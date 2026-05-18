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
        api, app_id = make_api_from_config(config)
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
        done_flag = _threading.Event()

        def _drain_loop():
            while not done_flag.is_set():
                while not q.empty():
                    _task_store.append_log(task_id, q.get_nowait())
                done_flag.wait(timeout=0.05)
            while not q.empty():
                _task_store.append_log(task_id, q.get_nowait())

        _threading.Thread(target=_drain_loop, daemon=True).start()

        try:
            config = Config(app_name=profile)
            api, app_id = make_api_from_config(config)

            with capture_stdout_to_queue(q):
                if include_metadata:
                    from asc.commands.metadata import _upload_metadata_core
                    metadata_list = parse_csv(csv_path)
                    _upload_metadata_core(api, app_id, metadata_list, dry_run=dry_run)
                if include_screenshots:
                    from asc.commands.screenshots import _upload_screenshots_core
                    _upload_screenshots_core(api, app_id, screenshots_dir, dry_run=dry_run)

            done_flag.set()
            _task_store.set_status(task_id, _TaskStatus.DONE)
            _task_store.set_result(task_id, {"success": True})
        except Exception as e:
            done_flag.set()
            _task_store.append_log(task_id, f"❌ 错误：{e}")
            _task_store.set_status(task_id, _TaskStatus.ERROR)
            _task_store.set_result(task_id, {"success": False, "error": str(e)})

    _threading.Thread(target=_run, daemon=True).start()
    return task_id


@router.post("/metadata/check")
async def metadata_check(request: Request):
    profile = request.cookies.get("asc_profile", "")
    result = _run_metadata_check(profile)
    return result


@router.post("/metadata/run")
async def metadata_run(
    request: Request,
    csv_path: str = _Form("data/appstore_info.csv"),
    screenshots_dir: str = _Form("data/screenshots"),
    include_metadata: str = _Form(""),
    include_screenshots: str = _Form(""),
    dry_run: str = _Form(""),
):
    profile = request.cookies.get("asc_profile", "")
    task_id = _start_metadata_task(
        profile=profile,
        csv_path=csv_path,
        screenshots_dir=screenshots_dir,
        include_metadata=bool(include_metadata),
        include_screenshots=bool(include_screenshots),
        dry_run=bool(dry_run),
    )
    return {"task_id": task_id}


def _start_build_task(
    profile: str,
    mode: str,
    project: str,
    scheme: str,
    destination: str,
    ipa_path: str,
    verbose: bool,
) -> str:
    task_id = _task_store.create("build")

    def _run():
        import queue
        from asc.web.sse import capture_stdout_to_queue
        from asc.config import Config

        _task_store.set_status(task_id, _TaskStatus.RUNNING)
        q: queue.Queue = queue.Queue()
        done_flag = _threading.Event()

        def _drain_loop():
            while not done_flag.is_set():
                while not q.empty():
                    _task_store.append_log(task_id, q.get_nowait())
                done_flag.wait(timeout=0.05)
            while not q.empty():
                _task_store.append_log(task_id, q.get_nowait())

        _threading.Thread(target=_drain_loop, daemon=True).start()

        try:
            config = Config(app_name=profile)

            with capture_stdout_to_queue(q):
                if mode in ("full", "build"):
                    from asc.commands.build_inputs import (
                        BuildInputsCLI, prepare_build_inputs
                    )
                    from asc.commands.build import build_core
                    cli = BuildInputsCLI(
                        project=project or None,
                        scheme=scheme or None,
                        destination=destination or None,
                    )
                    resolved = prepare_build_inputs(cli, config, interactive=False)
                    ipa = build_core(resolved, config.build_output, verbose=verbose)
                    if mode == "full" and ipa:
                        from asc.commands.build import deploy_core
                        deploy_core(
                            ipa_path=ipa,
                            issuer_id=config.issuer_id,
                            key_id=config.key_id,
                            key_file=config.key_file,
                            destination=destination or "appstore",
                            dry_run=False,
                            verbose=verbose,
                        )
                elif mode == "deploy":
                    from asc.commands.build import deploy_core
                    deploy_core(
                        ipa_path=ipa_path,
                        issuer_id=config.issuer_id,
                        key_id=config.key_id,
                        key_file=config.key_file,
                        destination=destination or "appstore",
                        dry_run=False,
                        verbose=verbose,
                    )

            done_flag.set()
            _task_store.set_status(task_id, _TaskStatus.DONE)
            _task_store.set_result(task_id, {"success": True})
        except Exception as e:
            done_flag.set()
            _task_store.append_log(task_id, f"❌ 错误：{e}")
            _task_store.set_status(task_id, _TaskStatus.ERROR)
            _task_store.set_result(task_id, {"success": False, "error": str(e)})

    _threading.Thread(target=_run, daemon=True).start()
    return task_id


@router.post("/build/run")
async def build_run(
    request: Request,
    mode: str = _Form("full"),
    project: str = _Form(""),
    scheme: str = _Form(""),
    destination: str = _Form("testflight"),
    ipa_path: str = _Form(""),
    verbose: str = _Form(""),
):
    profile = request.cookies.get("asc_profile", "")
    task_id = _start_build_task(
        profile=profile,
        mode=mode,
        project=project,
        scheme=scheme,
        destination=destination,
        ipa_path=ipa_path,
        verbose=bool(verbose),
    )
    return {"task_id": task_id}


@router.get("/build/schemes")
async def build_schemes(project: str = "."):
    """Return list of schemes for a given project path."""
    try:
        from asc.commands.build_inputs import detect_project, list_schemes
        project_path, kind = detect_project(project)
        schemes = list_schemes(project_path, kind)
        return {"schemes": schemes}
    except Exception as e:
        return {"schemes": [], "error": str(e)}


import asyncio as _asyncio
from fastapi.responses import StreamingResponse as _StreamingResponse
from asc.web.sse import format_sse_event as _fmt_sse


@router.get("/task/{task_id}/stream")
async def task_stream(task_id: str):
    """SSE stream: replay existing logs then push new ones until task completes."""
    task = _task_store.get(task_id)
    if task is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Task not found")

    async def _generate():
        sent = 0
        max_polls = 1500  # 300 seconds at 0.2s intervals
        polls = 0
        while polls < max_polls:
            current = _task_store.get(task_id)
            if current is None:
                yield _fmt_sse("error_event", "task not found")
                break
            logs = current["logs"]
            while sent < len(logs):
                yield _fmt_sse("log", logs[sent])
                sent += 1
            status = current["status"]
            if status == _TaskStatus.DONE:
                yield _fmt_sse("done", "")
                break
            elif status == _TaskStatus.ERROR:
                yield _fmt_sse("error_event", "")
                break
            polls += 1
            await _asyncio.sleep(0.2)
        else:
            yield _fmt_sse("error_event", "timeout")

    return _StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/task/{task_id}/status")
async def task_status(task_id: str):
    """Return current task status and result as JSON."""
    task = _task_store.get(task_id)
    if task is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task_id,
        "status": task["status"],
        "result": task["result"],
        "log_count": len(task["logs"]),
    }


import shutil as _shutil
from fastapi import UploadFile as _UploadFile, File as _File


@router.get("/profiles")
async def list_profiles_api():
    from asc.config import Config
    config = Config()
    apps = config.list_apps()
    default = config.app_name or (apps[0] if apps else "")
    return {"profiles": apps, "default": default}


@router.post("/profiles")
async def create_profile(
    name: str = _Form(...),
    issuer_id: str = _Form(...),
    key_id: str = _Form(...),
    app_id: str = _Form(...),
    csv: str = _Form("data/appstore_info.csv"),
    screenshots: str = _Form("data/screenshots"),
    key_file: _UploadFile = _File(...),
):
    import os
    import re
    from fastapi import HTTPException

    # Fix 2: Validate profile name
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise HTTPException(status_code=400, detail="Invalid profile name")

    # Fix 1: Sanitize key filename (path traversal protection)
    safe_filename = os.path.basename(key_file.filename)
    if not safe_filename or safe_filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid key filename")

    global_keys_dir = Path.home() / ".config" / "asc" / "keys"
    global_keys_dir.mkdir(parents=True, exist_ok=True)
    dest_key = global_keys_dir / safe_filename

    content = await key_file.read()
    dest_key.write_bytes(content)
    # Fix 3: Set key file permissions
    dest_key.chmod(0o600)

    from asc.config import Config
    config = Config()
    config.save_app_profile(name, issuer_id, key_id, str(dest_key), app_id, csv, screenshots)
    return {"ok": True, "name": name}


@router.put("/profiles/{name}")
async def update_profile(
    name: str,
    issuer_id: str = _Form(...),
    key_id: str = _Form(...),
    app_id: str = _Form(...),
    csv: str = _Form("data/appstore_info.csv"),
    screenshots: str = _Form("data/screenshots"),
    key_file: _UploadFile = _File(None),
):
    import os
    import re
    from fastapi import HTTPException

    # Fix 2: Validate profile name
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise HTTPException(status_code=400, detail="Invalid profile name")

    from asc.config import Config
    config = Config()
    existing = config.get_app_profile(name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    key_file_path = existing["key_file"]
    if key_file and key_file.filename:
        # Fix 1: Sanitize key filename
        safe_filename = os.path.basename(key_file.filename)
        if not safe_filename or safe_filename.startswith("."):
            raise HTTPException(status_code=400, detail="Invalid key filename")

        global_keys_dir = Path.home() / ".config" / "asc" / "keys"
        global_keys_dir.mkdir(parents=True, exist_ok=True)
        dest_key = global_keys_dir / safe_filename
        content = await key_file.read()
        dest_key.write_bytes(content)
        # Fix 3: Set key file permissions
        dest_key.chmod(0o600)
        key_file_path = str(dest_key)

    config.save_app_profile(name, issuer_id, key_id, key_file_path, app_id, csv, screenshots)
    return {"ok": True, "name": name}


@router.delete("/profiles/{name}")
async def delete_profile(name: str):
    import re
    from fastapi import HTTPException

    # Fix 2: Validate profile name
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise HTTPException(status_code=400, detail="Invalid profile name")

    from asc.config import Config
    config = Config()
    config.remove_app_profile(name)
    return {"ok": True}


@router.post("/profiles/{name}/set-default")
async def set_default_profile(name: str):
    import re
    from fastapi import HTTPException

    # Fix 2: Validate profile name
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise HTTPException(status_code=400, detail="Invalid profile name")

    local_dir = Path.cwd() / ".asc"
    local_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = local_dir / "config.toml"
    content = cfg_path.read_text() if cfg_path.exists() else ""
    if "default_app" in content:
        content = re.sub(r'default_app\s*=\s*"[^"]*"', f'default_app = "{name}"', content)
    else:
        # Fix 4: TOML injection protection (double-quote escaping)
        safe_name = name.replace('"', '\\"')
        content = f'default_app = "{safe_name}"\n' + content
    cfg_path.write_text(content)
    return {"ok": True}


@router.get("/profiles/{name}")
async def get_profile(name: str):
    import re
    from fastapi import HTTPException

    # Fix 2: Validate profile name
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise HTTPException(status_code=400, detail="Invalid profile name")

    from asc.config import Config
    config = Config()
    data = config.get_app_profile(name)
    if data is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    data["key_file_name"] = Path(data["key_file"]).name if data.get("key_file") else ""
    data.pop("key_file", None)
    return data


@router.get("/guard/status")
async def guard_status(request: Request):
    from asc.guard import Guard
    try:
        guard = Guard()
        data = guard.get_status()
        # Truncate machine fingerprints to first 8 chars
        for fp, info in list(data.get("bindings", {}).get("machine", {}).items()):
            if len(fp) > 8:
                truncated = fp[:8] + "..."
                data["bindings"]["machine"][truncated] = data["bindings"]["machine"].pop(fp)
        # Add current_profile from cookie
        profile = request.cookies.get("asc_profile", "")
        data["current_profile"] = profile
        return data
    except Exception as e:
        return {"enabled": False, "bindings": {"machine": {}, "ip": {}, "credential": {}}, "current_profile": "", "error": str(e)}


@router.post("/settings/lang")
async def set_lang(lang: str = _Form("zh")):
    import os
    if lang not in ("zh", "en"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid language")
    os.environ["ASC_LANG"] = lang
    return {"ok": True, "lang": lang}
