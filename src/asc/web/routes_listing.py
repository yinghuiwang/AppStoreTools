"""Local listing (CSV text + screenshots) routes for asc Web UI (/api/listing/*)."""
from __future__ import annotations

import mimetypes
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from asc.config import Config
from asc.guard import GuardViolationError, enforce_config_guard
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
from asc.listing.models import LocaleListing
from asc.web.i18n import t

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


def _snapshot_to_dict(snapshot) -> dict:
    return asdict(snapshot)


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
        snapshot = load_local_text_snapshot(csv_path)
    except (FileNotFoundError, OSError) as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    if screenshots_dir.strip():
        by_locale = scan_local_screenshots(screenshots_dir)
        for loc in snapshot.locales:
            if loc.locale in by_locale:
                loc.screenshots = by_locale[loc.locale]

    mtime = os.path.getmtime(csv_path) if os.path.exists(csv_path) else None
    return {
        "ok": True,
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

    return {"ok": True, "mtime": new_mtime}


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

    apply_screenshot_order(locale_dir, display_type, file_names)

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
