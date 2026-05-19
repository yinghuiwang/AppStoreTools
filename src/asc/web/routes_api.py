"""API routes for asc Web UI (/api/*)."""
from __future__ import annotations

import copy
import json
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from asc.commands.iap import _upload_iap_core, _load_iap_config
from asc.commands.subscriptions import _upload_subscriptions_core
from asc.config import Config

router = APIRouter()

_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_HOME = Path.home().resolve()
_TMPDIR = Path(tempfile.gettempdir()).resolve()
_ALLOWED_ROOTS = (_HOME, _TMPDIR)
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"

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
    """Run connectivity check for the given profile and return structured result."""
    from asc.config import Config
    from asc.utils import make_api_from_config
    try:
        config = Config(app_name=profile)
        api, app_id = make_api_from_config(config)
        version = api.get_editable_version(app_id)
        if not version:
            return {
                "ok": False,
                "level": "warning",
                "message": "无可编辑版本，请在 App Store Connect 创建版本",
                "detail": {},
            }
        vs = version["attributes"].get("versionString", "?")
        state = version["attributes"].get("appStoreState") or version["attributes"].get("appVersionState", "?")
        # Determine level based on state
        editable_states = {
            "PREPARE_FOR_SUBMISSION",
            "DEVELOPER_REJECTED",
            "REJECTED",
        }
        if state in editable_states:
            level = "success"
            message = f"环境正常，版本 {vs} 可编辑"
        else:
            level = "warning"
            message = f"版本 {vs} 存在但状态为 {state}，不可编辑"
        return {
            "ok": level == "success",
            "level": level,
            "message": message,
            "detail": {
                "version": vs,
                "state": state,
                "app_name": profile,
            },
        }
    except Exception as e:
        return {
            "ok": False,
            "level": "error",
            "message": str(e),
            "detail": {},
        }


def _start_metadata_task(
    profile: str,
    csv_path: str,
    screenshots_dir: str,
    include_metadata: bool,
    include_screenshots: bool,
    dry_run: bool,
) -> str:
    task_id = _task_store.create("metadata", profile=profile)

    def _run():
        import queue
        from asc.web.sse import capture_stdout_to_queue
        from asc.config import Config
        from asc.utils import make_api_from_config, parse_csv

        _task_store.set_status(task_id, _TaskStatus.RUNNING)
        q: queue.Queue = queue.Queue()
        done_flag = _threading.Event()

        _PROGRESS_RE = re.compile(r"\[PROGRESS:(\d+):(.+)\]")

        def _drain_loop():
            while not done_flag.is_set():
                while not q.empty():
                    line = q.get_nowait()
                    m = _PROGRESS_RE.match(line)
                    if m:
                        _task_store.set_progress(task_id, int(m.group(1)), m.group(2))
                    else:
                        _task_store.append_log(task_id, line)
                done_flag.wait(timeout=0.05)
            while not q.empty():
                line = q.get_nowait()
                m = _PROGRESS_RE.match(line)
                if m:
                    _task_store.set_progress(task_id, int(m.group(1)), m.group(2))
                else:
                    _task_store.append_log(task_id, line)

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
    signing: str = "auto",
) -> str:
    task_id = _task_store.create("build", profile=profile)

    def _run():
        import queue
        from asc.web.sse import capture_stdout_to_queue
        from asc.config import Config

        _task_store.set_status(task_id, _TaskStatus.RUNNING)
        q: queue.Queue = queue.Queue()
        done_flag = _threading.Event()

        _PROGRESS_RE = re.compile(r"\[PROGRESS:(\d+):(.+)\]")

        def _drain_loop():
            while not done_flag.is_set():
                while not q.empty():
                    line = q.get_nowait()
                    m = _PROGRESS_RE.match(line)
                    if m:
                        _task_store.set_progress(task_id, int(m.group(1)), m.group(2))
                    else:
                        _task_store.append_log(task_id, line)
                done_flag.wait(timeout=0.05)
            while not q.empty():
                line = q.get_nowait()
                m = _PROGRESS_RE.match(line)
                if m:
                    _task_store.set_progress(task_id, int(m.group(1)), m.group(2))
                else:
                    _task_store.append_log(task_id, line)

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
                        signing=signing or None,
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
    signing: str = _Form("auto"),
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
        signing=signing,
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
        last_progress = None
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
            # Emit progress event if changed
            progress = current.get("progress")
            if progress and progress != last_progress:
                yield _fmt_sse("progress", json.dumps(progress))
                last_progress = progress
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
        data = copy.deepcopy(guard.get_status())
        # Truncate machine fingerprints to first 8 chars
        for fp, info in list(data.get("bindings", {}).get("machine", {}).items()):
            if len(fp) > 8:
                truncated = fp[:8] + "..."
                data["bindings"]["machine"][truncated] = data["bindings"]["machine"].pop(fp)
        # Add current_profile from cookie
        profile = request.cookies.get("asc_profile", "")
        data["current_profile"] = profile
        # Build app_id → profile_name mapping for display
        from asc.config import Config
        config = Config()
        profiles = config.list_apps()
        app_id_to_profile = {}
        for p in profiles:
            pdata = config.get_app_profile(p)
            if pdata and pdata.get("app_id"):
                app_id_to_profile[pdata["app_id"]] = p
        # Inject profile_name into each binding entry
        for category in ("machine", "ip", "credential"):
            for key, info in data.get("bindings", {}).get(category, {}).items():
                info["profile_name"] = app_id_to_profile.get(info.get("app_id", ""), "")
        return data
    except Exception as e:
        return {"enabled": False, "bindings": {"machine": {}, "ip": {}, "credential": {}}, "current_profile": "", "error": str(e)}


@router.get("/tasks/recent", response_class=HTMLResponse)
async def tasks_recent_html(request: Request):
    """Return HTML fragment of recent tasks for HTMX polling."""
    tasks = _task_store.list_recent(limit=20)
    return _templates.TemplateResponse(request, "task_list.html", {"tasks": tasks})


@router.post("/settings/lang")
async def set_lang(lang: str = _Form("zh")):
    import os
    if lang not in ("zh", "en"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid language")
    os.environ["ASC_LANG"] = lang
    return {"ok": True, "lang": lang}


@router.get("/examples/csv")
async def download_example_csv():
    """Download the example CSV file."""
    csv_path = _DATA_DIR / "appstore_info.csv"
    if not csv_path.exists():
        return Response("Example CSV not found", status_code=404)
    content = csv_path.read_bytes()
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=appstore_info_example.csv"},
    )


@router.get("/examples/screenshots")
async def download_example_screenshots():
    """Download the example screenshots directory as a zip."""
    import io
    import zipfile

    screenshots_dir = _DATA_DIR / "screenshots"
    if not screenshots_dir.exists():
        return Response("Example screenshots not found", status_code=404)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in sorted(screenshots_dir.rglob("*")):
            if fp.is_file():
                arcname = str(fp.relative_to(screenshots_dir))
                zf.write(fp, arcname)
    buf.seek(0)
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=screenshots_example.zip"},
    )


# ---------- IAP helpers & endpoints ----------

def _start_iap_task(
        profile: str,
        iap_file: str,
        dry_run: bool,
        update_existing: bool,
    ) -> str:
    task_id = _task_store.create("iap", profile=profile)

    def _run():
        import queue
        from asc.web.sse import capture_stdout_to_queue
        from asc.config import Config
        from asc.utils import make_api_from_config

        _task_store.set_status(task_id, _TaskStatus.RUNNING)
        q: "queue.Queue" = queue.Queue()
        done_flag = _threading.Event()

        _PROGRESS_RE = re.compile(r"\[PROGRESS:(\d+)\:(.+)\]")

        def _drain_loop():
            while not done_flag.is_set():
                while not q.empty():
                    line = q.get_nowait()
                    m = _PROGRESS_RE.match(line)
                    if m:
                        _task_store.set_progress(task_id, int(m.group(1)), m.group(2))
                    else:
                        _task_store.append_log(task_id, line)
                done_flag.wait(timeout=0.05)
            while not q.empty():
                line = q.get_nowait()
                m = _PROGRESS_RE.match(line)
                if m:
                    _task_store.set_progress(task_id, int(m.group(1)), m.group(2))
                else:
                    _task_store.append_log(task_id, line)

        _threading.Thread(target=_drain_loop, daemon=True).start()

        try:
            config = Config(app_name=profile)
            api, app_id = make_api_from_config(config)

            items, groups = _load_iap_config(iap_file)
            if items:
                _upload_iap_core(api, app_id, items,
                                 dry_run=dry_run,
                                 update_existing=update_existing)
            if groups:
                _upload_subscriptions_core(
                    api, app_id, groups,
                    update_existing=update_existing, dry_run=dry_run
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

@router.post("/iap/run")
async def iap_run(
        request: Request,
        iap_file: str = _Form("data/iap_packages.json"),
        dry_run: str = _Form(""),
        update_existing: str = _Form(""),
):
    profile = request.cookies.get("asc_profile", "")
    task_id = _start_iap_task(
        profile=profile,
        iap_file=iap_file,
        dry_run=bool(dry_run),
        update_existing=bool(update_existing),
    )
    return {"task_id": task_id}


@router.post("/iap/check")
async def iap_check(request: Request):
    profile = request.cookies.get("asc_profile", "")
    try:
        from pathlib import Path
        config = Config(app_name=profile)
        iap_path = Path(config.iap_file) if hasattr(config, "iap_file") and config.iap_file else Path("data/iap_packages.json")
        if not iap_path.exists():
            return {
                "ok": False,
                "level": "error",
                "message": f"IAP 配置文件未找到: {iap_path}",
                "detail": {},
            }
        items, groups = _load_iap_config(str(iap_path))
        total = len(items) + len(groups)
        return {
            "ok": True,
            "level": "success",
            "message": f"配置有效：{len(items)} 个 IAP 项，{len(groups)} 个订阅组",
            "detail": {"items": len(items), "groups": len(groups), "total": total},
        }
    except Exception as e:
        return {"ok": False, "level": "error", "message": str(e), "detail": {}}
