"""Helpers for scanning missing IAP review screenshots."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


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
