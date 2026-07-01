"""Helpers for scanning missing IAP review screenshots."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import typer

from asc.config import Config
from asc.error_handler import get_action_hint
from asc.guard import Guard, GuardViolationError
from asc.i18n import HELP, t
from asc.utils import make_api_from_config, resolve_app_profile


REVIEW_SCREENSHOT_EXTS = {".png", ".jpg", ".jpeg"}
REVIEW_SCREENSHOT_WARNING_BYTES = 5 * 1024 * 1024


@dataclass
class ReviewScreenshotTarget:
    kind: str
    id: str
    product_id: str
    name: str = ""
    group_name: str = ""
    default_path: str = ""
    path_status: str = "empty"

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "id": self.id,
            "productId": self.product_id,
            "name": self.name,
            "groupName": self.group_name,
            "defaultPath": self.default_path,
            "pathStatus": self.path_status,
        }


@dataclass
class ReviewScreenshotScanResult:
    targets: list[ReviewScreenshotTarget] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": [target.to_dict() for target in self.targets],
            "errors": self.errors,
        }


@dataclass
class PathValidationResult:
    ok: bool
    path: Path | None = None
    error: str = ""
    warning: str = ""


@dataclass
class ReviewScreenshotUploadItem:
    kind: str
    id: str
    product_id: str
    path: str


@dataclass
class ReviewScreenshotUploadResult:
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)


def scan_missing_review_screenshots(api, app_id: str) -> ReviewScreenshotScanResult:
    """Scan ASC online state and return products missing review screenshots."""
    result = ReviewScreenshotScanResult()

    for iap in api.list_in_app_purchases(app_id):
        iap_id = str(iap.get("id", ""))
        attrs = iap.get("attributes", {}) or {}
        product_id = str(attrs.get("productId", ""))
        name = str(attrs.get("name", ""))
        try:
            screenshots = api.list_in_app_purchase_review_screenshots(iap_id)
        except Exception as exc:
            result.errors.append(f"IAP {product_id}: {exc}")
            continue
        if not screenshots:
            result.targets.append(
                ReviewScreenshotTarget(
                    kind="iap",
                    id=iap_id,
                    product_id=product_id,
                    name=name,
                )
            )

    for group in api.list_subscription_groups(app_id):
        group_id = str(group.get("id", ""))
        group_attrs = group.get("attributes", {}) or {}
        group_name = str(group_attrs.get("referenceName", ""))
        for sub in api.list_subscriptions(group_id):
            sub_id = str(sub.get("id", ""))
            attrs = sub.get("attributes", {}) or {}
            product_id = str(attrs.get("productId", ""))
            name = str(attrs.get("name", ""))
            try:
                screenshots = api.list_subscription_review_screenshots(sub_id)
            except Exception as exc:
                result.errors.append(f"Subscription {product_id}: {exc}")
                continue
            if not screenshots:
                result.targets.append(
                    ReviewScreenshotTarget(
                        kind="subscription",
                        id=sub_id,
                        product_id=product_id,
                        name=name,
                        group_name=group_name,
                    )
                )

    return result


def extract_review_screenshot_paths(iap_file: str) -> dict[str, str]:
    """Extract optional review.screenshot defaults without full upload validation."""
    config_path = Path(iap_file)
    if not config_path.exists():
        return {}

    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}

    paths: dict[str, str] = {}
    base_dir = config_path.resolve().parent

    def add_path(item: Any) -> None:
        if not isinstance(item, dict):
            return
        product_id = item.get("productId")
        review = item.get("review")
        if not isinstance(product_id, str) or not product_id.strip():
            return
        if not isinstance(review, dict):
            return
        screenshot = review.get("screenshot")
        if not isinstance(screenshot, str) or not screenshot.strip():
            return

        path = Path(screenshot)
        paths[product_id] = str(path if path.is_absolute() else base_dir / path)

    if isinstance(data, list):
        for item in data:
            add_path(item)
    elif isinstance(data, dict):
        for item in data.get("items", []) or []:
            add_path(item)
        for item in data.values():
            if isinstance(item, dict):
                add_path(item)
        for group in data.get("subscriptionGroups", []) or []:
            if not isinstance(group, dict):
                continue
            for sub in group.get("subscriptions", []) or []:
                add_path(sub)

    return paths


def attach_default_paths(
    targets: list[ReviewScreenshotTarget], paths_by_product_id: dict[str, str]
) -> None:
    for target in targets:
        default_path = paths_by_product_id.get(target.product_id)
        if default_path:
            target.default_path = default_path


def validate_review_screenshot_path(path_value) -> PathValidationResult:
    if not isinstance(path_value, str) or not path_value.strip():
        return PathValidationResult(False, error="review screenshot path required")

    path = Path(path_value)
    if not path.exists() or not path.is_file():
        return PathValidationResult(False, error=f"file not found: {path_value}")
    if path.suffix.lower() not in REVIEW_SCREENSHOT_EXTS:
        return PathValidationResult(
            False,
            error=f"review screenshot must be .png/.jpg/.jpeg, got {path.suffix}",
        )

    warning = ""
    size = path.stat().st_size
    if size > REVIEW_SCREENSHOT_WARNING_BYTES:
        warning = (
            f"review screenshot exceeds 5MB ({size} bytes); continuing and "
            "leaving final validation to App Store Connect"
        )
    return PathValidationResult(True, path=path, warning=warning)


def _upload_iap_review_screenshot_file(api, iap_id: str, path: Path) -> None:
    file_bytes = path.read_bytes()
    reservation = api.create_in_app_purchase_review_screenshot_reservation(
        iap_id, path.name, len(file_bytes)
    )
    screenshot_id = reservation["data"]["id"]
    upload_operations = reservation["data"].get("attributes", {}).get(
        "uploadOperations", []
    )
    api.upload_in_app_purchase_review_screenshot(upload_operations, file_bytes)
    md5 = hashlib.md5(file_bytes).hexdigest()
    api.commit_in_app_purchase_review_screenshot(screenshot_id, md5)


def _upload_subscription_review_screenshot_file(api, sub_id: str, path: Path) -> None:
    file_bytes = path.read_bytes()
    reservation = api.create_subscription_review_screenshot_reservation(
        sub_id, path.name, len(file_bytes)
    )
    screenshot_id = reservation["data"]["id"]
    upload_operations = reservation["data"].get("attributes", {}).get(
        "uploadOperations", []
    )
    api.upload_subscription_review_screenshot(upload_operations, file_bytes)
    md5 = hashlib.md5(file_bytes).hexdigest()
    api.commit_subscription_review_screenshot(screenshot_id, md5)


def _has_existing_review_screenshot(api, item: ReviewScreenshotUploadItem) -> bool:
    if item.kind == "iap":
        return bool(api.list_in_app_purchase_review_screenshots(item.id))
    if item.kind == "subscription":
        return bool(api.list_subscription_review_screenshots(item.id))
    raise ValueError(f"unsupported review screenshot kind: {item.kind}")


def upload_review_screenshots(
    api, items: list[ReviewScreenshotUploadItem], dry_run: bool = False
) -> ReviewScreenshotUploadResult:
    result = ReviewScreenshotUploadResult()
    total = len(items)

    for idx, item in enumerate(items, start=1):
        try:
            validation = validate_review_screenshot_path(item.path)
            if not validation.ok:
                result.failed += 1
                result.failures.append((item.product_id, validation.error))
                print(f"  ❌ {item.product_id}: {validation.error}")
                continue

            if validation.warning:
                print(f"  ⚠️  {item.product_id}: {validation.warning}")

            if _has_existing_review_screenshot(api, item):
                result.skipped += 1
                print(f"  {item.product_id}: 审核截图已存在，跳过")
                continue

            path = validation.path
            if path is None:
                raise ValueError("validated screenshot path missing")

            if dry_run:
                result.skipped += 1
                print(f"  [预览] {item.product_id}: 将上传审核截图 {path.name}")
                continue

            if item.kind == "iap":
                _upload_iap_review_screenshot_file(api, item.id, path)
            elif item.kind == "subscription":
                _upload_subscription_review_screenshot_file(api, item.id, path)
            else:
                raise ValueError(f"unsupported review screenshot kind: {item.kind}")

            result.uploaded += 1
            print(f"  {item.product_id}: 审核截图 {path.name} 上传 ✅")
        except Exception as exc:
            result.failed += 1
            result.failures.append((item.product_id, str(exc)))
            print(f"  ❌ {item.product_id}: {exc}")
        finally:
            pct = int(idx / total * 100) if total else 100
            print(f"[PROGRESS:{pct}:IAP 审核截图 {idx}/{total}]")

    return result


def _default_iap_file(config: Config, explicit_iap_file: Optional[str]) -> str:
    if explicit_iap_file:
        return explicit_iap_file
    return config.iap_path or "data/iap_packages.json"


def _print_missing_targets(targets: list[ReviewScreenshotTarget]) -> None:
    iap_targets = [target for target in targets if target.kind == "iap"]
    subscription_targets = [
        target for target in targets if target.kind == "subscription"
    ]

    if iap_targets:
        typer.echo("\nIAP 缺少审核截图:")
        for target in iap_targets:
            label = target.name or target.product_id
            typer.echo(f"  - {target.product_id} ({label})")

    if subscription_targets:
        typer.echo("\n订阅缺少审核截图:")
        for target in subscription_targets:
            label = target.name or target.product_id
            group = f" / {target.group_name}" if target.group_name else ""
            typer.echo(f"  - {target.product_id} ({label}{group})")


def _collect_upload_items(
    targets: list[ReviewScreenshotTarget], no_prompt: bool
) -> list[ReviewScreenshotUploadItem]:
    items: list[ReviewScreenshotUploadItem] = []

    for target in targets:
        path_value = target.default_path
        if not path_value and not no_prompt:
            prompt_text = f"{target.product_id} 审核截图路径 (留空跳过)"
            path_value = typer.prompt(prompt_text, default="", show_default=False)

        if not path_value:
            continue

        validation = validate_review_screenshot_path(path_value)
        if not validation.ok:
            typer.echo(f"  ❌ {target.product_id}: {validation.error}", err=True)
            continue
        if validation.warning:
            typer.echo(f"  ⚠️  {target.product_id}: {validation.warning}")

        items.append(
            ReviewScreenshotUploadItem(
                kind=target.kind,
                id=target.id,
                product_id=target.product_id,
                path=str(validation.path),
            )
        )

    return items


def cmd_iap_screenshots(
    iap_file: Optional[str] = typer.Option(
        None,
        "--iap-file",
        "-f",
        help="IAP 配置文件路径，用于读取 review.screenshot 默认路径",
    ),
    app: Optional[str] = typer.Option(
        None, "--app", "-a", help=t(HELP["app_profile_name"])
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-d", help="预览将上传的审核截图，不实际上传"
    ),
    no_prompt: bool = typer.Option(
        False, "--no-prompt", help="不交互提示，仅上传配置中已有默认路径的截图"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过上传确认"),
):
    """Upload missing IAP and subscription review screenshots."""
    config = Config(app)
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env
        import os

        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        import os

        os.environ.pop("_ASC_APP", None)
    app = resolved_app
    config = Config(app)
    guard = Guard()
    if guard.is_enabled():
        try:
            guard.check_and_enforce(
                app_id=config.app_id or "",
                app_name=config.app_name or app or "",
                key_id=config.key_id or "",
                issuer_id=config.issuer_id or "",
            )
        except GuardViolationError as e:
            typer.echo(f"❌ {e}", err=True)
            hint = get_action_hint(e)
            if hint:
                typer.echo(f"💡 {hint}", err=True)
            raise typer.Exit(1)
    api, app_id = make_api_from_config(config)

    scan = scan_missing_review_screenshots(api, app_id)
    for warning in scan.errors:
        typer.echo(f"⚠️  {warning}", err=True)

    if not scan.targets:
        typer.echo("没有缺少审核截图的 IAP/订阅。")
        return

    paths_by_product_id = extract_review_screenshot_paths(
        _default_iap_file(config, iap_file)
    )
    attach_default_paths(scan.targets, paths_by_product_id)
    _print_missing_targets(scan.targets)

    upload_items = _collect_upload_items(scan.targets, no_prompt)
    if not upload_items:
        typer.echo("没有选择审核截图。No screenshots selected.")
        return

    typer.echo(f"\n准备上传审核截图: {len(upload_items)} 个")
    if not dry_run and not yes:
        confirmed = typer.confirm("确认上传这些审核截图?", default=False)
        if not confirmed:
            typer.echo("已取消。")
            raise typer.Exit(1)

    result = upload_review_screenshots(api, upload_items, dry_run=dry_run)
    typer.echo(
        f"\n完成: uploaded={result.uploaded}, skipped={result.skipped}, "
        f"failed={result.failed}"
    )
    if result.failures:
        for product_id, error in result.failures:
            typer.echo(f"  ❌ {product_id}: {error}", err=True)

    if result.failed:
        raise typer.Exit(1)
