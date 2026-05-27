"""API routes for asc Web UI (/api/*)."""
from __future__ import annotations

import copy
import json
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Query, Request
from asc.utils import make_api_from_config
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from asc.commands.iap import _upload_iap_core, _load_iap_config
from asc.commands.subscriptions import _upload_subscriptions_core
from asc.config import Config
from asc.utils import make_api_from_config

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

    # If target is a file, use its parent directory for browsing
    if target.is_file():
        target = target.parent

    entries = []
    if target != _HOME and target.parent != target:
        entries.append({"name": "..", "path": str(target.parent), "is_dir": True})

    try:
        items = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except (PermissionError, NotADirectoryError, OSError):
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
    certificate: str = "",
    provisioning_profile: str = "",
    dry_run: bool = False,
    reuse_archive: str = "",
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
                        certificate=certificate or None,
                        profile=provisioning_profile or None,
                    )
                    resolved = prepare_build_inputs(cli, config, interactive=False)
                    reuse_value = None
                    if reuse_archive == "reuse":
                        reuse_value = True
                    elif reuse_archive == "rebuild":
                        reuse_value = False
                    ipa = build_core(
                        resolved,
                        config.build_output,
                        dry_run=dry_run,
                        reuse_archive=reuse_value,
                        interactive=False,
                        verbose=verbose,
                    )
                    if mode == "full" and ipa:
                        from asc.commands.build import deploy_core
                        deploy_core(
                            ipa_path=ipa,
                            issuer_id=config.issuer_id,
                            key_id=config.key_id,
                            key_file=config.key_file,
                            destination=destination or "appstore",
                            dry_run=dry_run,
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
                        dry_run=dry_run,
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


def _archive_summary(archive):
    if not archive:
        return None
    return {
        "path": archive.path,
        "bundle_id": archive.bundle_id,
        "marketing_version": archive.marketing_version,
        "build_number": archive.build_number,
        "created": archive.created.strftime("%Y-%m-%d %H:%M"),
    }


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
    certificate: str = _Form(""),
    provisioning_profile: str = _Form(""),
    dry_run: str = _Form(""),
    reuse_archive: str = _Form(""),
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
        certificate=certificate,
        provisioning_profile=provisioning_profile,
        dry_run=bool(dry_run),
        reuse_archive=reuse_archive,
    )
    return {"task_id": task_id}


@router.get("/build/schemes")
def build_schemes(project: str = "."):
    """Return list of schemes for a given project path."""
    try:
        from asc.commands.build_inputs import detect_project, list_schemes
        project_path, kind = detect_project(project)
        schemes = list_schemes(project_path, kind)
        return {"schemes": schemes}
    except Exception as e:
        return {"schemes": [], "error": str(e)}


@router.get("/build/options")
def build_options(
    request: Request,
    project: str = ".",
    scheme: str = "",
    signing: str = "auto",
    certificate: str = "",
):
    """Return selectable build inputs for the Web UI.

    This mirrors the choices that `asc release --interactive` would prompt for
    in a terminal, but keeps the Web UI non-interactive at execution time.
    """
    try:
        from asc.commands.build_inputs import (
            detect_bundle_id,
            detect_certificates,
            detect_project,
            detect_profiles,
            detect_versions,
            find_matching_archive,
            list_schemes,
            scan_archives,
        )

        profile = request.cookies.get("asc_profile", "")
        config = Config(app_name=profile)
        source_project = project or config.build_project or "."
        project_path, kind = detect_project(source_project)
        schemes = list_schemes(project_path, kind)
        selected_scheme = scheme or config.build_scheme or (schemes[0] if len(schemes) == 1 else "")
        scheme_auto = not scheme and not config.build_scheme and len(schemes) == 1

        bundle_id = ""
        if selected_scheme:
            bundle_id = config.build_bundle_id or detect_bundle_id(project_path, kind, selected_scheme) or ""

        certs = detect_certificates() if signing == "manual" else []
        selected_cert = certificate or config.build_certificate or ""
        cert_sha1 = next((c.sha1 for c in certs if c.name == selected_cert), None)
        profiles = detect_profiles(bundle_id, cert_sha1) if signing == "manual" and bundle_id else []

        version_info = None
        archive_match = None
        if selected_scheme:
            version_info = detect_versions(project_path, kind, selected_scheme)
        if version_info:
            mv, bn = version_info
            archives = scan_archives(config.build_output, selected_scheme)
            archive_match = find_matching_archive(
                archives,
                bundle_id=bundle_id or config.build_bundle_id or "",
                marketing_version=mv,
                build_number=bn,
            )

        return {
            "ok": True,
            "project": project_path,
            "kind": kind,
            "project_selected": project_path,
            "schemes": schemes,
            "selected_scheme": selected_scheme,
            "scheme_auto": scheme_auto,
            "bundle_id": bundle_id,
            "bundle_id_selected": bundle_id,
            "certificates": [{"name": c.name, "sha1": c.sha1} for c in certs],
            "selected_certificate": selected_cert,
            "profiles": [
                {
                    "path": p.path,
                    "name": p.name,
                    "team_id": p.team_id,
                    "bundle_id": p.bundle_id,
                    "expiration": p.expiration.strftime("%Y-%m-%d"),
                }
                for p in profiles
            ],
            "selected_profile": config.build_profile or "",
            "version_info": {
                "marketing_version": version_info[0],
                "build_number": version_info[1],
            } if version_info else None,
            "archive_match": _archive_summary(archive_match),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "schemes": [], "certificates": [], "profiles": []}


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
    profile_details = {}
    for app in apps:
        data = config.get_app_profile(app) or {}
        key_file = data.get("key_file", "")
        profile_details[app] = {
            "issuer_id": data.get("issuer_id", ""),
            "key_id": data.get("key_id", ""),
            "key_file_name": Path(key_file).name if key_file else "",
            "app_id": str(data.get("app_id", "")),
            "csv": data.get("csv", ""),
            "screenshots": data.get("screenshots", ""),
        }
    return {"profiles": apps, "default": default, "profile_details": profile_details}


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
        return {"enabled": False, "bindings": {"machine": {}, "ip": {}, "credential": {}}, "app_notes": {}, "current_profile": "", "error": str(e)}


@router.post("/guard/note")
async def guard_note(
    app_id: str = _Form(...),
    note: str = _Form(""),
):
    from fastapi import HTTPException
    from asc.guard import Guard

    guard = Guard()
    if not guard.set_app_note(app_id, note):
        raise HTTPException(status_code=404, detail="App binding not found")
    return {"ok": True}


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


# ---------- Whats-New Translate ----------

@router.get("/whats-new/check")
def whats_new_check(request: Request):
    """Check environment and return available locales for the current app version."""
    profile = request.cookies.get("asc_profile", "")
    if not profile:
        return {"ok": False, "level": "error", "message": "No profile selected", "detail": {}}
    try:
        from asc.config import Config
        config = Config(app_name=profile)
        api, app_id = make_api_from_config(config)
        version = api.get_editable_version(app_id)
        if not version:
            return {
                "ok": False,
                "level": "warning",
                "message": "无可编辑版本",
                "detail": {},
            }
        version_string = version["attributes"].get("versionString", "?")
        locales = _get_available_locales(api, app_id)
        return {
            "ok": True,
            "level": "success",
            "message": f"版本 {version_string}，找到 {len(locales)} 个语言",
            "detail": {
                "version": version_string,
                "locales": [l["locale"] for l in locales],
            },
        }
    except Exception as e:
        return {"ok": False, "level": "error", "message": str(e), "detail": {}}


@router.post("/whats-new/translate")
async def whats_new_translate(request: Request):
    """Translate text to all available locales using LLM."""
    profile = request.cookies.get("asc_profile", "")
    if not profile:
        return JSONResponse({"error": "No profile selected"}, status_code=400)
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            data = await request.json()
        else:
            form = await request.form()
            data = dict(form)
        text = data.get("text", "")
        source_locale = data.get("source_locale", "auto")
        from asc.config import Config
        from asc.llm import LLMClient
        from asc.services.translator import OpenAITranslator
        config = Config(app_name=profile)
        if not config.llm_api_key:
            return JSONResponse({"error": "LLM API key not configured. Set [llm] api_key in config or OPENAI_API_KEY env var."}, status_code=400)
        llm_client = LLMClient(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
        )
        translator = OpenAITranslator(llm_client)
        # Get available locales
        api, app_id = make_api_from_config(config)
        version = api.get_editable_version(app_id)
        version_id = version["id"]
        ver_locs = api.get_version_localizations(version_id)
        all_locales = [loc["attributes"]["locale"] for loc in ver_locs]
        target_locales = [l for l in all_locales if l != source_locale] if source_locale != "auto" else all_locales
        translations = {}
        errors = []
        for locale in target_locales:
            try:
                translations[locale] = translator.translate(text, locale, source_locale)
            except Exception as e:
                translations[locale] = ""
                errors.append(f"{locale}: {e}")
        resp = {
            "source_locale": source_locale,
            "translations": translations,
        }
        if errors:
            resp["errors"] = errors
        return resp
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _start_whats_new_task(
    profile: str,
    dry_run: bool,
    translations: dict[str, str] | None = None,
    text: str | None = None,
    locales: list[str] | None = None,
) -> str:
    task_id = _task_store.create("whats-new", profile=profile)

    def _run():
        import queue
        from asc.web.sse import capture_stdout_to_queue
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
            version = api.get_editable_version(app_id)
            if not version:
                raise Exception("无可编辑版本")

            app_store_state = version["attributes"].get("appStoreState", "")
            editable_states = {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED"}
            if app_store_state not in editable_states:
                state_hint = {
                    "READY_FOR_SALE": "版本已上架，无法编辑更新说明。如需修改，请创建新版本。",
                    "WAITING_FOR_REVIEW": "版本正在等待审核，请先拒绝版本后再修改。",
                    "IN_REVIEW": "版本正在审核中，无法修改更新说明。",
                    "PENDING_APPLE_RELEASE": "版本待 Apple 发布，无法修改更新说明。",
                    "ACCEPTED": "版本已通过审核，无法修改更新说明。",
                }.get(app_store_state, f"当前版本状态「{app_store_state}」不允许编辑更新说明。")
                raise Exception(
                    f"无法编辑 What's New：{state_hint}\n"
                    f"💡 可编辑状态：{', '.join(editable_states)}"
                )

            version_id = version["id"]
            ver_locs = api.get_version_localizations(version_id)
            ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}

            if translations is not None:
                # Translation flow: use pre-translated dict
                total = len(translations)
                for i, (locale, content) in enumerate(translations.items()):
                    if locale not in ver_loc_map:
                        _task_store.append_log(task_id, f"⚠️  {locale}: 不存在，跳过")
                        continue
                    if dry_run:
                        _task_store.append_log(task_id, f"[DRYRUN] {locale}: {content[:50]}...")
                        continue
                    api.update_version_localization(ver_loc_map[locale]["id"], {"whatsNew": content})
                    _task_store.append_log(task_id, f"✅ {locale}: 已上传")
                    _task_store.set_progress(task_id, int((i + 1) / total * 100), f"上传 {locale}")
            else:
                # Direct text flow: apply same text to target locales
                target_locs = ver_locs
                if locales:
                    target_locs = [loc for loc in ver_locs if loc["attributes"]["locale"] in locales]
                    if not target_locs:
                        raise Exception(f"指定的语言不存在，可用语言: {list(ver_loc_map.keys())}")

                if dry_run:
                    _task_store.append_log(task_id, f"[DRYRUN] 预览模式，目标语言: {[l['attributes']['locale'] for l in target_locs]}")
                else:
                    for i, loc in enumerate(target_locs):
                        locale = loc["attributes"]["locale"]
                        api.update_version_localization(loc["id"], {"whatsNew": text or ""})
                        _task_store.append_log(task_id, f"✅ {locale}: 已更新")
                        _task_store.set_progress(task_id, int((i + 1) / len(target_locs) * 100), f"上传 {locale}")

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


@router.post("/whats-new/run")
async def whats_new_run(
    request: Request,
    translations_json: str = _Form(""),
    text: str = _Form(""),
    locales: str = _Form(""),
    dry_run: str = _Form(""),
):
    """Run whats-new upload. Supports both translate mode (translations_json) and direct mode (text+locales)."""
    import json
    profile = request.cookies.get("asc_profile", "")
    if not profile:
        return JSONResponse({"error": "No profile selected"}, status_code=400)

    def _as_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    translations = None
    locale_list = None
    payload = None

    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            payload = await request.json()
    except Exception:
        payload = None

    if payload is not None:
        payload_translations = payload.get("translations")
        if payload_translations is not None and not translations_json:
            translations_json = json.dumps(payload_translations)
        text = text or payload.get("text", "")
        locales = locales or payload.get("locales", "")
        if not dry_run and "dry_run" in payload:
            dry_run = payload["dry_run"]

    if translations_json:
        # Translate mode: pre-translated dict
        try:
            translations = json.loads(translations_json)
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    elif text:
        # Direct mode: same text to specified locales
        locale_list = [l.strip() for l in locales.split(",")] if locales else None
    else:
        return JSONResponse({"error": "Either translations_json or text is required"}, status_code=400)

    task_id = _start_whats_new_task(
        profile=profile,
        dry_run=_as_bool(dry_run),
        translations=translations,
        text=text or None,
        locales=locale_list,
    )
    return {"task_id": task_id}


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
            with capture_stdout_to_queue(q):
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


# ---------- URL Settings API ----------

def _get_available_locales(api, app_id: str) -> list[dict]:
    """Get all available locales from app version."""
    version = api.get_editable_version(app_id)
    if not version:
        return []
    version_id = version["id"]
    ver_locs = api.get_version_localizations(version_id)
    return [{"locale": loc["attributes"]["locale"], "id": loc["id"]} for loc in ver_locs]


@router.get("/urls/check")
async def urls_check(request: Request):
    """Check environment for URL settings."""
    profile = request.cookies.get("asc_profile", "")
    try:
        config = Config(app_name=profile)
        api, app_id = make_api_from_config(config)
        version = api.get_editable_version(app_id)
        if not version:
            return {
                "ok": False,
                "level": "warning",
                "message": "无可编辑版本",
                "detail": {},
            }
        locales = _get_available_locales(api, app_id)
        return {
            "ok": True,
            "level": "success",
            "message": f"环境正常，找到 {len(locales)} 个语言版本",
            "detail": {"locales": [l["locale"] for l in locales]},
        }
    except Exception as e:
        return {"ok": False, "level": "error", "message": str(e), "detail": {}}


@router.post("/urls/set")
async def urls_set(
    request: Request,
    field: str = _Form(...),  # supportUrl, marketingUrl, privacyPolicyUrl
    url: str = _Form(...),
    locales: str = _Form(""),  # comma-separated or empty for all
    dry_run: str = _Form(""),
):
    """Set a URL field directly."""
    profile = request.cookies.get("asc_profile", "")
    task_id = _task_store.create("urls", profile=profile)

    def _run():
        import queue
        from asc.web.sse import capture_stdout_to_queue

        _task_store.set_status(task_id, _TaskStatus.RUNNING)
        q: "queue.Queue" = queue.Queue()
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
            locale_list = [l.strip() for l in locales.split(",")] if locales else None

            with capture_stdout_to_queue(q):
                if field == "privacyPolicyUrl":
                    from asc.commands.metadata import _update_app_info_field_core
                    _update_app_info_field_core(
                        api, app_id, field, field, url, locale_list, bool(dry_run)
                    )
                else:
                    from asc.commands.metadata import _update_version_field_core
                    _update_version_field_core(
                        api, app_id, field, field, url, locale_list, bool(dry_run)
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
    return {"task_id": task_id}


# ---------- Update API ----------

@router.get("/update/check")
async def update_check():
    """Check for updates."""
    from asc.commands.update_cmd import _current_version, _latest_version_from_github, _parse_version

    current = _current_version()
    latest = _latest_version_from_github()
    if not latest:
        return {
            "ok": False,
            "level": "warning",
            "message": "无法连接到 GitHub",
            "detail": {"current": current},
        }
    is_latest = _parse_version(latest) <= _parse_version(current)
    return {
        "ok": True,
        "level": "success" if is_latest else "info",
        "message": f"当前版本: {current}" + (" (已是最新)" if is_latest else f" → 最新版本: {latest}"),
        "detail": {
            "current": current,
            "latest": latest,
            "is_latest": is_latest,
        },
    }


@router.post("/update/run")
async def update_run(version: str = _Form(""), branch: str = _Form(""), dry_run: str = _Form("")):
    """Run update."""
    task_id = _task_store.create("update", profile="system")

    def _run():
        _task_store.set_status(task_id, _TaskStatus.RUNNING)
        try:
            from asc.commands.update_cmd import cmd_update
            import io
            import sys

            old_stdout = sys.stdout
            sys.stdout = captured = io.StringIO()

            try:
                cmd_update(version=version or None, branch=branch or None, yes=True)
            finally:
                sys.stdout = old_stdout

            output = captured.getvalue()
            for line in output.splitlines():
                _task_store.append_log(task_id, line)

            _task_store.set_status(task_id, _TaskStatus.DONE)
            _task_store.set_result(task_id, {"success": True})
        except Exception as e:
            _task_store.append_log(task_id, f"❌ 错误：{e}")
            _task_store.set_status(task_id, _TaskStatus.ERROR)
            _task_store.set_result(task_id, {"success": False, "error": str(e)})

    _threading.Thread(target=_run, daemon=True).start()
    return {"task_id": task_id}

@router.get("/settings/llm")
async def get_llm_config(request: Request):
    """Returns all LLM configs and the default config name."""
    from asc.config import Config
    config = Config()
    return {
        "configs": config.llm_configs,
        "default": config.llm_default,
    }


@router.post("/settings/llm")
async def save_llm_config(request: Request):
    """Save a named LLM config to the global llm.toml. Set as default if specified."""
    from asc.config import Config

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    name = data.get("name", "default")
    base_url = data.get("base_url", "https://api.openai.com/v1")
    api_key = data.get("api_key", "")
    model = data.get("model", "gpt-4o")
    set_default = data.get("set_default", True)

    try:
        config = Config()
        config.save_llm_config(name, base_url, api_key, model, set_default=set_default)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/settings/llm")
async def delete_llm_config(request: Request, name: str = Query(...)):
    """Delete a named LLM config from the global llm.toml."""
    from asc.config import Config

    try:
        config = Config()
        config.delete_llm_config(name)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/settings/llm/default")
async def set_llm_default(request: Request):
    """Set the default LLM config."""
    from asc.config import Config

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    name = data.get("name")
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)

    try:
        config = Config()
        config.set_llm_default(name)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
