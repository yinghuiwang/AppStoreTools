"""Shared background task runner for Web UI jobs."""

from __future__ import annotations

import threading
from threading import Event
from typing import Any, Callable

from asc.progress import ProcessCanceled
from asc.reporting import TaskReporter, make_web_reporter
from asc.web.tasks import TERMINAL_STATUSES, TaskStatus, TaskStore

SSE_ABSOLUTE_TIMEOUT_SEC = 7200


def _is_terminal(store: TaskStore, task_id: str) -> bool:
    task = store.get_state(task_id) or store.get(task_id)
    if task is None:
        return False
    status = task.get("status")
    if status in TERMINAL_STATUSES:
        return True
    value = getattr(status, "value", status)
    return value in {s.value for s in TERMINAL_STATUSES}


def start_background_task(
    store: TaskStore,
    *,
    kind: str,
    profile: str,
    verbose: bool,
    run: Callable[[TaskReporter, Event], Any],
    task_id: str | None = None,
) -> str:
    """Create a task and run ``run(reporter, cancel_event)`` on a daemon thread.

    If ``task_id`` is provided, reuse that existing task row (caller may close
    over the id before the worker starts).
    """
    if task_id is None:
        task_id = store.create(kind, profile=profile)

    def _worker() -> None:
        # Cancel (or other terminal finish) may win the race before the worker starts.
        if _is_terminal(store, task_id):
            return
        store.set_status(task_id, TaskStatus.RUNNING)
        reporter = make_web_reporter(store, task_id, verbose=verbose)
        cancel_event = store.cancel_event(task_id)
        try:
            result = run(reporter, cancel_event)
            if _is_terminal(store, task_id):
                return
            if cancel_event.is_set():
                store.set_result(task_id, {"success": False, "canceled": True})
                store.set_status(task_id, TaskStatus.CANCELED)
                return
            if isinstance(result, dict):
                store.set_result(task_id, result)
            store.set_status(task_id, TaskStatus.DONE)
        except ProcessCanceled:
            if _is_terminal(store, task_id):
                return
            store.set_status(task_id, TaskStatus.CANCELED)
        except Exception as exc:
            if not reporter.failed:
                reporter.fail(str(exc))
            if _is_terminal(store, task_id):
                return
            store.set_status(task_id, TaskStatus.ERROR)
        finally:
            reporter.flush()

    threading.Thread(target=_worker, daemon=True).start()
    return task_id
