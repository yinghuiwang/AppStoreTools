"""Local listing (CSV text) routes for asc Web UI (/api/listing/*)."""
from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from asc.config import Config
from asc.guard import GuardViolationError, enforce_config_guard
from asc.listing.local import FileChangedError, load_local_text_snapshot, save_local_csv
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


@router.get("/local")
async def listing_local(
    request: Request,
    csv_path: str,
    screenshots_dir: str = "",
):
    """Read a local CSV into a text-only `ListingSnapshot`.

    `screenshots` is left empty on every locale for now; screenshot scanning
    is wired up in a later task.
    """
    lang = _lang(request)
    profile = _require_profile(request)
    if not profile:
        return JSONResponse(_no_profile_payload(lang), status_code=400)

    try:
        snapshot = load_local_text_snapshot(csv_path)
    except (FileNotFoundError, OSError) as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    mtime = os.path.getmtime(csv_path) if os.path.exists(csv_path) else None
    return {
        "ok": True,
        "mtime": mtime,
        "snapshot": _snapshot_to_dict(snapshot),
    }


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
