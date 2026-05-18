"""API routes for asc Web UI (/api/*)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

router = APIRouter()

_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_HOME = Path.home().resolve()
_TMPDIR = Path(tempfile.gettempdir()).resolve()
_ALLOWED_ROOTS = (_HOME, _TMPDIR)


def _is_under_allowed_root(target: Path) -> bool:
    """Return True if target is at or under any allowed root."""
    for root in _ALLOWED_ROOTS:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


@router.get("/switch-profile")
async def switch_profile(profile: str):
    """Switch active app profile (stores in session cookie)."""
    resp = JSONResponse({"ok": True, "profile": profile})
    resp.set_cookie("asc_profile", profile, httponly=True, samesite="lax")
    return resp


@router.get("/browse", response_class=HTMLResponse)
async def browse(request: Request, path: str = ".", mode: str = "dir", ext: str = ""):
    """Return an HTML fragment listing files/dirs at `path` for the file browser modal."""
    target = Path(path).expanduser().resolve()
    if not _is_under_allowed_root(target):
        return Response("Forbidden", status_code=403)

    if not target.exists():
        target = _HOME

    entries = []
    if target != _HOME and target.parent != target:
        entries.append({"name": "..", "path": str(target.parent), "is_dir": True})

    try:
        items = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        items = []

    for item in items:
        if item.name.startswith("."):
            continue
        if mode == "file" and not item.is_dir():
            if ext and item.suffix != ext:
                continue
        entries.append({"name": item.name, "path": str(item), "is_dir": item.is_dir()})

    return _templates.TemplateResponse(request, "filebrowser.html", {
        "current_path": str(target),
        "entries": entries,
        "mode": mode,
        "ext": ext,
    })
