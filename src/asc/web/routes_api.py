"""API routes for asc Web UI (/api/*)."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from asc.commands.iap import _upload_iap_core, _load_iap_config, _iap_phase_plan
from asc.commands.iap_review_screenshots import (
    ReviewScreenshotUploadItem,
    attach_default_paths,
    extract_review_screenshot_paths,
    scan_missing_review_screenshots,
    upload_review_screenshots,
)
from asc.commands.subscriptions import _upload_subscriptions_core
from asc.config import Config
from asc.guard import enforce_bundle_guard, enforce_config_guard, read_ipa_bundle_id
from asc.utils import make_api_from_config
from asc.web import notifications
from asc.web.dashboard import MANUAL_BASELINE_MINUTES, build_dashboard_summary
from asc.web.i18n import t
from asc.web.task_runner import SSE_ABSOLUTE_TIMEOUT_SEC, start_background_task

router = APIRouter()

_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_HOME = Path.home().resolve()
_TMPDIR = Path(tempfile.gettempdir()).resolve()
_ALLOWED_ROOTS = (_HOME, _TMPDIR)
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _lang(request: Request) -> str:
    from asc.web.i18n import COOKIE_NAME, resolve_lang

    return getattr(request.state, "lang", None) or resolve_lang(
        cookie=request.cookies.get(COOKIE_NAME),
        accept_language=request.headers.get("accept-language"),
    )


def _i18n_template_ctx(request: Request) -> dict:
    from asc.web.i18n import html_lang, load_catalog, t as translate

    lang = _lang(request)

    def _t(key: str, **kwargs: object) -> str:
        return translate(key, lang=lang, **kwargs)

    return {
        "lang": lang,
        "html_lang": html_lang(lang),
        "t": _t,
        "i18n_catalog": load_catalog(lang),
    }


def _validate_webhook_config_payload(data: object) -> str | None:
    if not isinstance(data, dict):
        return "JSON body must be an object"

    enabled = data.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        return "enabled must be a boolean"

    notify_kinds = data.get("notify_kinds")
    if notify_kinds is not None:
        if not isinstance(notify_kinds, list):
            return "notify_kinds must be a list"
        invalid_kinds = [
            item
            for item in notify_kinds
            if not isinstance(item, str) or item not in notifications.TASK_KINDS
        ]
        if invalid_kinds:
            return "Invalid notify_kinds value"

    notify_statuses = data.get("notify_statuses")
    if notify_statuses is not None:
        if not isinstance(notify_statuses, list):
            return "notify_statuses must be a list"
        invalid_statuses = [
            item
            for item in notify_statuses
            if not isinstance(item, str) or item not in notifications.TERMINAL_STATUSES
        ]
        if invalid_statuses:
            return "Invalid notify_statuses value"

    providers = data.get("providers")
    if providers is None:
        return None
    if not isinstance(providers, dict):
        return "providers must be an object"

    for provider, provider_config in providers.items():
        if provider not in notifications.PROVIDERS:
            return f"Unknown provider: {provider}"
        if not isinstance(provider_config, dict):
            return f"Provider {provider} must be an object"

        provider_enabled = provider_config.get("enabled")
        if provider_enabled is not None and not isinstance(provider_enabled, bool):
            return f"Provider {provider} enabled must be a boolean"

        url = provider_config.get("url")
        if url is not None:
            if not isinstance(url, str):
                return f"Provider {provider} url must be a string"
            stripped_url = url.strip()
            if stripped_url and not (
                stripped_url.startswith("http://") or stripped_url.startswith("https://")
            ):
                return f"Provider {provider} url must start with http:// or https://"

    return None


def _is_under_allowed_root(target: Path) -> bool:
    """Return True if target is at or under any allowed root."""
    for root in _ALLOWED_ROOTS:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _extension_filter(ext: str) -> set[str]:
    return {
        part.strip().lower()
        for part in ext.split(",")
        if part.strip()
    }


@router.get("/switch-profile")
async def switch_profile(profile: str):
    """Switch active app profile (stores in session cookie)."""
    from fastapi import HTTPException
    from asc.config import Config
    from asc.guard import Guard

    config = Config()
    profiles = {
        name: config.get_app_profile(name) or {}
        for name in config.list_apps()
    }
    if profile not in profiles:
        raise HTTPException(status_code=404, detail="Profile not found")
    access = Guard().profile_access(profiles)["options"].get(profile, {})
    if not access.get("enabled", False):
        raise HTTPException(status_code=403, detail="Profile is bound to another machine")
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

    allowed_exts = _extension_filter(ext)
    for item in items:
        if item.name.startswith("."):
            continue
        if mode == "file" and not item.is_dir():
            if allowed_exts and item.suffix.lower() not in allowed_exts:
                continue
        entries.append({"name": item.name, "path": str(item), "is_dir": item.is_dir()})

    return _templates.TemplateResponse(request, "filebrowser.html", {
        "current_path": str(target),
        "entries": entries,
        "mode": mode,
        "ext": ext,
        **_i18n_template_ctx(request),
    })


import threading as _threading
from fastapi import Form as _Form
from asc.web.tasks import task_store as _task_store, TaskStatus as _TaskStatus
from asc.progress import ProcessCanceled


def _finish_task(task_id: str, status: _TaskStatus, result: dict) -> None:
    current = _task_store.get_state(task_id) or _task_store.get(task_id)
    if current is not None:
        current_status = current.get("status")
        current_value = getattr(current_status, "value", current_status)
        if current_value in {"done", "error", "canceled"}:
            return
    _task_store.set_status(task_id, status)
    _task_store.set_result(task_id, result)
    try:
        notifications.notify_task_finished(task_id, task_store=_task_store)
    except Exception as exc:
        _task_store.append_log(task_id, f"群通知处理失败：{exc.__class__.__name__}")


def _enforce_web_profile_guard(
    app_id: str,
    app_name: str,
    key_id: str,
    issuer_id: str,
) -> None:
    from fastapi import HTTPException
    from asc.guard import Guard, GuardViolationError

    guard = Guard()
    if not guard.is_enabled():
        return
    try:
        guard.check_and_enforce(
            app_id=app_id,
            app_name=app_name,
            key_id=key_id,
            issuer_id=issuer_id,
            interactive=False,
        )
    except GuardViolationError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


def _run_metadata_check(profile: str, lang: str = "en") -> dict:
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
                "message": t("api.no_editable_version_create", lang=lang),
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
            message = t("api.env_ok_version_editable", lang=lang, version=vs)
        else:
            level = "warning"
            message = t("api.version_not_editable", lang=lang, version=vs, state=state)
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
    verbose: bool = False,
) -> str:
    guard_enforcer = enforce_config_guard
    task_id = _task_store.create("metadata", profile=profile)

    def run(reporter, cancel_event):
        from asc.config import Config
        from asc.utils import make_api_from_config, parse_csv

        try:
            config = Config(app_name=profile)
            guard_enforcer(config, interactive=False)
            api, app_id = make_api_from_config(config)

            combined = include_metadata and include_screenshots
            if combined:
                # One phase plan for the whole task so pct stays monotonic.
                reporter.set_phases([
                    ("check", 5, "校验"),
                    ("locales", 45, "元数据"),
                    ("scan", 5, "扫描"),
                    ("upload", 45, "截图"),
                ])

            if include_metadata:
                from asc.commands.metadata import _upload_metadata_core

                metadata_list = parse_csv(csv_path)
                _upload_metadata_core(
                    api,
                    app_id,
                    metadata_list,
                    dry_run=dry_run,
                    cancel_event=cancel_event,
                    reporter=reporter,
                    manage_phases=not combined,
                    finalize=not combined,
                )

            if include_screenshots:
                from asc.commands.screenshots import _upload_screenshots_core

                _upload_screenshots_core(
                    api,
                    app_id,
                    screenshots_dir,
                    dry_run=dry_run,
                    cancel_event=cancel_event,
                    reporter=reporter,
                    manage_phases=not combined,
                    finalize=True,
                )

            if cancel_event.is_set():
                raise ProcessCanceled("metadata upload canceled")

            _finish_task(task_id, _TaskStatus.DONE, {"success": True})
            return {"success": True}
        except ProcessCanceled:
            reporter.log("⏹ 用户已终止上传")
            _finish_task(
                task_id,
                _TaskStatus.CANCELED,
                {"success": False, "canceled": True},
            )
            raise
        except Exception as e:
            _finish_task(
                task_id,
                _TaskStatus.ERROR,
                {"success": False, "error": str(e)},
            )
            raise

    return start_background_task(
        _task_store,
        kind="metadata",
        profile=profile,
        verbose=verbose,
        run=run,
        task_id=task_id,
    )


@router.post("/metadata/check")
async def metadata_check(request: Request):
    profile = request.cookies.get("asc_profile", "")
    result = _run_metadata_check(profile, lang=_lang(request))
    return result


@router.post("/metadata/run")
async def metadata_run(
    request: Request,
    csv_path: str = _Form("data/appstore_info.csv"),
    screenshots_dir: str = _Form("data/screenshots"),
    include_metadata: str = _Form(""),
    include_screenshots: str = _Form(""),
    dry_run: str = _Form(""),
    verbose: str = _Form(""),
):
    profile = request.cookies.get("asc_profile", "")
    task_id = _start_metadata_task(
        profile=profile,
        csv_path=csv_path,
        screenshots_dir=screenshots_dir,
        include_metadata=bool(include_metadata),
        include_screenshots=bool(include_screenshots),
        dry_run=bool(dry_run),
        verbose=bool(verbose),
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
    from asc.commands.build import _build_phase_plan, build_core, deploy_core
    from asc.config import Config

    task_id = _task_store.create("build", profile=profile)
    guard_enforcer = enforce_config_guard

    def run(reporter, cancel_event):
        try:
            config = Config(app_name=profile)
            guard_enforcer(config, interactive=False)

            if mode in ("full", "build"):
                from asc.commands.build_inputs import (
                    BuildInputsCLI, prepare_build_inputs
                )
                cli = BuildInputsCLI(
                    project=project or None,
                    scheme=scheme or None,
                    destination=destination or None,
                    signing=signing or None,
                    certificate=certificate or None,
                    profile=provisioning_profile or None,
                )
                resolved = prepare_build_inputs(cli, config, interactive=False)
                enforce_bundle_guard(config, resolved.bundle_id)
                reuse_value = None
                if reuse_archive == "reuse":
                    reuse_value = True
                elif reuse_archive == "rebuild":
                    reuse_value = False

                if mode == "full":
                    reporter.set_phases(_build_phase_plan(mode="full"))
                    ipa = build_core(
                        resolved,
                        config.build_output,
                        dry_run=dry_run,
                        reuse_archive=reuse_value,
                        interactive=False,
                        verbose=verbose,
                        cancel_event=cancel_event,
                        reporter=reporter,
                        configure_phases=False,
                    )
                    if ipa:
                        deploy_core(
                            ipa_path=ipa,
                            issuer_id=config.issuer_id,
                            key_id=config.key_id,
                            key_file=config.key_file,
                            destination=destination or "appstore",
                            dry_run=dry_run,
                            verbose=verbose,
                            cancel_event=cancel_event,
                            reporter=reporter,
                            configure_phases=False,
                        )
                    elif dry_run:
                        reporter.done()
                else:
                    build_core(
                        resolved,
                        config.build_output,
                        dry_run=dry_run,
                        reuse_archive=reuse_value,
                        interactive=False,
                        verbose=verbose,
                        cancel_event=cancel_event,
                        reporter=reporter,
                    )
            elif mode == "deploy":
                enforce_bundle_guard(config, read_ipa_bundle_id(ipa_path))
                deploy_core(
                    ipa_path=ipa_path,
                    issuer_id=config.issuer_id,
                    key_id=config.key_id,
                    key_file=config.key_file,
                    destination=destination or "appstore",
                    dry_run=dry_run,
                    verbose=verbose,
                    cancel_event=cancel_event,
                    reporter=reporter,
                )

            if cancel_event.is_set():
                raise ProcessCanceled("build canceled")
            result = {"success": True}
            _finish_task(task_id, _TaskStatus.DONE, result)
            return result
        except ProcessCanceled:
            reporter.log("⏹ 用户已终止上传")
            _finish_task(
                task_id,
                _TaskStatus.CANCELED,
                {"success": False, "canceled": True},
            )
            raise
        except Exception as e:
            _finish_task(
                task_id,
                _TaskStatus.ERROR,
                {"success": False, "error": str(e)},
            )
            raise

    return start_background_task(
        _task_store,
        kind="build",
        profile=profile,
        verbose=verbose,
        run=run,
        task_id=task_id,
    )


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
async def task_stream(
    task_id: str,
    after: int = Query(0, ge=0),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    """SSE stream: replay sequenced logs after a cursor until task completes."""
    task = await _asyncio.to_thread(_task_store.get_state, task_id)
    if task is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Task not found")

    async def _generate():
        sent = after
        if last_event_id is not None:
            try:
                sent = max(sent, int(last_event_id))
            except ValueError:
                pass
        last_progress = None
        polls = 0
        started = time.monotonic()
        while True:
            current = await _asyncio.to_thread(_task_store.get_state, task_id)
            if current is None:
                yield _fmt_sse("error_event", "task not found")
                break
            logs = await _asyncio.to_thread(_task_store.get_logs_after, task_id, sent)
            for log in logs:
                yield _fmt_sse("log", log["message"], event_id=log["seq"])
                sent = log["seq"]
            # Emit progress event if changed
            progress = current.get("progress")
            if progress and progress != last_progress:
                yield _fmt_sse("progress", json.dumps(progress))
                last_progress = progress
            status = current["status"]
            if status == _TaskStatus.DONE:
                yield _fmt_sse("done", "")
                break
            elif status == _TaskStatus.CANCELED:
                yield _fmt_sse("canceled", "")
                break
            elif status == _TaskStatus.ERROR:
                yield _fmt_sse("error_event", "")
                break
            if time.monotonic() - started >= SSE_ABSOLUTE_TIMEOUT_SEC:
                yield _fmt_sse("error_event", "timeout")
                break
            if polls % 15 == 0:
                yield ": heartbeat\n\n"
            polls += 1
            await _asyncio.sleep(0.2)

    return _StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/task/{task_id}/status")
def task_status(task_id: str):
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


@router.post("/task/{task_id}/cancel")
async def task_cancel(task_id: str):
    """Request cooperative cancellation; the worker sets the terminal status."""
    from fastapi import HTTPException

    task = _task_store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    status_value = getattr(task.get("status"), "value", task.get("status"))
    if status_value in {"done", "error", "canceled"}:
        return {
            "task_id": task_id,
            "cancel_requested": True,
            "status": status_value,
        }

    _task_store.request_cancel(task_id)
    _task_store.append_log(task_id, "⏹ 已请求终止，正在停止当前步骤...")
    return {"task_id": task_id, "cancel_requested": True, "status": status_value}


import shutil as _shutil
from fastapi import UploadFile as _UploadFile, File as _File


async def _save_uploaded_key(key_file: _UploadFile) -> Path:
    """Store an uploaded key by content hash so another profile cannot overwrite it."""
    content = await key_file.read()
    if not content or len(content) > 1024 * 1024:
        raise HTTPException(status_code=400, detail="Invalid key file")
    global_keys_dir = Path.home() / ".config" / "asc" / "keys"
    global_keys_dir.mkdir(parents=True, exist_ok=True)
    dest_key = global_keys_dir / f"{hashlib.sha256(content).hexdigest()}.p8"
    if not dest_key.exists():
        temp_key = global_keys_dir / f".{dest_key.name}.tmp"
        temp_key.write_bytes(content)
        temp_key.chmod(0o600)
        temp_key.replace(dest_key)
    dest_key.chmod(0o600)
    return dest_key


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
    from asc.guard import Guard
    guard = Guard()
    access = guard.profile_access({
        app: config.get_app_profile(app) or {}
        for app in apps
    })
    bound_app_ids = guard.bound_app_ids()
    for app in apps:
        profile_details[app]["machine_access"] = access["options"].get(app, {})
        profile_details[app]["bundle_ids"] = guard.profile_bundle_ids(app)
        profile_details[app]["already_bound"] = bool(
            profile_details[app]["app_id"] and profile_details[app]["app_id"] in bound_app_ids
        )
    return {
        "profiles": apps,
        "default": default,
        "profile_details": profile_details,
        "matched_profile": access["matched_profile"],
        "can_create": not bool(access["matched_profile"]),
    }


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

    from asc.config import Config
    config = Config()
    _enforce_web_profile_guard(app_id, name, key_id, issuer_id)

    if not key_file.filename or not key_file.filename.lower().endswith(".p8"):
        raise HTTPException(status_code=400, detail="Invalid key filename")
    dest_key = await _save_uploaded_key(key_file)

    config.save_app_profile(name, issuer_id, key_id, str(dest_key), app_id, csv, screenshots)
    return {"ok": True, "name": name}


@router.get("/profiles/discover-local")
async def discover_local_profiles():
    """Scan cwd (and parents) for AppStore/Config/.env not yet in profiles."""
    from asc.utils import discover_local_import_candidates

    candidates = discover_local_import_candidates(Path.cwd())
    return {
        "candidates": candidates,
        "cwd": str(Path.cwd()),
    }


@router.post("/profiles/import")
async def import_local_profile(request: Request):
    """Import the local AppStore/Config/.env into a global profile."""
    from fastapi import HTTPException
    from asc.commands.app_config import _do_import_from_env, _is_valid_profile_name, _write_local_default
    from asc.guard import GuardViolationError
    from asc.utils import discover_local_import_candidates, find_project_env

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    name = (body.get("name") or "").strip() or None
    set_default = _as_bool(body.get("set_default", True))

    if name is not None and not _is_valid_profile_name(name):
        raise HTTPException(status_code=400, detail="Invalid profile name")

    candidates = discover_local_import_candidates(Path.cwd())
    if not candidates:
        raise HTTPException(status_code=404, detail="No importable local app config found")

    candidate = candidates[0]
    if name is None:
        name = candidate["suggested_name"]
    if not candidate.get("key_file_exists"):
        raise HTTPException(
            status_code=400,
            detail=f"Key file not found: {candidate.get('key_file')}",
        )

    found = find_project_env(Path.cwd())
    if not found:
        raise HTTPException(status_code=404, detail="No AppStore/Config/.env found")
    project_root, env_file = found

    try:
        profile_name = _do_import_from_env(
            str(env_file),
            project_root,
            name,
            quiet=True,
            interactive=False,
        )
    except GuardViolationError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if set_default:
        _write_local_default(project_root / ".asc", profile_name)

    return {
        "ok": True,
        "name": profile_name,
        "project_root": str(project_root),
        "set_default": set_default,
    }


@router.put("/profiles/{name}")
async def update_profile(
    request: Request,
    name: str,
    new_name: str = _Form(..., alias="name"),
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
    if not re.match(r'^[a-zA-Z0-9_-]+$', new_name):
        raise HTTPException(status_code=400, detail="Invalid profile name")

    from asc.config import Config
    config = Config()
    existing = config.get_app_profile(name)
    if existing is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if new_name != name and config.get_app_profile(new_name) is not None:
        raise HTTPException(status_code=409, detail="Profile name already exists")

    _enforce_web_profile_guard(app_id, new_name, key_id, issuer_id)

    key_file_path = existing["key_file"]
    if key_file and key_file.filename:
        if not key_file.filename.lower().endswith(".p8"):
            raise HTTPException(status_code=400, detail="Invalid key filename")
        dest_key = await _save_uploaded_key(key_file)
        key_file_path = str(dest_key)

    config.save_app_profile(new_name, issuer_id, key_id, key_file_path, app_id, csv, screenshots)
    if new_name != name:
        from asc.guard import Guard
        Guard().rename_profile(name, new_name)
        config.remove_app_profile(name)

        local_cfg = Path.cwd() / ".asc" / "config.toml"
        if local_cfg.exists():
            content = local_cfg.read_text()
            old_value = re.escape(name)
            safe_name = new_name.replace("\\", "\\\\").replace('"', '\\"')
            content = re.sub(
                rf'(default_app\s*=\s*"){old_value}(")',
                lambda m: f"{m.group(1)}{safe_name}{m.group(2)}",
                content,
            )
            local_cfg.write_text(content)

    resp = JSONResponse({"ok": True, "name": new_name, "old_name": name})
    if request.cookies.get("asc_profile") == name:
        resp.set_cookie("asc_profile", new_name, httponly=True, samesite="lax")
    return resp


@router.delete("/profiles/{name}")
async def delete_profile(name: str):
    import re
    from fastapi import HTTPException

    # Fix 2: Validate profile name
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise HTTPException(status_code=400, detail="Invalid profile name")

    from asc.config import Config
    config = Config()
    from asc.guard import Guard
    Guard().remove_profile(name)
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


def _empty_current_environment() -> dict:
    return {
        "machine": {
            "fingerprint": "",
            "bound": False,
            "app_id": "",
            "app_name": "",
            "note": "",
            "profile_name": "",
        },
        "ip": {
            "address": "unknown",
            "available": False,
            "bound": False,
            "app_id": "",
            "app_name": "",
            "note": "",
            "profile_name": "",
        },
    }


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
                app_id_to_profile[str(pdata["app_id"])] = p
        # Inject profile_name into each binding entry
        for category in ("machine", "ip", "credential"):
            for key, info in data.get("bindings", {}).get(category, {}).items():
                info["profile_name"] = app_id_to_profile.get(str(info.get("app_id", "")), "")
        env = copy.deepcopy(guard.current_environment())
        for section in ("machine", "ip"):
            env[section]["profile_name"] = app_id_to_profile.get(
                str(env[section].get("app_id", "")), ""
            )
        data["current_environment"] = env
        return data
    except Exception as e:
        return {
            "enabled": False,
            "bindings": {"machine": {}, "ip": {}, "credential": {}},
            "app_notes": {},
            "current_profile": "",
            "current_environment": _empty_current_environment(),
            "error": str(e),
        }


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


@router.post("/guard/manual-bind")
async def guard_manual_bind(
    fingerprint: str = _Form(...),
    profile: str = _Form(...),
    ip: str = _Form(""),
    note: str = _Form(""),
):
    """Manually register a machine-fingerprint binding for a local app profile.

    Credential fields (app_id/issuer_id/key_id) always come from the selected
    profile - the client cannot override key_id here.
    """
    from fastapi import HTTPException
    from asc.config import Config
    from asc.guard import Guard, GuardConfigError, GuardViolationError

    fingerprint = fingerprint.strip()
    profile = profile.strip()
    if not fingerprint:
        raise HTTPException(status_code=400, detail="Machine fingerprint is required")
    if not profile:
        raise HTTPException(status_code=400, detail="Local app profile is required")

    config = Config()
    profile_data = config.get_app_profile(profile)
    if profile_data is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    guard = Guard()
    try:
        result = guard.manual_bind(
            fingerprint,
            profile,
            app_id=str(profile_data.get("app_id", "")),
            issuer_id=profile_data.get("issuer_id", ""),
            key_id=profile_data.get("key_id", ""),
            ip=ip.strip(),
            note=note.strip(),
        )
    except GuardConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except GuardViolationError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"ok": True, "binding": result}


@router.get("/tasks/recent", response_class=HTMLResponse)
async def tasks_recent_html(request: Request):
    """Return HTML fragment of recent tasks for HTMX polling."""
    tasks = _task_store.list_recent(limit=20)
    return _templates.TemplateResponse(
        request,
        "task_list.html",
        {"tasks": tasks, **_i18n_template_ctx(request)},
    )


@router.get("/dashboard/summary")
def dashboard_summary(
    request: Request,
    range_: str = Query("30d", alias="range"),
    profile: Optional[str] = Query(None),
    kind: str = "",
    status: str = "",
):
    ranges = {"7d": 7, "30d": 30, "90d": 90}
    statuses = {"", "pending", "running", "done", "error", "canceled"}
    if range_ not in ranges:
        raise HTTPException(status_code=400, detail="range must be one of: 7d, 30d, 90d")
    if kind and kind not in MANUAL_BASELINE_MINUTES:
        raise HTTPException(status_code=400, detail="kind must be a supported task kind or empty")
    if status not in statuses:
        raise HTTPException(
            status_code=400,
            detail="status must be one of: pending, running, done, error, canceled, or empty",
        )

    selected_profile = request.cookies.get("asc_profile", "") if profile is None else profile
    return build_dashboard_summary(
        _task_store.list_recent_states(limit=500),
        days=ranges[range_],
        profile=selected_profile,
        kind=kind,
        status=status,
    )


@router.post("/settings/lang")
async def set_lang(request: Request, lang: str = _Form("zh")):
    import os

    from asc.web.i18n import (
        COOKIE_MAX_AGE,
        COOKIE_NAME,
        SUPPORTED_LANGS,
        normalize_lang,
    )

    code = normalize_lang(lang)
    if code not in SUPPORTED_LANGS:
        raise HTTPException(
            status_code=400,
            detail=t("api.invalid_lang", lang=_lang(request)),
        )
    os.environ["ASC_LANG"] = code
    resp = JSONResponse({"ok": True, "lang": code})
    resp.set_cookie(
        COOKIE_NAME,
        code,
        max_age=COOKIE_MAX_AGE,
        path="/",
        samesite="lax",
    )
    return resp


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


@router.get("/examples/iap")
@router.get("/examples/iap.json")
async def download_example_iap():
    """Download the example IAP JSON file."""
    iap_path = _TEMPLATES_DIR / "iap_packages.json"
    if not iap_path.exists():
        return Response("Example IAP JSON not found", status_code=404)
    return FileResponse(
        iap_path,
        media_type="application/json",
        filename="iap_packages_example.json",
    )


# ---------- Whats-New Translate ----------

@router.get("/whats-new/check")
def whats_new_check(request: Request):
    """Check environment and return available locales for the current app version."""
    lang = _lang(request)
    profile = request.cookies.get("asc_profile", "")
    if not profile:
        return {
            "ok": False,
            "level": "error",
            "message": t("api.no_profile", lang=lang),
            "detail": {},
        }
    try:
        from asc.config import Config
        config = Config(app_name=profile)
        api, app_id = make_api_from_config(config)
        version = api.get_editable_version(app_id)
        if not version:
            return {
                "ok": False,
                "level": "warning",
                "message": t("api.no_editable_version", lang=lang),
                "detail": {},
            }
        version_string = version["attributes"].get("versionString", "?")
        locales = _get_available_locales(api, app_id)
        return {
            "ok": True,
            "level": "success",
            "message": t(
                "api.version_locales",
                lang=lang,
                version=version_string,
                count=len(locales),
            ),
            "detail": {
                "version": version_string,
                "locales": [l["locale"] for l in locales],
            },
        }
    except Exception as e:
        return {"ok": False, "level": "error", "message": str(e), "detail": {}}


@router.post("/whats-new/translate")
async def whats_new_translate(request: Request):
    """Start a preview-translate background task; result.translations on task done."""
    lang = _lang(request)
    profile = request.cookies.get("asc_profile", "")
    if not profile:
        return JSONResponse({"error": t("api.no_profile", lang=lang)}, status_code=400)
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            data = await request.json()
        else:
            form = await request.form()
            data = dict(form)
        text = str(data.get("text", "")).strip()
        source_locale = data.get("source_locale", "auto") or "auto"
        verbose = _as_bool(data.get("verbose", False))
        if not text:
            return JSONResponse({"error": "Text is required"}, status_code=400)
        config = Config(app_name=profile)
        if not config.llm_api_key:
            return JSONResponse(
                {"error": "LLM API key not configured. Set it in Web settings or OPENAI_API_KEY."},
                status_code=400,
            )
        task_id = _start_whats_new_translate_task(
            profile=profile,
            text=text,
            source_locale=source_locale,
            verbose=verbose,
        )
        return {"task_id": task_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _start_whats_new_translate_task(
    profile: str,
    text: str,
    source_locale: str = "auto",
    verbose: bool = False,
) -> str:
    """Preview translate only: translate phase 100%; result.translations (+ errors)."""
    from asc.commands.whats_new import _make_translator, _whats_new_translate_only_core

    task_id = _task_store.create("whats-new-translate", profile=profile)
    guard_enforcer = enforce_config_guard

    def run(reporter, cancel_event):
        try:
            config = Config(app_name=profile)
            guard_enforcer(config, interactive=False)
            if not config.llm_api_key:
                raise ValueError(
                    "LLM API key not configured. Set it in Web settings or OPENAI_API_KEY."
                )
            api, app_id = make_api_from_config(config)
            translator = _make_translator(config)
            result = _whats_new_translate_only_core(
                api,
                app_id,
                text=text,
                source_locale=source_locale or "auto",
                translator=translator,
                reporter=reporter,
                cancel_event=cancel_event,
            )
            if cancel_event.is_set():
                raise ProcessCanceled("whats-new translate canceled")
            _finish_task(task_id, _TaskStatus.DONE, result)
            return result
        except ProcessCanceled:
            reporter.log("⏹ 用户已终止翻译")
            _finish_task(
                task_id,
                _TaskStatus.CANCELED,
                {"success": False, "canceled": True},
            )
            raise
        except Exception as e:
            reporter.fail(str(e))
            _finish_task(
                task_id,
                _TaskStatus.ERROR,
                {"success": False, "error": str(e)},
            )
            raise

    return start_background_task(
        _task_store,
        kind="whats-new-translate",
        profile=profile,
        verbose=verbose,
        run=run,
        task_id=task_id,
    )


def _start_whats_new_task(
    profile: str,
    dry_run: bool,
    translations: dict[str, str] | None = None,
    text: str | None = None,
    locales: list[str] | None = None,
    *,
    translate: bool = False,
    source_locale: str = "auto",
    verbose: bool = False,
) -> str:
    from asc.commands.whats_new import _make_translator, _whats_new_core

    task_id = _task_store.create("whats-new", profile=profile)
    guard_enforcer = enforce_config_guard

    def run(reporter, cancel_event):
        try:
            config = Config(app_name=profile)
            guard_enforcer(config, interactive=False)
            api, app_id = make_api_from_config(config)

            translator = None
            if translate and translations is None:
                if not config.llm_api_key:
                    raise ValueError(
                        "LLM API key not configured. Set it in Web settings or OPENAI_API_KEY."
                    )
                translator = _make_translator(config)

            result = _whats_new_core(
                api,
                app_id,
                text=text,
                translations=translations,
                locales=locales,
                translate=translate and translations is None,
                source_locale=source_locale or "auto",
                dry_run=dry_run,
                translator=translator,
                reporter=reporter,
                cancel_event=cancel_event,
                require_editable_state=True,
            )
            if cancel_event.is_set():
                raise ProcessCanceled("whats-new upload canceled")
            _finish_task(task_id, _TaskStatus.DONE, result)
            return result
        except ProcessCanceled:
            reporter.log("⏹ 用户已终止上传")
            _finish_task(
                task_id,
                _TaskStatus.CANCELED,
                {"success": False, "canceled": True},
            )
            raise
        except Exception as e:
            reporter.fail(str(e))
            _finish_task(
                task_id,
                _TaskStatus.ERROR,
                {"success": False, "error": str(e)},
            )
            raise

    return start_background_task(
        _task_store,
        kind="whats-new",
        profile=profile,
        verbose=verbose,
        run=run,
        task_id=task_id,
    )


@router.post("/whats-new/run")
async def whats_new_run(
    request: Request,
    translations_json: str = _Form(""),
    text: str = _Form(""),
    locales: str = _Form(""),
    dry_run: str = _Form(""),
    translate: str = _Form(""),
    source_locale: str = _Form("auto"),
    verbose: str = _Form(""),
):
    """Run whats-new upload. Supports translated dicts, translate mode, and direct text mode."""
    import json
    lang = _lang(request)
    profile = request.cookies.get("asc_profile", "")
    if not profile:
        return JSONResponse({"error": t("api.no_profile", lang=lang)}, status_code=400)

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
        source_locale = payload.get("source_locale", source_locale) or "auto"
        if not dry_run and "dry_run" in payload:
            dry_run = payload["dry_run"]
        if not translate and "translate" in payload:
            translate = payload["translate"]
        if not verbose and "verbose" in payload:
            verbose = payload["verbose"]

    translate_requested = _as_bool(translate)

    if translations_json:
        # Pre-supplied translations: upload-only
        try:
            translations = json.loads(translations_json)
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    elif translate_requested and text:
        # LLM runs inside the worker (not request thread)
        locale_list = [l.strip() for l in locales.split(",")] if locales else None
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
        translate=translate_requested and translations is None,
        source_locale=source_locale or "auto",
        verbose=_as_bool(verbose),
    )
    return {"task_id": task_id}


# ---------- IAP helpers & endpoints ----------


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
    task_id = _task_store.create("iap-review-screenshots", profile=profile)
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
                _finish_task(task_id, _TaskStatus.ERROR, payload)
                raise RuntimeError(payload["error"])

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
                _finish_task(task_id, _TaskStatus.DONE, payload)
                return payload
            _finish_task(task_id, _TaskStatus.ERROR, payload)
            raise RuntimeError(
                f"review screenshot upload failed: {result.failed} item(s)"
            )
        except Exception as e:
            current = _task_store.get_state(task_id) or _task_store.get(task_id)
            current_status = (
                getattr(current.get("status"), "value", current.get("status"))
                if current
                else None
            )
            if current_status not in {"done", "error", "canceled"}:
                reporter.fail(f"❌ 错误：{e}")
                _finish_task(
                    task_id,
                    _TaskStatus.ERROR,
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
    task_id = _task_store.create("iap", profile=profile)
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
                _upload_iap_core(
                    api,
                    app_id,
                    items,
                    dry_run=dry_run,
                    update_existing=update_existing,
                    reporter=reporter,
                    manage_phases=False,
                    finalize=not bool(groups),
                )
            if groups:
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
                )
                if failed:
                    raise RuntimeError(f"subscription upload failed: {failed} item(s)")

            _finish_task(task_id, _TaskStatus.DONE, {"success": True})
            return {"success": True}
        except Exception as e:
            current = _task_store.get_state(task_id) or _task_store.get(task_id)
            current_status = (
                getattr(current.get("status"), "value", current.get("status"))
                if current
                else None
            )
            if current_status not in {"done", "error", "canceled"}:
                _finish_task(
                    task_id,
                    _TaskStatus.ERROR,
                    {"success": False, "error": str(e)},
                )
            raise

    return start_background_task(
        _task_store,
        kind="iap",
        profile=profile,
        verbose=verbose,
        run=run,
        task_id=task_id,
    )
@router.post("/iap/run")
async def iap_run(
        request: Request,
        iap_file: str = _Form("data/iap_packages.json"),
        dry_run: str = _Form(""),
        update_existing: str = _Form(""),
        verbose: str = _Form(""),
):
    profile = request.cookies.get("asc_profile", "")
    task_id = _start_iap_task(
        profile=profile,
        iap_file=iap_file,
        dry_run=bool(dry_run),
        update_existing=bool(update_existing),
        verbose=bool(verbose),
    )
    return {"task_id": task_id}


@router.post("/iap/check")
async def iap_check(request: Request):
    lang = _lang(request)
    profile = request.cookies.get("asc_profile", "")
    try:
        from pathlib import Path
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


@router.post("/iap/review-screenshots/scan")
async def iap_review_screenshots_scan(request: Request):
    from fastapi import HTTPException

    profile = request.cookies.get("asc_profile", "")
    body = await request.body()
    if body.strip():
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid JSON")
    else:
        payload = {}
    iap_file = payload.get("iapFile") if isinstance(payload, dict) else None
    if iap_file is not None and not isinstance(iap_file, str):
        raise HTTPException(status_code=400, detail="iapFile must be a string")
    try:
        return _scan_iap_review_screenshot_targets(profile, iap_file=iap_file)
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


@router.post("/iap/review-screenshots/upload")
async def iap_review_screenshots_upload(request: Request):
    from fastapi import HTTPException

    profile = request.cookies.get("asc_profile", "")
    body = await request.body()
    if body.strip():
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid JSON")
    else:
        payload = {}

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

    task_id = _start_iap_review_screenshots_task(
        profile=profile,
        items=items,
        dry_run=dry_run,
        verbose=verbose,
    )
    return {"task_id": task_id}


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
    lang = _lang(request)
    profile = request.cookies.get("asc_profile", "")
    try:
        config = Config(app_name=profile)
        api, app_id = make_api_from_config(config)
        version = api.get_editable_version(app_id)
        if not version:
            return {
                "ok": False,
                "level": "warning",
                "message": t("api.no_editable_version", lang=lang),
                "detail": {},
            }
        locales = _get_available_locales(api, app_id)
        return {
            "ok": True,
            "level": "success",
            "message": t("api.env_ok_locales", lang=lang, count=len(locales)),
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
    verbose: str = _Form(""),
):
    """Set a URL field directly."""
    profile = request.cookies.get("asc_profile", "")
    task_id = _start_urls_task(
        profile=profile,
        field=field,
        url=url,
        locales=locales,
        dry_run=bool(dry_run),
        verbose=bool(verbose),
    )
    return {"task_id": task_id}


def _start_urls_task(
    *,
    profile: str,
    field: str,
    url: str,
    locales: str = "",
    dry_run: bool = False,
    verbose: bool = False,
) -> str:
    task_id = _task_store.create("urls", profile=profile)
    guard_enforcer = enforce_config_guard

    def run(reporter, cancel_event):
        try:
            config = Config(app_name=profile)
            guard_enforcer(config, interactive=False)
            api, app_id = make_api_from_config(config)
            locale_list = [l.strip() for l in locales.split(",")] if locales else None

            if field == "privacyPolicyUrl":
                from asc.commands.metadata import _update_app_info_field_core
                _update_app_info_field_core(
                    api,
                    app_id,
                    field,
                    field,
                    url,
                    locale_list,
                    dry_run,
                    cancel_event=cancel_event,
                    reporter=reporter,
                )
            else:
                from asc.commands.metadata import _update_version_field_core
                _update_version_field_core(
                    api,
                    app_id,
                    field,
                    field,
                    url,
                    locale_list,
                    dry_run,
                    cancel_event=cancel_event,
                    reporter=reporter,
                )

            if cancel_event.is_set():
                raise ProcessCanceled("urls update canceled")
            result = {"success": True}
            _finish_task(task_id, _TaskStatus.DONE, result)
            return result
        except ProcessCanceled:
            reporter.log("⏹ 用户已终止上传")
            _finish_task(
                task_id,
                _TaskStatus.CANCELED,
                {"success": False, "canceled": True},
            )
            raise
        except Exception as e:
            # Core already called reporter.fail for RuntimeError; avoid duplicate.
            _finish_task(
                task_id,
                _TaskStatus.ERROR,
                {"success": False, "error": str(e)},
            )
            raise

    return start_background_task(
        _task_store,
        kind="urls",
        profile=profile,
        verbose=verbose,
        run=run,
        task_id=task_id,
    )


# ---------- Update API ----------

@router.get("/update/check")
async def update_check(request: Request):
    """Check for updates."""
    from asc.commands.update_cmd import (
        _current_version,
        _is_editable,
        _latest_version_from_github,
        _parse_version,
        _resolve_git_ref_commit,
    )
    from asc.cli import _installed_commit_short

    lang = _lang(request)

    current = _current_version()
    current_commit = _installed_commit_short() or "unknown"
    is_editable = _is_editable()
    latest = _latest_version_from_github()
    if not latest:
        return {
            "ok": False,
            "level": "warning",
            "message": t("api.github_unreachable", lang=lang),
            "detail": {
                "current": current,
                "current_commit": current_commit,
                "is_editable": is_editable,
            },
        }
    latest_commit = (_resolve_git_ref_commit(f"v{latest}") or "unknown")[:7]
    is_latest = _parse_version(latest) <= _parse_version(current)
    latest_label = f"{latest} (commit {latest_commit})"
    if is_latest:
        message = t(
            "api.update_up_to_date",
            lang=lang,
            current=current,
            current_commit=current_commit,
        )
    else:
        message = t(
            "api.update_available",
            lang=lang,
            current=current,
            current_commit=current_commit,
            latest_label=latest_label,
        )
    return {
        "ok": True,
        "level": "success" if is_latest else "info",
        "message": message,
        "detail": {
            "current": current,
            "current_commit": current_commit,
            "latest": latest,
            "latest_commit": latest_commit,
            "is_latest": is_latest,
            "is_editable": is_editable,
        },
    }


@router.get("/update/versions")
async def update_versions(request: Request):
    """List installable release versions."""
    from asc.commands.update_cmd import _all_versions_from_github

    lang = _lang(request)
    versions = _all_versions_from_github()
    if versions is None:
        return {
            "ok": False,
            "level": "warning",
            "message": t("api.versions_unavailable", lang=lang),
            "versions": [],
        }
    return {
        "ok": True,
        "level": "success",
        "message": t("api.versions_found", lang=lang, count=len(versions)),
        "versions": versions,
    }


@router.get("/update/branches")
async def update_branches(request: Request):
    """List installable branches."""
    from asc.commands.update_cmd import _branches_from_github

    lang = _lang(request)
    branches = _branches_from_github()
    if branches is None:
        return {
            "ok": False,
            "level": "warning",
            "message": t("api.branches_unavailable", lang=lang),
            "branches": [],
        }
    return {
        "ok": True,
        "level": "success",
        "message": t("api.branches_found", lang=lang, count=len(branches)),
        "branches": branches,
    }


@router.post("/update/run")
async def update_run(
    version: str = _Form(""),
    branch: str = _Form(""),
    dry_run: str = _Form(""),
    verbose: str = _Form(""),
):
    """Run update."""
    task_id = _start_update_task(
        version=version or None,
        branch=branch or None,
        verbose=bool(verbose),
    )
    return {"task_id": task_id}


def _start_update_task(
    *,
    version: str | None = None,
    branch: str | None = None,
    verbose: bool = False,
) -> str:
    from asc.commands.update_cmd import UpdateError, _update_core
    from asc.web.daemon import schedule_restart

    task_id = _task_store.create("update", profile="system")

    def run(reporter, cancel_event):
        try:
            installed = _update_core(
                version=version or None,
                branch=branch or None,
                yes=True,
                reporter=reporter,
                confirm=False,
            )
            if cancel_event.is_set():
                raise ProcessCanceled("update canceled")
            result: dict = {"success": True, "installed": bool(installed)}
            if installed:
                reporter.log("🔄 即将重启 Web UI 以加载新版本...")
                restart_info = schedule_restart(delay=2.0)
                result["restart"] = restart_info
                result["restarting"] = restart_info.get("status") == "scheduled"
                if result["restarting"]:
                    reporter.log(
                        f"Web UI 将在约 {restart_info.get('delay', 2)} 秒后自动重启"
                        f"（{restart_info.get('url', '')}）"
                    )
                else:
                    reporter.log(
                        f"⚠️  自动重启未安排：{restart_info.get('message', restart_info.get('status'))}"
                    )
            # Flush buffered logs before marking DONE so SSE clients see the full log
            # (including restart notes) before the "done" event.
            reporter.flush()
            _finish_task(task_id, _TaskStatus.DONE, result)
            return result
        except ProcessCanceled:
            reporter.log("⏹ 用户已终止更新")
            reporter.flush()
            _finish_task(
                task_id,
                _TaskStatus.CANCELED,
                {"success": False, "canceled": True},
            )
            raise
        except UpdateError as e:
            # Core already called reporter.fail; do not fail again.
            reporter.flush()
            _finish_task(
                task_id,
                _TaskStatus.ERROR,
                {"success": False, "error": str(e)},
            )
            raise
        except Exception as e:
            reporter.fail(str(e))
            reporter.flush()
            _finish_task(
                task_id,
                _TaskStatus.ERROR,
                {"success": False, "error": str(e)},
            )
            raise

    return start_background_task(
        _task_store,
        kind="update",
        profile="system",
        verbose=verbose,
        run=run,
        task_id=task_id,
    )

@router.get("/settings/llm")
async def get_llm_config(request: Request):
    """Return LLM config metadata without exposing stored API keys."""
    from asc.config import Config
    config = Config()
    configs = {
        name: {
            "base_url": values.get("base_url", ""),
            "model": values.get("model", ""),
            "has_api_key": bool(values.get("api_key")),
        }
        for name, values in config.llm_configs.items()
        if isinstance(values, dict)
    }
    return {
        "configs": configs,
        "default": config.llm_default,
    }


@router.get("/settings/webhooks")
async def get_webhook_config(request: Request):
    """Return webhook notification config without exposing secrets."""
    return notifications.load_public_webhook_config()


@router.post("/settings/webhooks")
async def save_webhook_config(request: Request):
    """Save webhook notification config."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    validation_error = _validate_webhook_config_payload(data)
    if validation_error:
        return JSONResponse({"error": validation_error}, status_code=400)

    try:
        notifications.save_webhook_config(data, preserve_blank_secrets=True)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/settings/webhooks/test")
async def test_webhook_config(request: Request):
    """Send a test webhook notification."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)

    try:
        return {"results": notifications.send_test_notification(provider=data.get("provider"))}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


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
        config.save_llm_config(
            name, base_url, api_key, model, set_default=set_default, preserve_blank_api_key=True
        )
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
