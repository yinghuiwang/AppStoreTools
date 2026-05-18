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


import threading as _threading
from fastapi import Form as _Form
from asc.web.tasks import task_store as _task_store, TaskStatus as _TaskStatus


def _run_metadata_check(profile: str) -> dict:
    """Run connectivity check for the given profile and return result dict."""
    from asc.config import Config
    from asc.utils import make_api_from_config
    try:
        config = Config(app_name=profile)
        api = make_api_from_config(config)
        app_id = config.app_id
        if not app_id:
            return {"ok": False, "message": "未配置 App ID"}
        version = api.get_editable_version(app_id)
        if not version:
            return {"ok": False, "message": "无可编辑版本，请在 App Store Connect 创建版本"}
        vs = version["attributes"].get("versionString", "?")
        return {"ok": True, "message": f"环境正常，版本 {vs} 可编辑"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def _start_metadata_task(
    profile: str,
    csv_path: str,
    screenshots_dir: str,
    include_metadata: bool,
    include_screenshots: bool,
    dry_run: bool,
) -> str:
    task_id = _task_store.create("metadata")

    def _run():
        import queue
        from asc.web.sse import capture_stdout_to_queue
        from asc.config import Config
        from asc.utils import make_api_from_config, parse_csv

        _task_store.set_status(task_id, _TaskStatus.RUNNING)
        q: queue.Queue = queue.Queue()

        try:
            config = Config(app_name=profile)
            api = make_api_from_config(config)
            app_id = config.app_id

            with capture_stdout_to_queue(q):
                if include_metadata:
                    from asc.commands.metadata import _upload_metadata_core
                    metadata_list = parse_csv(csv_path)
                    _upload_metadata_core(api, app_id, metadata_list, dry_run=dry_run)
                if include_screenshots:
                    from asc.commands.screenshots import _upload_screenshots_core
                    _upload_screenshots_core(api, app_id, screenshots_dir, dry_run=dry_run)

            while not q.empty():
                _task_store.append_log(task_id, q.get_nowait())

            _task_store.set_status(task_id, _TaskStatus.DONE)
            _task_store.set_result(task_id, {"success": True})
        except Exception as e:
            while not q.empty():
                _task_store.append_log(task_id, q.get_nowait())
            _task_store.append_log(task_id, f"❌ 错误：{e}")
            _task_store.set_status(task_id, _TaskStatus.ERROR)
            _task_store.set_result(task_id, {"success": False, "error": str(e)})

    _threading.Thread(target=_run, daemon=True).start()
    return task_id


@router.post("/metadata/check")
async def metadata_check(profile: str = _Form(...)):
    result = _run_metadata_check(profile)
    return result


@router.post("/metadata/run")
async def metadata_run(
    profile: str = _Form(...),
    csv_path: str = _Form("data/appstore_info.csv"),
    screenshots_dir: str = _Form("data/screenshots"),
    include_metadata: str = _Form(""),
    include_screenshots: str = _Form(""),
    dry_run: str = _Form(""),
):
    task_id = _start_metadata_task(
        profile=profile,
        csv_path=csv_path,
        screenshots_dir=screenshots_dir,
        include_metadata=bool(include_metadata),
        include_screenshots=bool(include_screenshots),
        dry_run=bool(dry_run),
    )
    return {"task_id": task_id}
