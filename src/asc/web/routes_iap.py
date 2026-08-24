"""IAP workflow routes for asc Web UI (/api/iap/*)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from asc.commands.iap import _iap_phase_plan, _load_iap_config, _upload_iap_core
from asc.commands.iap_review_screenshots import (
    ReviewScreenshotUploadItem,
    attach_default_paths,
    extract_review_screenshot_paths,
    scan_missing_review_screenshots,
    upload_review_screenshots,
)
from asc.commands.subscriptions import _upload_subscriptions_core
from asc.config import Config
from asc.guard import GuardViolationError, enforce_config_guard
from asc.iap.diff import build_plan
from asc.iap.infer import apply_group_levels, infer_products
from asc.iap.local import (
    load_local_snapshot,
    merge_products,
    missing_local_screenshot_ids,
    normalize_snapshot,
    save_local_snapshot,
    snapshot_has_content,
    validate_snapshot,
)
from asc.iap.remote import pull_remote_snapshot
from asc.iap.translator import make_iap_translator
from asc.listing.local import FileChangedError
from asc.progress import ProcessCanceled
from asc.utils import make_api_from_config
from asc.web.i18n import t
from asc.web.task_runner import (
    TaskTerminalError,
    sanitize_replay,
    start_background_task,
)
from asc.web.tasks import task_store as _task_store

router = APIRouter()


def _cookie_profile(request: Request) -> str:
    return (request.cookies.get("asc_profile") or "").strip()


def _lang(request: Request) -> str:
    from asc.web.i18n import COOKIE_NAME, resolve_lang

    return getattr(request.state, "lang", None) or resolve_lang(
        cookie=request.cookies.get(COOKIE_NAME),
        accept_language=request.headers.get("accept-language"),
    )


def _no_profile_payload(lang: str) -> dict:
    return {
        "ok": False,
        "level": "error",
        "message": t("api.no_profile", lang=lang),
        "detail": {},
    }


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _require_profile(request: Request) -> str:
    profile = _cookie_profile(request)
    if profile:
        try:
            enforce_config_guard(Config(app_name=profile), interactive=False)
        except GuardViolationError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
    return profile


def _default_iap_file(profile: str, explicit: str | None = None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    if profile:
        config = Config(app_name=profile)
        return config.iap_path or "data/iap_packages.json"
    return "data/iap_packages.json"


async def _read_object(request: Request) -> dict:
    body = await request.body()
    if not body.strip():
        return {}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    return payload


# ---------- local snapshot ----------


@router.get("/local")
def iap_local(request: Request, iap_file: str = ""):
    """Read local JSON. Missing file → empty snapshot (not 400)."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)
    path = _default_iap_file(profile, iap_file or None)
    try:
        snapshot, mtime, exists = load_local_snapshot(path)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {
        "ok": True,
        "iapFile": path,
        "exists": exists,
        "hasContent": snapshot_has_content(snapshot),
        "mtime": mtime,
        "snapshot": snapshot,
        "issues": validate_snapshot(snapshot),
    }


@router.post("/local/save")
async def iap_local_save(request: Request):
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)
    body = await _read_object(request)
    path = _default_iap_file(profile, body.get("iap_file") or body.get("iapFile"))
    from asc.web.security import WebPathError, forbidden_response, resolve_web_data_path

    try:
        path = str(resolve_web_data_path(path))
    except WebPathError:
        return forbidden_response()
    snapshot = body.get("snapshot")
    if snapshot is None:
        raise HTTPException(status_code=400, detail="snapshot is required")
    expected = body.get("expected_mtime")
    if expected is not None and not isinstance(expected, (int, float)):
        raise HTTPException(status_code=400, detail="expected_mtime must be a number")
    try:
        new_mtime = await asyncio.to_thread(
            save_local_snapshot, path, snapshot, expected_mtime=expected
        )
    except FileChangedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except OSError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True, "mtime": new_mtime, "iapFile": path}


@router.post("/infer")
async def iap_infer(request: Request):
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)
    body = await _read_object(request)
    raw = body.get("text") or body.get("table") or body.get("raw") or ""
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="text is required")
    app_short = str(body.get("appShortName") or body.get("app_short_name") or "").strip()
    territory = str(body.get("baseTerritory") or "USA").strip() or "USA"
    levels = body.get("groupLevels") or body.get("group_levels")
    result = infer_products(raw, app_short_name=app_short, default_territory=territory)
    if isinstance(levels, dict) and levels:
        coerced: dict[str, int] = {}
        for key, value in levels.items():
            try:
                coerced[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        result["snapshot"] = apply_group_levels(result["snapshot"], coerced)
    return result


def _iap_pull_impl(profile: str, body: dict[str, Any]) -> dict | JSONResponse:
    path = _default_iap_file(profile, body.get("iap_file") or body.get("iapFile"))
    product_ids = body.get("productIds") or body.get("product_ids") or []
    group_names = body.get("groupNames") or body.get("groups") or []
    if product_ids is None:
        product_ids = []
    if group_names is None:
        group_names = []
    if not isinstance(product_ids, list) or not isinstance(group_names, list):
        raise HTTPException(status_code=400, detail="productIds / groupNames must be arrays")
    product_ids = [str(x).strip() for x in product_ids if str(x).strip()]
    group_names = [str(x).strip() for x in group_names if str(x).strip()]
    expected = body.get("expected_mtime")
    if expected is not None and not isinstance(expected, (int, float)):
        raise HTTPException(status_code=400, detail="expected_mtime must be a number")
    if "write" in body:
        write = _as_bool(body.get("write"))
    elif _as_bool(body.get("preview")):
        write = False
    else:
        write = False

    config = Config(app_name=profile)
    api, app_id = make_api_from_config(config)
    remote = pull_remote_snapshot(
        api,
        app_id,
        product_ids=product_ids or None,
        group_names=group_names or None,
    )
    local, mtime, _exists = load_local_snapshot(path)
    wanted = set(product_ids) if product_ids else None
    merged = merge_products(local, remote, product_ids=wanted)
    written = False
    if write:
        try:
            mtime = save_local_snapshot(path, merged, expected_mtime=expected)
            written = True
        except FileChangedError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {
        "ok": True,
        "iapFile": path,
        "mtime": mtime,
        "snapshot": merged,
        "written": written,
        "imported": {
            "items": len(remote.get("items") or []),
            "groups": len(remote.get("subscriptionGroups") or []),
        },
    }


@router.post("/pull")
async def iap_pull(request: Request):
    """Import from App Store Connect. ASC work runs in a thread pool."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)
    body = await _read_object(request)
    return await asyncio.to_thread(_iap_pull_impl, profile, body)


def _iap_compare_phase_plan() -> list[tuple[str, int, str]]:
    return [
        ("local", 8, "读取本地 JSON"),
        ("iap", 32, "拉取一次性 IAP"),
        ("groups", 32, "拉取订阅组"),
        ("shots", 22, "扫描审核截图"),
        ("done", 6, "完成"),
    ]


def _finalize_plan_payload(
    snapshot: dict[str, Any],
    remote: dict[str, Any] | None,
    path: str,
    mtime: float | None,
    exists: bool,
    *,
    update_existing: bool,
    remote_ok: bool,
    error: str,
    missing_on_store: list[str] | None = None,
) -> dict[str, Any]:
    plan = build_plan(
        snapshot,
        remote,
        update_existing=update_existing,
        remote_ok=remote_ok,
        error=error,
    )
    payload = plan.to_dict()
    missing_shots = missing_local_screenshot_ids(snapshot, path)
    for item in payload.get("items") or []:
        if isinstance(item, dict):
            item["missingScreenshot"] = item.get("productId") in missing_shots
    payload["iapFile"] = path
    payload["mtime"] = mtime
    payload["exists"] = exists
    payload["hasContent"] = snapshot_has_content(snapshot)
    if missing_on_store is not None:
        payload["missingOnStore"] = missing_on_store
    return payload


@router.get("/plan")
def iap_plan(
    request: Request,
    iap_file: str = "",
    update_existing: str = "",
):
    """Local vs ASC publish plan. Sync def so ASC stays off the event loop."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)
    path = _default_iap_file(profile, iap_file or None)
    snapshot, mtime, exists = load_local_snapshot(path)
    remote_ok = True
    error = ""
    remote: dict[str, Any] | None = None
    try:
        config = Config(app_name=profile)
        api, app_id = make_api_from_config(config)
        remote = pull_remote_snapshot(api, app_id)
    except Exception as exc:  # noqa: BLE001
        remote_ok = False
        error = str(exc)
    return _finalize_plan_payload(
        snapshot,
        remote,
        path,
        mtime,
        exists,
        update_existing=_as_bool(update_existing),
        remote_ok=remote_ok,
        error=error,
    )


def _start_iap_compare_task(
    profile: str,
    iap_file: str,
    update_existing: bool,
    snapshot: dict[str, Any] | None = None,
) -> str:
    task_id = _task_store.create(
        "iap-compare",
        profile=profile,
        replay=sanitize_replay(
            "iap-compare",
            profile,
            False,
            {
                "iap_file": iap_file,
                "update_existing": update_existing,
            },
        ),
    )
    guard_enforcer = enforce_config_guard

    def run(reporter, cancel_event):
        try:
            config = Config(app_name=profile)
            guard_enforcer(config, interactive=False)
            path = _default_iap_file(profile, iap_file)
            reporter.set_phases(_iap_compare_phase_plan())

            reporter.phase("local")
            disk_snap, mtime, exists = load_local_snapshot(path)
            local_snap = snapshot
            if local_snap is not None:
                try:
                    local_snap = normalize_snapshot(local_snap)
                except ValueError:
                    local_snap = disk_snap
            else:
                local_snap = disk_snap
            reporter.progress(1, 1, msg="ok")
            if cancel_event.is_set():
                raise ProcessCanceled("iap compare canceled")

            remote_ok = True
            error = ""
            remote: dict[str, Any] | None = None
            api = None
            app_id = ""
            try:
                api, app_id = make_api_from_config(config)
                remote = pull_remote_snapshot(
                    api,
                    app_id,
                    reporter=reporter,
                    cancel_event=cancel_event,
                )
            except ProcessCanceled:
                raise
            except Exception as exc:  # noqa: BLE001
                remote_ok = False
                error = str(exc)
                reporter.phase("iap")
                reporter.progress(1, 1, msg="error")
                reporter.phase("groups")
                reporter.progress(1, 1, msg="error")

            if cancel_event.is_set():
                raise ProcessCanceled("iap compare canceled")

            missing_on_store: list[str] = []
            reporter.phase("shots")
            if api is not None:
                try:
                    scan = scan_missing_review_screenshots(api, app_id)
                    missing_on_store = [
                        str(target.product_id).strip()
                        for target in scan.targets
                        if str(target.product_id).strip()
                    ]
                    reporter.progress(1, 1, msg=str(len(missing_on_store)))
                except Exception as exc:  # noqa: BLE001
                    reporter.log(f"⚠️ {exc}")
                    reporter.progress(1, 1, msg="error")
            else:
                reporter.progress(1, 1, msg="skip")

            if cancel_event.is_set():
                raise ProcessCanceled("iap compare canceled")

            reporter.phase("done")
            payload = _finalize_plan_payload(
                local_snap,
                remote,
                path,
                mtime,
                exists,
                update_existing=update_existing,
                remote_ok=remote_ok,
                error=error,
                missing_on_store=missing_on_store,
            )
            reporter.progress(1, 1, msg="ok")
            reporter.done("核对完成")
            return payload
        except ProcessCanceled:
            reporter.log("⏹ 用户已终止商店核对")
            raise

    return start_background_task(
        _task_store,
        kind="iap-compare",
        profile=profile,
        verbose=False,
        run=run,
        task_id=task_id,
    )


@router.post("/compare")
async def iap_compare(request: Request):
    """Start a background local-vs-ASC compare; result lives on the task."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)
    body = await _read_object(request)
    path = _default_iap_file(profile, body.get("iap_file") or body.get("iapFile"))
    update_existing = _as_bool(body.get("update_existing") or body.get("updateExisting"))
    snapshot_in = body.get("snapshot")
    snapshot = snapshot_in if isinstance(snapshot_in, dict) else None

    def _start():
        return _start_iap_compare_task(
            profile=profile,
            iap_file=path,
            update_existing=update_existing,
            snapshot=snapshot,
        )

    task_id = await asyncio.to_thread(_start)
    return {"task_id": task_id}


def _iap_translate_impl(profile: str, lang: str, body: dict[str, Any]) -> dict | JSONResponse:
    config = Config(app_name=profile)
    if not config.llm_api_key:
        return JSONResponse(
            {
                "ok": False,
                "error": "api_key",
                "message": t("api.llm_api_key_required", lang=lang),
            },
            status_code=400,
        )
    source_locale = str(body.get("source_locale") or body.get("sourceLocale") or "en-US")
    mode = str(body.get("mode") or "translate").strip() or "translate"
    if mode not in {"translate", "rewrite"}:
        raise HTTPException(status_code=400, detail="mode must be translate or rewrite")
    fields = body.get("fields")
    if not isinstance(fields, list) or not fields:
        raise HTTPException(status_code=400, detail="fields is required")
    translator = make_iap_translator(config)
    translations: list[dict[str, Any]] = []
    errors: list[str] = []
    for row in fields:
        if not isinstance(row, dict):
            continue
        locale = str(row.get("locale") or "").strip()
        if not locale:
            continue
        name = str(row.get("name") or "")
        has_desc = "description" in row
        description = str(row.get("description") or "") if has_desc else None
        try:
            translated = translator.translate_fields(
                source_locale=source_locale,
                target_locale=locale,
                name=name,
                description=description,
                mode=mode,
            )
            translations.append(translated)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{locale}: {exc}")
            fallback = {"locale": locale, "name": name}
            if has_desc:
                fallback["description"] = str(row.get("description") or "")
            translations.append(fallback)
    return {"ok": True, "translations": translations, "errors": errors}


@router.post("/translate")
async def iap_translate(request: Request):
    """Translate/rewrite IAP copy in-request (thread pool, no task bar)."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)
    body = await _read_object(request)
    return await asyncio.to_thread(_iap_translate_impl, profile, lang, body)


# ---------- existing check / run / review ----------


def _default_iap_review_screenshot_file(
    config: Config, explicit_iap_file: str | None
) -> str:
    if explicit_iap_file:
        return explicit_iap_file
    return config.iap_path or "data/iap_packages.json"


def _scan_iap_review_screenshot_targets(
    profile: str, iap_file: str | None = None
) -> dict:
    config = Config(app_name=profile)
    api, app_id = make_api_from_config(config)
    scan = scan_missing_review_screenshots(api, app_id)
    paths_by_product_id = extract_review_screenshot_paths(
        _default_iap_review_screenshot_file(config, iap_file)
    )
    attach_default_paths(scan.targets, paths_by_product_id)
    return {
        "ok": True,
        "count": len(scan.targets),
        "targets": [target.to_dict() for target in scan.targets],
        "errors": list(scan.errors),
    }


def _review_screenshot_target_key(item) -> tuple[str, str, str]:
    return (item.kind, item.id, item.product_id)


def _ineligible_iap_review_screenshot_items(
    api, app_id: str, items: list[ReviewScreenshotUploadItem]
) -> tuple[list[ReviewScreenshotUploadItem], list[str]]:
    scan = scan_missing_review_screenshots(api, app_id)
    eligible = {_review_screenshot_target_key(target) for target in scan.targets}
    invalid = [
        item
        for item in items
        if _review_screenshot_target_key(item) not in eligible
    ]
    return invalid, list(scan.errors)


def _start_iap_review_screenshots_task(
    profile: str,
    items: list[ReviewScreenshotUploadItem],
    dry_run: bool,
    verbose: bool = False,
) -> str:
    task_id = _task_store.create(
        "iap-review-screenshots",
        profile=profile,
        replay=sanitize_replay(
            "iap-review-screenshots",
            profile,
            verbose,
            {
                "dry_run": dry_run,
                "items": [
                    {
                        "kind": item.kind,
                        "id": item.id,
                        "productId": item.product_id,
                        "path": item.path,
                    }
                    for item in items
                ],
            },
        ),
    )
    guard_enforcer = enforce_config_guard

    def run(reporter, cancel_event):
        try:
            config = Config(app_name=profile)
            guard_enforcer(config, interactive=False)
            api, app_id = make_api_from_config(config)

            invalid_items, scan_errors = _ineligible_iap_review_screenshot_items(
                api, app_id, items
            )
            for error in scan_errors:
                reporter.log(f"⚠️ {error}")
            if invalid_items:
                message = (
                    "review screenshot target no longer eligible for current "
                    "app/profile or already has a screenshot"
                )
                labels = ", ".join(
                    f"{item.kind}:{item.product_id} ({item.id})"
                    for item in invalid_items
                )
                reporter.log(f"❌ {message}: {labels}")
                payload = {
                    "success": False,
                    "uploaded": 0,
                    "skipped": 0,
                    "failed": len(invalid_items),
                    "failures": [
                        {
                            "productId": item.product_id,
                            "error": f"{message}: {item.kind}:{item.id}",
                        }
                        for item in invalid_items
                    ],
                    "error": f"{message}: {labels}",
                }
                raise TaskTerminalError(payload["error"], payload)

            result = upload_review_screenshots(
                api, items, dry_run=dry_run, reporter=reporter
            )
            payload = {
                "success": result.failed == 0,
                "uploaded": result.uploaded,
                "skipped": result.skipped,
                "failed": result.failed,
                "failures": [
                    {"productId": product_id, "error": error}
                    for product_id, error in result.failures
                ],
            }
            if result.failed == 0:
                return payload
            raise TaskTerminalError(
                f"review screenshot upload failed: {result.failed} item(s)",
                payload,
            )
        except Exception as e:
            if not isinstance(e, TaskTerminalError):
                reporter.fail(f"❌ 错误：{e}")
                raise TaskTerminalError(
                    str(e),
                    {
                        "success": False,
                        "uploaded": 0,
                        "skipped": 0,
                        "failed": len(items) or 1,
                        "failures": [{"productId": "", "error": str(e)}],
                        "error": str(e),
                    },
                )
            raise

    return start_background_task(
        _task_store,
        kind="iap-review-screenshots",
        profile=profile,
        verbose=verbose,
        run=run,
        task_id=task_id,
    )


def _start_iap_task(
    profile: str,
    iap_file: str,
    dry_run: bool,
    update_existing: bool,
    verbose: bool = False,
) -> str:
    task_id = _task_store.create(
        "iap",
        profile=profile,
        replay=sanitize_replay(
            "iap",
            profile,
            verbose,
            {
                "iap_file": iap_file,
                "dry_run": dry_run,
                "update_existing": update_existing,
            },
        ),
    )
    guard_enforcer = enforce_config_guard

    def run(reporter, cancel_event):
        try:
            config = Config(app_name=profile)
            guard_enforcer(config, interactive=False)
            api, app_id = make_api_from_config(config)

            items, groups = _load_iap_config(iap_file)
            reporter.set_phases(
                _iap_phase_plan(has_items=bool(items), has_groups=bool(groups))
            )
            reporter.phase("parse")
            reporter.progress(1, 1, msg="ok")

            if items:
                reporter.log(f"📦 一次性 IAP: {len(items)} 项")
                failed_items = _upload_iap_core(
                    api,
                    app_id,
                    items,
                    dry_run=dry_run,
                    update_existing=update_existing,
                    reporter=reporter,
                    manage_phases=False,
                    finalize=not bool(groups),
                    cancel_event=cancel_event,
                )
                if failed_items:
                    raise RuntimeError(f"iap upload failed: {failed_items} item(s)")
            if groups:
                if cancel_event.is_set():
                    raise ProcessCanceled("iap upload canceled")
                total_subs = sum(len(g.get("subscriptions", [])) for g in groups)
                reporter.log(f"🔁 订阅: {len(groups)} 组 / {total_subs} 商品")
                failed = _upload_subscriptions_core(
                    api,
                    app_id,
                    groups,
                    update_existing=update_existing,
                    dry_run=dry_run,
                    reporter=reporter,
                    manage_phases=False,
                    finalize=True,
                    cancel_event=cancel_event,
                )
                if failed:
                    raise RuntimeError(f"subscription upload failed: {failed} item(s)")

            if cancel_event.is_set():
                raise ProcessCanceled("iap upload canceled")
            return {"success": True}
        except ProcessCanceled:
            reporter.log("⏹ 用户已终止 IAP 上传")
            raise

    return start_background_task(
        _task_store,
        kind="iap",
        profile=profile,
        verbose=verbose,
        run=run,
        task_id=task_id,
    )


@router.post("/run")
def iap_run(
    request: Request,
    iap_file: str = Form("data/iap_packages.json"),
    dry_run: str = Form(""),
    update_existing: str = Form(""),
    verbose: str = Form(""),
):
    """Sync def so TaskStore.create(wait=True) stays off the event loop."""
    lang = _lang(request)
    profile = _cookie_profile(request)
    if not profile:
        return JSONResponse({"error": t("api.no_profile", lang=lang)}, status_code=400)
    task_id = _start_iap_task(
        profile=profile,
        iap_file=iap_file,
        dry_run=_as_bool(dry_run),
        update_existing=_as_bool(update_existing),
        verbose=_as_bool(verbose),
    )
    return {"task_id": task_id}


@router.post("/check")
def iap_check(request: Request):
    """Sync def so Config + JSON parse stay off the event loop."""
    lang = _lang(request)
    profile = _cookie_profile(request)
    if not profile:
        return _no_profile_payload(lang)
    try:
        config = Config(app_name=profile)
        iap_path = Path(config.iap_path) if config.iap_path else Path("data/iap_packages.json")
        if not iap_path.exists():
            return {
                "ok": False,
                "level": "error",
                "message": t("api.iap_file_missing", lang=lang, path=iap_path),
                "detail": {},
            }
        items, groups = _load_iap_config(str(iap_path))
        total = len(items) + len(groups)
        return {
            "ok": True,
            "level": "success",
            "message": t(
                "api.iap_config_valid",
                lang=lang,
                items=len(items),
                groups=len(groups),
            ),
            "detail": {"items": len(items), "groups": len(groups), "total": total},
        }
    except Exception as e:
        return {"ok": False, "level": "error", "message": str(e), "detail": {}}


@router.post("/review-screenshots/scan")
async def iap_review_screenshots_scan(request: Request):
    lang = _lang(request)
    profile = _cookie_profile(request)
    if not profile:
        return JSONResponse({"error": t("api.no_profile", lang=lang)}, status_code=400)
    payload = await _read_object(request)
    iap_file = payload.get("iapFile") if isinstance(payload, dict) else None
    if iap_file is not None and not isinstance(iap_file, str):
        raise HTTPException(status_code=400, detail="iapFile must be a string")
    try:
        return await asyncio.to_thread(
            _scan_iap_review_screenshot_targets, profile, iap_file
        )
    except Exception as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "count": 0,
                "targets": [],
                "errors": [str(exc)],
            },
            status_code=500,
        )


@router.post("/review-screenshots/upload")
async def iap_review_screenshots_upload(request: Request):
    lang = _lang(request)
    profile = _cookie_profile(request)
    if not profile:
        return JSONResponse({"error": t("api.no_profile", lang=lang)}, status_code=400)
    payload = await _read_object(request)

    items_payload = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items_payload, list) or not items_payload:
        raise HTTPException(status_code=400, detail="items required")

    dry_run = payload.get("dryRun", False) if isinstance(payload, dict) else False
    if not isinstance(dry_run, bool):
        raise HTTPException(status_code=400, detail="dryRun must be a boolean")

    verbose = payload.get("verbose", False) if isinstance(payload, dict) else False
    if not isinstance(verbose, bool):
        verbose = _as_bool(verbose)

    items: list[ReviewScreenshotUploadItem] = []
    for item in items_payload:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="invalid item")
        kind = item.get("kind")
        item_id = item.get("id")
        product_id = item.get("productId")
        path = item.get("path")
        values = (kind, item_id, product_id, path)
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise HTTPException(status_code=400, detail="invalid item")
        if kind not in {"iap", "subscription"}:
            raise HTTPException(status_code=400, detail="invalid item")
        items.append(
            ReviewScreenshotUploadItem(
                kind=kind,
                id=item_id,
                product_id=product_id,
                path=path,
            )
        )

    if not items:
        raise HTTPException(status_code=400, detail="items required")

    def _start():
        return _start_iap_review_screenshots_task(
            profile=profile,
            items=items,
            dry_run=dry_run,
            verbose=verbose,
        )

    task_id = await asyncio.to_thread(_start)
    return {"task_id": task_id}
