"""Local listing (CSV text + screenshots) routes for asc Web UI (/api/listing/*)."""
from __future__ import annotations

import asyncio
import mimetypes
import os
from dataclasses import asdict
from pathlib import Path

import requests
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from asc.config import Config
from asc.guard import GuardViolationError, enforce_config_guard
from asc.listing.diff import diff_snapshots
from asc.listing.local import (
    FileChangedError,
    PathTraversalError,
    _assert_under_root,
    _safe_locale_name,
    add_screenshot,
    apply_screenshot_order,
    delete_screenshot,
    find_locale_screenshot_dir,
    load_local_text_snapshot,
    replace_screenshot,
    save_local_csv,
    scan_local_screenshots,
)
from asc.listing.models import (
    FIELD_NAMES,
    ListingSnapshot,
    LocaleListing,
    TEXT_FIELDS,
    snapshot_has_content,
)
from asc.listing.translator import make_listing_translator
from asc.listing.remote import (
    NoAppInfoError,
    NoEditableVersionError,
    attach_asc_screenshots,
    download_asc_screenshots,
    load_asc_text_snapshot,
    screenshot_thumb_url,
)
from asc.progress import ProcessCanceled
from asc.utils import make_api_from_config
from asc.web.i18n import t
from asc.web.task_runner import sanitize_replay, start_background_task
from asc.web.tasks import task_store

router = APIRouter()


def _cookie_profile(request: Request) -> str:
    """Return the explicitly selected Web profile cookie (may be empty)."""
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


def _require_profile(request: Request) -> str:
    """Resolve the selected profile and, if present, enforce Guard for it.

    Local CSV read/write does not itself call App Store Connect, but the
    workbench is scoped to the currently selected App profile like every
    other `/api/*` route, so guard checks stay consistent across the app.
    """
    profile = _cookie_profile(request)
    if profile:
        try:
            enforce_config_guard(Config(app_name=profile), interactive=False)
        except GuardViolationError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
    return profile


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _snapshot_to_dict(snapshot) -> dict:
    return asdict(snapshot)


def _empty_snapshot() -> ListingSnapshot:
    return ListingSnapshot(source="local", locales=[])


def _load_local_or_empty(csv_path: str) -> tuple[ListingSnapshot, float | None, bool]:
    """Load CSV text. Missing file → empty snapshot (not an error)."""
    if not csv_path or not os.path.exists(csv_path):
        return _empty_snapshot(), None, False
    snapshot = load_local_text_snapshot(csv_path)
    mtime = os.path.getmtime(csv_path) if os.path.exists(csv_path) else None
    return snapshot, mtime, True


def _snapshot_from_payload(payload) -> ListingSnapshot:
    """Build a text-only ListingSnapshot from a JSON body (`locales` list)."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="snapshot must be an object")
    locales_payload = payload.get("locales")
    if locales_payload is None:
        locales_payload = []
    if not isinstance(locales_payload, list):
        raise HTTPException(status_code=400, detail="snapshot.locales must be a list")
    locales: list[LocaleListing] = []
    for item in locales_payload:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="invalid locale entry")
        locale = item.get("locale")
        fields = item.get("fields")
        if not isinstance(locale, str) or not locale.strip():
            raise HTTPException(status_code=400, detail="invalid locale entry")
        if not isinstance(fields, dict):
            fields = {}
        locales.append(
            LocaleListing(
                locale=locale.strip(),
                fields={name: "" if fields.get(name) is None else str(fields.get(name, "")) for name in FIELD_NAMES},
                screenshots={},
            )
        )
    return ListingSnapshot(source="local", locales=locales)


def _locale_status(fields: list) -> str:
    statuses = {getattr(item, "status", "") for item in fields}
    if "changed" in statuses:
        return "changed"
    if "local_only" in statuses:
        return "local-only"
    if statuses and statuses <= {"equal"}:
        return "equal"
    if "asc_only" in statuses:
        return "changed"
    return "unchecked"


def _resolve_data_file(path: str) -> Path:
    from asc.web.security import resolve_web_data_path

    return resolve_web_data_path(path)


def _resolve_under_root(root: str, path: str) -> Path:
    """Resolve `path`'s realpath and ensure it lies under `root`'s realpath.

    Raises `HTTPException(400)` otherwise. Used by every screenshot-editing
    endpoint below so callers can never read/write/delete files outside the
    screenshots directory they were given.
    """
    if not root or not path:
        raise HTTPException(status_code=400, detail="root and path are required")
    try:
        return _assert_under_root(root, path)
    except PathTraversalError:
        raise HTTPException(status_code=400, detail="path is outside root") from None


@router.get("/local")
async def listing_local(
    request: Request,
    csv_path: str,
    screenshots_dir: str = "",
):
    """Read a local CSV into a `ListingSnapshot`.

    When `screenshots_dir` is provided, it is scanned with
    `scan_local_screenshots` and merged into each matching locale's
    `screenshots` field (`displayType -> [ScreenshotItem]`); otherwise
    `screenshots` stays `{}` on every locale.
    """
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)

    try:
        snapshot, mtime, exists = _load_local_or_empty(csv_path)
    except (OSError, ValueError) as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    if screenshots_dir.strip():
        by_locale = scan_local_screenshots(screenshots_dir)
        for loc in snapshot.locales:
            if loc.locale in by_locale:
                loc.screenshots = by_locale[loc.locale]

    return {
        "ok": True,
        "csvPath": csv_path,
        "exists": exists,
        "hasContent": snapshot_has_content(snapshot),
        "mtime": mtime,
        "snapshot": _snapshot_to_dict(snapshot),
    }


@router.get("/thumb")
async def listing_thumb(path: str, root: str):
    """Serve a screenshot thumbnail/original file, restricted to `root`.

    Read-only local filesystem access (no ASC credentials involved), so this
    endpoint intentionally does not require a selected profile — mirrors
    `/api/browse`'s pattern of gating solely on a real-path containment check.
    """
    target = _resolve_under_root(root, path)
    from asc.web.security import WebPathError, resolve_web_data_path

    try:
        resolve_web_data_path(target)
    except WebPathError:
        raise HTTPException(status_code=403, detail="Forbidden") from None
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(str(target), media_type=media_type or "application/octet-stream")


@router.post("/local/save")
async def listing_local_save(request: Request):
    """Write edited locale fields back to `csv_path`, guarded by `expected_mtime`."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")

    csv_path = body.get("csv_path")
    if not isinstance(csv_path, str) or not csv_path.strip():
        raise HTTPException(status_code=400, detail="csv_path is required")
    from asc.web.security import WebPathError, forbidden_response

    try:
        csv_path = str(_resolve_data_file(csv_path))
    except WebPathError:
        return forbidden_response()

    expected_mtime = body.get("expected_mtime")
    if expected_mtime is not None and not isinstance(expected_mtime, (int, float)):
        raise HTTPException(status_code=400, detail="expected_mtime must be a number")

    locales_payload = body.get("locales")
    if not isinstance(locales_payload, list) or not locales_payload:
        raise HTTPException(status_code=400, detail="locales must be a non-empty list")

    locales: list[LocaleListing] = []
    for item in locales_payload:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="invalid locale entry")
        locale = item.get("locale")
        fields = item.get("fields")
        if not isinstance(locale, str) or not locale.strip():
            raise HTTPException(status_code=400, detail="invalid locale entry")
        if not isinstance(fields, dict):
            raise HTTPException(status_code=400, detail="invalid locale entry")
        locales.append(
            LocaleListing(
                locale=locale,
                fields={str(k): "" if v is None else str(v) for k, v in fields.items()},
                screenshots={},
            )
        )

    try:
        new_mtime = save_local_csv(csv_path, locales, expected_mtime=expected_mtime)
    except FileChangedError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=409)
    except OSError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    return {"ok": True, "mtime": new_mtime, "csvPath": csv_path, "written": True}


def _api_for_profile(profile: str):
    """Build ASC API client + app_id from the selected profile name."""
    config = Config(app_name=profile)
    return make_api_from_config(config)


def _merge_local_screenshots(snapshot, screenshots_dir: str) -> None:
    """In-place merge of scanned local screenshots into a text snapshot."""
    if not screenshots_dir.strip():
        return
    by_locale = scan_local_screenshots(screenshots_dir)
    for loc in snapshot.locales:
        if loc.locale in by_locale:
            loc.screenshots = by_locale[loc.locale]


def _asc_error_response(exc: Exception, lang: str) -> JSONResponse:
    if isinstance(exc, NoEditableVersionError):
        return JSONResponse(
            {
                "ok": False,
                "level": "warning",
                "message": t("api.no_editable_version_create", lang=lang),
                "error": str(exc),
                "detail": {},
            },
            status_code=400,
        )
    if isinstance(exc, NoAppInfoError):
        return JSONResponse(
            {
                "ok": False,
                "level": "error",
                "message": str(exc),
                "error": str(exc),
                "detail": {},
            },
            status_code=400,
        )
    return JSONResponse(
        {"ok": False, "error": str(exc), "message": str(exc)},
        status_code=400,
    )


@router.get("/diff")
def listing_diff(
    request: Request,
    csv_path: str,
    screenshots_dir: str = "",
):
    """Compare local CSV (+ screenshots) against ASC text + screenshot sets.

    Sync ``def`` so ASC HTTP stays off the event loop (Starlette threadpool).
    """
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)

    try:
        local = load_local_text_snapshot(csv_path)
    except (FileNotFoundError, OSError) as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    _merge_local_screenshots(local, screenshots_dir)

    try:
        api, app_id = _api_for_profile(profile)
        asc = load_asc_text_snapshot(api, app_id)
        attach_asc_screenshots(api, asc)
    except (NoEditableVersionError, NoAppInfoError) as e:
        return _asc_error_response(e, lang)
    except Exception as e:
        return JSONResponse(
            {"ok": False, "error": str(e), "message": str(e)},
            status_code=400,
        )

    diff = diff_snapshots(local, asc)
    mtime = os.path.getmtime(csv_path) if os.path.exists(csv_path) else None
    return {
        "ok": True,
        "mtime": mtime,
        "version": asc.version,
        "local": _snapshot_to_dict(local),
        "asc": _snapshot_to_dict(asc),
        "diff": asdict(diff),
    }


def _listing_compare_phase_plan() -> list[tuple[str, int, str]]:
    return [
        ("local", 10, "读取本地 CSV"),
        ("text", 40, "拉取商店文案"),
        ("shots", 40, "对照截图"),
        ("done", 10, "完成"),
    ]


def _finalize_listing_compare(
    local: ListingSnapshot,
    asc: ListingSnapshot | None,
    *,
    mtime: float | None,
    exists: bool,
    remote_ok: bool,
    error: str,
) -> dict:
    empty_asc = ListingSnapshot(source="asc", locales=[], version=None)
    diff = diff_snapshots(local, asc or empty_asc)
    locales = []
    for loc in diff.locales:
        local_row = next((item for item in local.locales if item.locale == loc.locale), None)
        has_shots = bool(local_row and any(local_row.screenshots.values()))
        locales.append(
            {
                "locale": loc.locale,
                "status": _locale_status(loc.fields),
                "missingScreenshots": not has_shots,
                "fields": [asdict(field) for field in loc.fields],
                "screenshots": [asdict(shot) for shot in loc.screenshots],
            }
        )
    return {
        "ok": remote_ok,
        "error": error,
        "mtime": mtime,
        "exists": exists,
        "hasContent": snapshot_has_content(local),
        "version": (asc.version if asc else None),
        "locales": locales,
        "diff": asdict(diff),
    }


def _start_listing_compare_task(
    profile: str,
    csv_path: str,
    screenshots_dir: str,
    snapshot: dict | None = None,
) -> str:
    task_id = task_store.create(
        "listing-compare",
        profile=profile,
        replay=sanitize_replay(
            "listing-compare",
            profile,
            False,
            {"csv_path": csv_path, "screenshots_dir": screenshots_dir},
        ),
    )

    def run(reporter, cancel_event):
        try:
            reporter.set_phases(_listing_compare_phase_plan())
            reporter.phase("local")
            try:
                if snapshot is not None:
                    local = _snapshot_from_payload(snapshot)
                    mtime = os.path.getmtime(csv_path) if os.path.exists(csv_path) else None
                    exists = os.path.exists(csv_path)
                else:
                    local, mtime, exists = _load_local_or_empty(csv_path)
            except HTTPException:
                local, mtime, exists = _load_local_or_empty(csv_path)
            _merge_local_screenshots(local, screenshots_dir)
            reporter.progress(1, 1, msg="ok")
            if cancel_event.is_set():
                raise ProcessCanceled("listing compare canceled")

            remote_ok = True
            error = ""
            asc: ListingSnapshot | None = None
            try:
                reporter.phase("text")
                api, app_id = _api_for_profile(profile)
                asc = load_asc_text_snapshot(api, app_id)
                reporter.progress(1, 1, msg="ok")
                if cancel_event.is_set():
                    raise ProcessCanceled("listing compare canceled")
                reporter.phase("shots")
                attach_asc_screenshots(api, asc)
                reporter.progress(1, 1, msg="ok")
            except ProcessCanceled:
                raise
            except (NoEditableVersionError, NoAppInfoError, Exception) as exc:  # noqa: BLE001
                remote_ok = False
                error = str(exc)
                reporter.phase("text")
                reporter.progress(1, 1, msg="error")
                reporter.phase("shots")
                reporter.progress(1, 1, msg="error")

            if cancel_event.is_set():
                raise ProcessCanceled("listing compare canceled")

            reporter.phase("done")
            payload = _finalize_listing_compare(
                local,
                asc,
                mtime=mtime,
                exists=exists,
                remote_ok=remote_ok,
                error=error,
            )
            reporter.progress(1, 1, msg="ok")
            reporter.done("核对完成")
            return payload
        except ProcessCanceled:
            reporter.log("⏹ 用户已终止商店核对")
            raise

    return start_background_task(
        task_store,
        kind="listing-compare",
        profile=profile,
        verbose=False,
        run=run,
        task_id=task_id,
    )


@router.post("/compare")
async def listing_compare(request: Request):
    """Start a background local-vs-ASC compare; result lives on the task."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    csv_path = body.get("csv_path") or body.get("csvPath") or ""
    if not isinstance(csv_path, str) or not csv_path.strip():
        raise HTTPException(status_code=400, detail="csv_path is required")
    screenshots_dir = body.get("screenshots_dir") or body.get("screenshotsDir") or ""
    if not isinstance(screenshots_dir, str):
        screenshots_dir = ""
    snapshot_in = body.get("snapshot")
    snapshot = snapshot_in if isinstance(snapshot_in, dict) else None

    def _start():
        return _start_listing_compare_task(
            profile=profile,
            csv_path=csv_path.strip(),
            screenshots_dir=screenshots_dir.strip(),
            snapshot=snapshot,
        )

    task_id = await asyncio.to_thread(_start)
    return {"task_id": task_id}


def _listing_translate_impl(profile: str, lang: str, body: dict) -> dict | JSONResponse:
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
    if mode not in {"translate", "rewrite", "keywords"}:
        raise HTTPException(status_code=400, detail="mode must be translate, rewrite, or keywords")
    fields = body.get("fields")
    if not isinstance(fields, list) or not fields:
        raise HTTPException(status_code=400, detail="fields is required")
    translator = make_listing_translator(config)
    translations: list[dict] = []
    errors: list[str] = []
    for row in fields:
        if not isinstance(row, dict):
            continue
        locale = str(row.get("locale") or "").strip()
        if not locale:
            continue
        payload = {name: str(row.get(name) or "") for name in TEXT_FIELDS}
        try:
            translations.append(
                translator.translate_fields(
                    source_locale=source_locale,
                    target_locale=locale,
                    fields=payload,
                    mode=mode,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{locale}: {exc}")
            fallback = {"locale": locale, **payload}
            translations.append(fallback)
    return {"ok": True, "translations": translations, "errors": errors}


@router.post("/translate")
async def listing_translate(request: Request):
    """Translate/rewrite listing copy in-request (thread pool, no task bar)."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    return await asyncio.to_thread(_listing_translate_impl, profile, lang, body)


def _fetch_asc_screenshot_bytes(
    profile: str, screenshot_id: str, *, thumb: bool
) -> tuple[bytes, str]:
    """Blocking ASC metadata + CDN download. Raises HTTPException on missing asset."""
    api, _app_id = _api_for_profile(profile)
    detail = api.get(f"/v1/appScreenshots/{screenshot_id}")
    attrs = ((detail or {}).get("data") or {}).get("attributes") or {}
    if thumb:
        url = screenshot_thumb_url(attrs)
        if not url:
            raise HTTPException(status_code=404, detail="thumb URL not available")
        timeout = (10, 60)
    else:
        asset = (attrs or {}).get("imageAsset") or {}
        template = asset.get("templateUrl") or ""
        if not template:
            raise HTTPException(status_code=404, detail="image URL not available")
        width = asset.get("width") or 0
        height = asset.get("height") or 0
        if width and height:
            url = template.replace("{w}", str(width)).replace("{h}", str(height))
        else:
            url = template.replace("{w}", "2000").replace("{h}", "2000")
        if "{f}" in url:
            file_name = str(attrs.get("fileName") or "")
            suffix = Path(file_name).suffix.lower().lstrip(".")
            if suffix == "jpeg":
                suffix = "jpg"
            url = url.replace("{f}", suffix if suffix in ("png", "jpg") else "png")
        timeout = (10, 120)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type") or "image/png"
    return resp.content, content_type


@router.get("/asc-thumb")
def listing_asc_thumb(request: Request, screenshot_id: str):
    """Proxy a small ASC screenshot preview by `screenshot_id`.

    Resolves `imageAsset.templateUrl` (100×100) from the screenshot resource and
    streams the CDN bytes so the browser does not need cross-origin CDN access.

    Sync ``def`` so ASC + CDN ``requests.get`` stay off the event loop.
    """
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)
    sid = (screenshot_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="screenshot_id is required")

    try:
        content, content_type = _fetch_asc_screenshot_bytes(profile, sid, thumb=True)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    return Response(content=content, media_type=content_type)


@router.get("/asc-image")
def listing_asc_image(request: Request, screenshot_id: str):
    """Proxy the full ASC screenshot image by `screenshot_id` for lightbox viewing.

    Sync ``def`` so ASC + CDN ``requests.get`` stay off the event loop.
    """
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)
    sid = (screenshot_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="screenshot_id is required")

    try:
        content, content_type = _fetch_asc_screenshot_bytes(profile, sid, thumb=False)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    return Response(content=content, media_type=content_type)


@router.post("/pull/screenshots")
async def listing_pull_screenshots(request: Request):
    """Start a background task that downloads ASC screenshots over local scopes."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")

    screenshots_dir = body.get("screenshots_dir")
    if not isinstance(screenshots_dir, str) or not screenshots_dir.strip():
        raise HTTPException(status_code=400, detail="screenshots_dir is required")

    scopes_raw = body.get("scopes")
    if not isinstance(scopes_raw, list) or not scopes_raw:
        raise HTTPException(status_code=400, detail="scopes must be a non-empty list")

    scopes: list[dict] = []
    for item in scopes_raw:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="invalid scope entry")
        locale = item.get("locale")
        display_type = item.get("display_type")
        if not isinstance(locale, str) or not locale.strip():
            raise HTTPException(status_code=400, detail="invalid scope entry")
        if not isinstance(display_type, str) or not display_type.strip():
            raise HTTPException(status_code=400, detail="invalid scope entry")
        scopes.append({"locale": locale.strip(), "display_type": display_type.strip()})

    if not scopes:
        raise HTTPException(status_code=400, detail="no valid scopes")

    task_id = await asyncio.to_thread(
        _start_listing_pull_screenshots_task,
        profile,
        screenshots_dir.strip(),
        scopes,
    )
    return {"ok": True, "task_id": task_id}


def _start_listing_pull_screenshots_task(
    profile: str,
    screenshots_dir: str,
    scopes: list[dict],
) -> str:
    """Create and enqueue a blocking ASC screenshot download task."""
    task_id = task_store.create(
        "listing-pull-screenshots",
        profile=profile,
        replay=sanitize_replay(
            "listing-pull-screenshots",
            profile,
            False,
            {
                "screenshots_dir": screenshots_dir,
                "scopes": scopes,
            },
        ),
    )

    def run(reporter, cancel_event):
        try:
            api, app_id = _api_for_profile(profile)
            if cancel_event.is_set():
                raise ProcessCanceled("screenshot pull canceled")
            download_asc_screenshots(
                api,
                app_id,
                screenshots_dir,
                scopes,
                reporter=reporter,
            )
            if cancel_event.is_set():
                raise ProcessCanceled("screenshot pull canceled")
            reporter.done("截图拉取完成")
            return {"success": True}
        except ProcessCanceled:
            raise
        except Exception as e:
            reporter.fail(str(e))
            raise

    start_background_task(
        task_store,
        kind="listing-pull-screenshots",
        profile=profile,
        verbose=False,
        run=run,
        task_id=task_id,
    )
    return task_id


def _do_listing_pull_text(
    profile: str,
    csv_path: str,
    expected_mtime: float | int | None,
    parsed: list[tuple[str, list[str]]] | None,
    lang: str,
    *,
    write: bool,
    screenshots_dir: str = "",
):
    """Blocking ASC snapshot + optional CSV write (runs in a worker thread)."""
    try:
        local, mtime, exists = _load_local_or_empty(csv_path)
    except (OSError, ValueError) as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    try:
        api, app_id = _api_for_profile(profile)
        asc = load_asc_text_snapshot(api, app_id)
    except (NoEditableVersionError, NoAppInfoError) as e:
        return _asc_error_response(e, lang)
    except Exception as e:
        return JSONResponse(
            {"ok": False, "error": str(e), "message": str(e)},
            status_code=400,
        )

    local_map = {loc.locale: loc for loc in local.locales}
    asc_map = {loc.locale: loc for loc in asc.locales}
    if not parsed:
        parsed = [(loc.locale, list(FIELD_NAMES)) for loc in asc.locales]

    for locale, fields in parsed:
        asc_loc = asc_map.get(locale)
        if asc_loc is None:
            continue
        if locale not in local_map:
            local_map[locale] = LocaleListing(
                locale=locale,
                fields={name: "" for name in FIELD_NAMES},
                screenshots={},
            )
            local.locales.append(local_map[locale])
        for name in fields:
            local_map[locale].fields[name] = asc_loc.fields.get(name, "")

    written = False
    if write:
        try:
            mtime = save_local_csv(
                csv_path,
                list(local_map.values()),
                expected_mtime=expected_mtime,
            )
            written = True
            exists = True
        except FileChangedError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=409)
        except OSError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    _merge_local_screenshots(local, screenshots_dir)
    return {
        "ok": True,
        "csvPath": csv_path,
        "mtime": mtime,
        "exists": exists,
        "written": written,
        "snapshot": _snapshot_to_dict(local),
        "version": asc.version,
    }


@router.post("/pull/text")
async def listing_pull_text(request: Request):
    """Pull ASC text into CSV (`write: true`) or a memory snapshot (`write: false`)."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")

    csv_path = body.get("csv_path")
    if not isinstance(csv_path, str) or not csv_path.strip():
        raise HTTPException(status_code=400, detail="csv_path is required")

    expected_mtime = body.get("expected_mtime")
    if expected_mtime is not None and not isinstance(expected_mtime, (int, float)):
        raise HTTPException(status_code=400, detail="expected_mtime must be a number")

    screenshots_dir = body.get("screenshots_dir") or body.get("screenshotsDir") or ""
    if screenshots_dir is None:
        screenshots_dir = ""
    if not isinstance(screenshots_dir, str):
        raise HTTPException(status_code=400, detail="screenshots_dir must be a string")

    if "write" in body:
        write = _as_bool(body.get("write"))
    else:
        write = True

    selections = body.get("selections")
    parsed: list[tuple[str, list[str]]] | None = None
    if selections is None or selections == []:
        if write:
            raise HTTPException(status_code=400, detail="selections must be a non-empty list")
        parsed = None
    else:
        if not isinstance(selections, list):
            raise HTTPException(status_code=400, detail="selections must be a list")
        parsed = []
        for item in selections:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail="invalid selection entry")
            locale = item.get("locale")
            fields = item.get("fields")
            if not isinstance(locale, str) or not locale.strip():
                raise HTTPException(status_code=400, detail="invalid selection entry")
            if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
                raise HTTPException(status_code=400, detail="invalid selection entry")
            allowed = [f for f in fields if f in FIELD_NAMES]
            if allowed:
                parsed.append((locale, allowed))
        if write and not parsed:
            raise HTTPException(status_code=400, detail="no valid field selections")

    return await asyncio.to_thread(
        _do_listing_pull_text,
        profile,
        csv_path,
        expected_mtime,
        parsed,
        lang,
        write=write,
        screenshots_dir=screenshots_dir.strip(),
    )


def _screenshot_item_to_dict(root: str, file_path: Path, order: int) -> dict:
    from asc.listing.local import _thumb_url  # local import: private helper reused for responses

    return {
        "file_name": file_path.name,
        "order": order,
        "thumb_url": _thumb_url(root, file_path),
        "local_path": str(file_path),
        "remote_id": "",
    }


@router.post("/screenshots/reorder")
async def listing_screenshots_reorder(request: Request):
    """Reorder screenshots of one `(locale, display_type)` group, writing to disk immediately."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")

    root = body.get("root")
    locale = body.get("locale")
    display_type = body.get("display_type")
    file_names = body.get("file_names")
    if not isinstance(root, str) or not root.strip():
        raise HTTPException(status_code=400, detail="root is required")
    if not isinstance(locale, str) or not locale.strip():
        raise HTTPException(status_code=400, detail="locale is required")
    if not isinstance(display_type, str) or not display_type.strip():
        raise HTTPException(status_code=400, detail="display_type is required")
    if not isinstance(file_names, list) or not all(isinstance(n, str) for n in file_names):
        raise HTTPException(status_code=400, detail="file_names must be a list of strings")

    locale_dir = find_locale_screenshot_dir(root, locale)
    if locale_dir is None:
        raise HTTPException(status_code=404, detail="locale folder not found under root")

    try:
        apply_screenshot_order(locale_dir, display_type, file_names, root=root)
    except PathTraversalError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Full-folder renumber may rename sibling displayTypes too — return every
    # group for this locale so the UI can refresh stale file_name/path/thumb URLs.
    by_type = scan_local_screenshots(root).get(locale, {})
    groups = {
        dtype: [
            _screenshot_item_to_dict(root, Path(item.local_path), item.order) for item in items
        ]
        for dtype, items in by_type.items()
    }
    return {
        "ok": True,
        "groups": groups,
        # Kept for callers that only care about the reordered type.
        "items": groups.get(display_type, []),
    }


@router.post("/screenshots/replace")
async def listing_screenshots_replace(
    request: Request,
    root: str = Form(...),
    path: str = Form(...),
    new_name: str = Form(""),
    file: UploadFile = File(...),
):
    """Replace a single screenshot's bytes in place (optionally renaming it)."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)

    target = _resolve_under_root(root, path)
    data = await file.read()
    try:
        new_path = replace_screenshot(target, data, new_name.strip() or None, root=root)
    except PathTraversalError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return {
        "ok": True,
        "path": str(new_path),
        "file_name": new_path.name,
        "thumb_url": _screenshot_item_to_dict(root, new_path, 0)["thumb_url"],
    }


@router.post("/screenshots/delete")
async def listing_screenshots_delete(request: Request):
    """Delete a single screenshot file, writing to disk immediately."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")

    root = body.get("root")
    path = body.get("path")
    if not isinstance(root, str) or not isinstance(path, str):
        raise HTTPException(status_code=400, detail="root and path are required")

    target = _resolve_under_root(root, path)
    delete_screenshot(target)
    return {"ok": True}


@router.post("/screenshots/add")
async def listing_screenshots_add(
    request: Request,
    root: str = Form(...),
    locale: str = Form(...),
    display_type: str = Form(""),
    filename: str = Form(""),
    file: UploadFile = File(...),
):
    """Add a new screenshot to a locale folder (created under `root` if it doesn't exist yet)."""
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)

    try:
        safe_locale = _safe_locale_name(locale)
    except PathTraversalError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    root_path = Path(root).resolve()
    locale_dir = find_locale_screenshot_dir(root, safe_locale) or (root_path / safe_locale)
    data = await file.read()
    target_name = filename.strip() or file.filename or "screenshot.png"
    try:
        new_path = add_screenshot(locale_dir, display_type, target_name, data, root=root_path)
    except PathTraversalError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return {
        "ok": True,
        "path": str(new_path),
        "file_name": new_path.name,
        "thumb_url": _screenshot_item_to_dict(root, new_path, 0)["thumb_url"],
    }
