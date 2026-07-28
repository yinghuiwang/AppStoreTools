"""Pure dashboard filtering and efficiency metric calculation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional


MANUAL_BASELINE_MINUTES = {
    "metadata": 30,
    "build": 45,
    "whats-new": 10,
    "iap": 25,
    "iap-review-screenshots": 20,
    "urls": 8,
    "update": 5,
}

TERMINAL_STATUSES = {"done", "error", "canceled"}
FAILED_STATUSES = {"error", "canceled"}
RUNNING_STATUSES = {"pending", "running"}


def _status_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _normalize_datetime(value: datetime) -> datetime:
    """Treat naive task timestamps as server-local; normalize aware values to UTC."""
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _created_at(task: dict[str, Any]) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(task.get("created_at", "")))
    except ValueError:
        return None
    return _normalize_datetime(parsed)


def _duration_seconds(value: Any) -> int:
    try:
        return max(0, int(value))
    except (OverflowError, TypeError, ValueError):
        return 0


def _filter_tasks(
    tasks: Iterable[dict[str, Any]],
    *,
    cutoff: datetime,
    profile: str,
    kind: str,
    status: str,
) -> list[dict[str, Any]]:
    filtered = []
    normalized_status = _status_value(status) if status else ""
    for source in tasks:
        task = dict(source)
        created = _created_at(task)
        task_status = _status_value(task.get("status"))
        if created is None or created < cutoff:
            continue
        if profile and task.get("profile") != profile:
            continue
        if kind and task.get("kind") != kind:
            continue
        if normalized_status and task_status != normalized_status:
            continue
        task["status"] = task_status
        filtered.append(task)
    return filtered


def _calculate_metrics(tasks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    saved_seconds = 0
    failed_seconds = 0
    terminal_count = 0
    success_count = 0
    running_count = 0

    for task in tasks:
        task_status = task["status"]
        duration = _duration_seconds(task.get("duration_seconds", 0))
        if task_status in RUNNING_STATUSES:
            running_count += 1
        if task_status in TERMINAL_STATUSES:
            terminal_count += 1
        if task_status == "done":
            success_count += 1
            baseline_seconds = MANUAL_BASELINE_MINUTES.get(task.get("kind"), 0) * 60
            saved_seconds += max(baseline_seconds - duration, 0)
        elif task_status in FAILED_STATUSES:
            failed_seconds += duration

    return {
        "saved_seconds": saved_seconds,
        "success_rate": round(success_count / terminal_count * 100, 1) if terminal_count else None,
        "failed_seconds": failed_seconds,
        "running_count": running_count,
        "completed_count": terminal_count,
    }


def build_dashboard_summary(
    tasks: Iterable[dict[str, Any]],
    *,
    days: int,
    profile: str = "",
    kind: str = "",
    status: str = "",
    now: Optional[datetime] = None,
    task_limit: int = 20,
) -> dict[str, Any]:
    """Return filtered task metadata and aggregate dashboard metrics."""
    current = _normalize_datetime(now or datetime.now())
    scoped = _filter_tasks(
        tasks,
        cutoff=current - timedelta(days=days),
        profile=profile,
        kind=kind,
        status="",
    )
    normalized_status = _status_value(status) if status else ""
    filtered = [
        task for task in scoped
        if not normalized_status or task["status"] == normalized_status
    ]
    normalized_limit = max(1, min(task_limit, 100))
    metrics = _calculate_metrics(filtered)
    metrics["active_count"] = sum(
        task["status"] in RUNNING_STATUSES
        for task in scoped
    )
    return {
        "metrics": metrics,
        "tasks": filtered[:normalized_limit],
        "baseline_minutes": dict(MANUAL_BASELINE_MINUTES),
        "range_days": days,
    }
