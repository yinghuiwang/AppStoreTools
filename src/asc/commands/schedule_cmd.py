"""CLI commands for local iOS review schedules."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import typer

from asc import schedule
from asc.i18n import HELP, t
from asc.schedule import (
    ScheduleError,
    SystemHeartbeatBackend,
    parse_timestamp,
    parse_weekdays,
    resolve_asc_executable,
    user_message,
)

schedule_app = typer.Typer(help=t(HELP["cmd_schedule"]), no_args_is_help=True)


def _fail(exc: ScheduleError) -> None:
    typer.echo(user_message(exc.code, **exc.params), err=True)
    raise typer.Exit(1)


def cycle_label(task) -> str:
    if task.kind == "daily":
        return f"daily {task.time}"
    if task.kind == "interval":
        return f"every {task.interval_hours}h {task.time}"
    days = ",".join(str(day) for day in task.weekdays or [])
    return f"weekly {days} {task.time}"


def _next_label(task) -> str:
    moment = parse_timestamp(task.next_run_at).astimezone(ZoneInfo(task.timezone))
    moment = moment.replace(microsecond=0)
    return f"{moment.strftime('%Y-%m-%d %H:%M')} {task.timezone}"


def _choose_kind(daily: bool, every: Optional[int], weekly: Optional[str]):
    selected = sum((bool(daily), every is not None, weekly is not None))
    if selected != 1:
        raise ScheduleError("kind")
    if daily:
        return "daily", None, None
    if every is not None:
        if every < 1:
            raise ScheduleError("every")
        return "interval", every, None
    return "weekly", None, parse_weekdays(weekly or "")


@schedule_app.command("add")
def cmd_add(
    app_name: str = typer.Option(..., "--app"),
    daily: bool = typer.Option(False, "--daily"),
    every: Optional[int] = typer.Option(None, "--every"),
    weekly: Optional[str] = typer.Option(None, "--weekly"),
    time: str = typer.Option(..., "--time"),
) -> None:
    try:
        kind, interval_hours, weekdays = _choose_kind(daily, every, weekly)
        created, installed_now = schedule.add_task(
            profile=app_name,
            kind=kind,
            time=time,
            interval_hours=interval_hours,
            weekdays=weekdays,
            schedule_path=schedule.default_schedule_path(),
            now=datetime.now().astimezone(),
            profile_lookup=schedule.default_profile_lookup,
            backend=SystemHeartbeatBackend(),
            asc_path=resolve_asc_executable(),
        )
    except ScheduleError as exc:
        _fail(exc)
    typer.echo(f"{created.id} {created.next_run_at}")
    if installed_now:
        typer.echo(user_message("heartbeat_installed"))


@schedule_app.command("list")
def cmd_list() -> None:
    try:
        tasks = schedule.list_tasks(schedule_path=schedule.default_schedule_path())
    except ScheduleError as exc:
        _fail(exc)
    if not tasks:
        typer.echo(user_message("empty"))
        return
    header = [
        user_message("col_id"),
        user_message("col_app"),
        user_message("col_cycle"),
        user_message("col_next"),
        user_message("col_last"),
        user_message("col_enabled"),
    ]
    typer.echo("  ".join(header))
    for task in tasks:
        state = user_message("state_enabled" if task.enabled else "state_disabled")
        typer.echo(
            "  ".join(
                [
                    task.id,
                    task.profile,
                    cycle_label(task),
                    _next_label(task),
                    task.last_result or "-",
                    state,
                ]
            )
        )


@schedule_app.command("enable")
def cmd_enable(task_id: str = typer.Argument(...)) -> None:
    try:
        schedule.set_enabled(task_id, True, schedule_path=schedule.default_schedule_path())
    except ScheduleError as exc:
        _fail(exc)


@schedule_app.command("disable")
def cmd_disable(task_id: str = typer.Argument(...)) -> None:
    try:
        schedule.set_enabled(task_id, False, schedule_path=schedule.default_schedule_path())
    except ScheduleError as exc:
        _fail(exc)


@schedule_app.command("remove")
def cmd_remove(task_id: str = typer.Argument(...)) -> None:
    try:
        schedule.remove_task(task_id, schedule_path=schedule.default_schedule_path())
    except ScheduleError as exc:
        _fail(exc)


@schedule_app.command("install")
def cmd_install() -> None:
    try:
        asc_path = resolve_asc_executable()
        schedule.install_heartbeat(asc_path=asc_path, backend=SystemHeartbeatBackend())
    except ScheduleError as exc:
        _fail(exc)
    typer.echo(user_message("heartbeat_installed"))


@schedule_app.command("uninstall")
def cmd_uninstall() -> None:
    try:
        removed = schedule.uninstall_heartbeat(backend=SystemHeartbeatBackend())
    except ScheduleError as exc:
        _fail(exc)
    if not removed:
        typer.echo(user_message("heartbeat_absent"))


@schedule_app.command("tick")
def cmd_tick() -> None:
    try:
        code = schedule.tick(schedule_path=schedule.default_schedule_path())
    except ScheduleError as exc:
        _fail(exc)
    if code:
        raise typer.Exit(code)


@schedule_app.command("run")
def cmd_run(task_id: str = typer.Argument(...)) -> None:
    try:
        task = schedule.run_task(task_id, schedule_path=schedule.default_schedule_path())
    except ScheduleError as exc:
        _fail(exc)
    status = "error" if task.last_error else "ok"
    typer.echo(f"{task.id} {task.profile} {status}")
    if task.last_error:
        raise typer.Exit(1)
