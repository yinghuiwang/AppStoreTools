"""Local review-schedule API."""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from asc import schedule
from asc.schedule import (
    WATCH_APP_STORE,
    ScheduleCorruptError,
    ScheduleError,
    ScheduleLockTimeout,
    ScheduleNotFound,
    parse_hhmm,
    require_watch,
)
from asc.web.i18n import t

router = APIRouter()


def heartbeat_backend():
    from asc.schedule import SystemHeartbeatBackend

    return SystemHeartbeatBackend()


def asc_executable():
    from asc.schedule import resolve_asc_executable

    return resolve_asc_executable()


def _lang(request: Request) -> str:
    return getattr(request.state, "lang", None) or "en"


def _error(request: Request, key: str, status: int, **params: object) -> JSONResponse:
    return JSONResponse({"error": t(key, _lang(request), **params)}, status_code=status)


def _schedule_error(request: Request, exc: ScheduleError) -> JSONResponse:
    if isinstance(exc, ScheduleNotFound):
        status = 404
    elif isinstance(exc, ScheduleLockTimeout):
        status = 409
    else:
        status = 400
    return _error(request, f"schedules.err.{exc.code}", status, **exc.params)


async def _read_object(request: Request):
    try:
        body = await request.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    return body


def _period_fields(body: dict, kind: str):
    has_interval = "interval_hours" in body
    has_weekdays = "weekdays" in body
    if kind == "daily":
        if has_interval or has_weekdays:
            raise ScheduleError("kind_fields")
        return None, None
    if kind == "interval":
        if has_weekdays or not has_interval:
            raise ScheduleError("kind_fields")
        hours = body.get("interval_hours")
        if isinstance(hours, bool) or not isinstance(hours, int) or hours < 1:
            raise ScheduleError("every")
        return hours, None
    if kind == "weekly":
        if has_interval or not has_weekdays:
            raise ScheduleError("kind_fields")
        days = body.get("weekdays")
        if (
            not isinstance(days, list)
            or not days
            or any(isinstance(item, bool) or not isinstance(item, int) for item in days)
        ):
            raise ScheduleError("weekdays")
        return None, days
    raise ScheduleError("kind")


def _schedule_fields(body: dict, *, creating: bool):
    if "enabled" in body and not isinstance(body.get("enabled"), bool):
        raise ScheduleError("enabled")
    if creating:
        enabled = True if "enabled" not in body else body["enabled"]
    elif not isinstance(body.get("enabled"), bool):
        raise ScheduleError("enabled")
    else:
        enabled = body["enabled"]
    profile = body.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        raise ScheduleError("profile", name="" if profile is None else str(profile))
    kind = body.get("kind")
    if kind not in ("daily", "interval", "weekly"):
        raise ScheduleError("kind")
    when = body.get("time")
    if not isinstance(when, str):
        raise ScheduleError("time")
    parse_hhmm(when)
    interval_hours, weekdays = _period_fields(body, kind)
    return profile, kind, when, enabled, interval_hours, weekdays


def _requested_watch(body: dict):
    if "watch" not in body:
        return None
    value = body.get("watch")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return require_watch(value)


def _requested_timezone(body: dict):
    if "timezone" not in body:
        return None
    value = body.get("timezone")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return schedule.require_timezone_name(value)


def _task_json(task) -> dict:
    payload = {
        "id": task.id,
        "profile": task.profile,
        "enabled": task.enabled,
        "kind": task.kind,
        "watch": getattr(task, "watch", None) or WATCH_APP_STORE,
        "time": task.time,
        "timezone": task.timezone,
        "next_run_at": task.next_run_at,
        "last_run_at": task.last_run_at,
        "last_error": task.last_error,
        "last_result": task.last_result,
    }
    if task.kind == "interval":
        payload["interval_hours"] = task.interval_hours
    elif task.kind == "weekly":
        payload["weekdays"] = list(task.weekdays or [])
    return payload


def _load_state():
    path = schedule.default_schedule_path()
    tasks = schedule.list_tasks(schedule_path=path)
    heartbeat = schedule.heartbeat_status(backend=heartbeat_backend())
    return tasks, heartbeat


@router.get("/schedules")
async def list_schedules(request: Request):
    try:
        tasks, heartbeat = await asyncio.to_thread(_load_state)
    except ScheduleCorruptError as exc:
        return _schedule_error(request, exc)
    except ScheduleError as exc:
        return _schedule_error(request, exc)
    return {
        "tasks": [_task_json(task) for task in tasks],
        "heartbeat": heartbeat,
    }


@router.get("/schedules/timezones")
async def list_schedule_timezones():
    names = await asyncio.to_thread(schedule.list_timezones)
    return {"timezones": names}


@router.post("/schedules")
async def create_schedule(request: Request):
    body = await _read_object(request)
    if body is None:
        return _error(request, "schedules.err.json", 400)
    try:
        profile, kind, when, enabled, interval_hours, weekdays = _schedule_fields(body, creating=True)
        timezone_name = _requested_timezone(body)
        watch = _requested_watch(body) or WATCH_APP_STORE
    except ScheduleError as exc:
        return _schedule_error(request, exc)

    def _add():
        task, _installed = schedule.add_task(
            profile=profile,
            kind=kind,
            time=when,
            interval_hours=interval_hours,
            weekdays=weekdays,
            enabled=enabled,
            watch=watch,
            timezone=timezone_name,
            schedule_path=schedule.default_schedule_path(),
            now=datetime.now().astimezone(),
            profile_lookup=schedule.default_profile_lookup,
            backend=heartbeat_backend(),
            asc_path=asc_executable(),
        )
        return task

    try:
        task = await asyncio.to_thread(_add)
    except ScheduleError as exc:
        return _schedule_error(request, exc)
    return _task_json(task)


@router.put("/schedules/{task_id}")
async def update_schedule(task_id: str, request: Request):
    body = await _read_object(request)
    if body is None:
        return _error(request, "schedules.err.json", 400)
    try:
        profile, kind, when, enabled, interval_hours, weekdays = _schedule_fields(body, creating=False)
        watch = _requested_watch(body)
    except ScheduleError as exc:
        return _schedule_error(request, exc)

    def _update():
        return schedule.update_task(
            task_id,
            profile=profile,
            kind=kind,
            time=when,
            enabled=enabled,
            interval_hours=interval_hours,
            weekdays=weekdays,
            watch=watch,
            schedule_path=schedule.default_schedule_path(),
            now=datetime.now().astimezone(),
            profile_lookup=schedule.default_profile_lookup,
        )

    try:
        task = await asyncio.to_thread(_update)
    except ScheduleError as exc:
        return _schedule_error(request, exc)
    return _task_json(task)


@router.delete("/schedules/{task_id}")
async def delete_schedule(task_id: str, request: Request):
    def _delete():
        schedule.remove_task(task_id, schedule_path=schedule.default_schedule_path())

    try:
        await asyncio.to_thread(_delete)
    except ScheduleError as exc:
        return _schedule_error(request, exc)
    return {"ok": True}


@router.post("/schedules/{task_id}/run")
async def run_schedule(task_id: str, request: Request):
    def _run():
        return schedule.run_task(task_id, schedule_path=schedule.default_schedule_path())

    try:
        task = await asyncio.to_thread(_run)
    except ScheduleError as exc:
        return _schedule_error(request, exc)
    return _task_json(task)


@router.post("/schedules/heartbeat/install")
async def install_schedule_heartbeat(request: Request):
    def _install():
        schedule.install_heartbeat(asc_path=asc_executable(), backend=heartbeat_backend())
        return schedule.heartbeat_status(backend=heartbeat_backend())

    try:
        heartbeat = await asyncio.to_thread(_install)
    except ScheduleError as exc:
        return _schedule_error(request, exc)
    return {"heartbeat": heartbeat}


@router.post("/schedules/heartbeat/uninstall")
async def uninstall_schedule_heartbeat(request: Request):
    def _uninstall():
        removed = schedule.uninstall_heartbeat(backend=heartbeat_backend())
        return removed, schedule.heartbeat_status(backend=heartbeat_backend())

    try:
        removed, heartbeat = await asyncio.to_thread(_uninstall)
    except ScheduleError as exc:
        return _schedule_error(request, exc)
    return {"removed": removed, "heartbeat": heartbeat}
