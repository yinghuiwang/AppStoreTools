"""Shared background task runner for Web UI jobs."""

from __future__ import annotations

import atexit
import os
import queue
import sys
import traceback
import threading
from threading import Event
from typing import Any, Callable, Optional

from asc.progress import ProcessCanceled
from asc.reporting import TaskReporter, make_web_reporter
from asc.web.tasks import TERMINAL_STATUSES, TaskStatus, TaskStore

SSE_ABSOLUTE_TIMEOUT_SEC = 7200

DEFAULT_MAX_WORKERS = 2
MAX_WORKERS_CAP = 4

RunFn = Callable[[TaskReporter, Event], Any]


def _max_workers_from_env() -> int:
    raw = os.getenv("ASC_WEB_MAX_WORKERS", str(DEFAULT_MAX_WORKERS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_WORKERS
    return max(1, min(value, MAX_WORKERS_CAP))


def _is_terminal(store: TaskStore, task_id: str) -> bool:
    task = store.get_state(task_id) or store.get(task_id)
    if task is None:
        return False
    status = task.get("status")
    if status in TERMINAL_STATUSES:
        return True
    value = getattr(status, "value", status)
    return value in {s.value for s in TERMINAL_STATUSES}


def _cancel_requested(store: TaskStore, task_id: str) -> bool:
    try:
        return bool(store.is_cancel_requested(task_id))
    except Exception:  # noqa: BLE001
        return False


def _execute_task(
    store: TaskStore,
    task_id: str,
    run: RunFn,
    *,
    verbose: bool,
) -> None:
    """Run one task to completion (cooperative cancel; no forced kill)."""
    # Cancel (or other terminal finish) may win the race before the worker starts.
    if _is_terminal(store, task_id):
        return
    if _cancel_requested(store, task_id):
        try:
            store.set_result(task_id, {"success": False, "canceled": True})
            store.set_status(task_id, TaskStatus.CANCELED)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  Failed to mark pending task {task_id} canceled: {exc}", file=sys.stderr)
        return
    try:
        store.set_status(task_id, TaskStatus.RUNNING)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  Failed to mark task {task_id} running: {exc}", file=sys.stderr)
    reporter = make_web_reporter(store, task_id, verbose=verbose)
    cancel_event = store.cancel_event(task_id)
    try:
        result = run(reporter, cancel_event)
        # Flush before terminal status so status pollers see durable logs.
        reporter.flush()
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
        try:
            reporter.flush()
        except Exception:  # noqa: BLE001
            pass
        if _is_terminal(store, task_id):
            return
        try:
            store.set_status(task_id, TaskStatus.CANCELED)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  Failed to mark task {task_id} canceled: {exc}", file=sys.stderr)
    except Exception as exc:
        tb = traceback.format_exc()
        if not reporter.failed:
            reporter.fail(str(exc), detail=tb)
        else:
            # Core already logged a friendly fail; still attach traceback for the drawer.
            reporter.log(tb, level="error")
        try:
            reporter.flush()
        except Exception:  # noqa: BLE001
            pass
        if _is_terminal(store, task_id):
            return
        try:
            store.set_status(task_id, TaskStatus.ERROR)
        except Exception as status_exc:  # noqa: BLE001
            print(
                f"⚠️  Failed to mark task {task_id} error after {exc}: {status_exc}",
                file=sys.stderr,
            )
    finally:
        try:
            reporter.flush()
        except Exception as flush_exc:  # noqa: BLE001
            print(f"⚠️  Task reporter flush failed: {flush_exc}", file=sys.stderr)


class TaskScheduler:
    """Bounded worker pool: overflow stays PENDING until a worker is free."""

    def __init__(self, store: TaskStore, *, max_workers: Optional[int] = None) -> None:
        self._store = store
        if max_workers is None:
            self._max_workers = _max_workers_from_env()
        else:
            self._max_workers = max(1, min(int(max_workers), MAX_WORKERS_CAP))
        self._queue: queue.Queue[Optional[tuple[str, RunFn, bool]]] = queue.Queue()
        self._shutdown = threading.Event()
        self._workers: list[threading.Thread] = []
        for i in range(self._max_workers):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"asc-task-worker-{i}",
                daemon=True,
            )
            thread.start()
            self._workers.append(thread)

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def submit(
        self,
        task_id: str,
        run: RunFn,
        *,
        kind: str,
        profile: str,
        verbose: bool,
    ) -> None:
        """Enqueue a task; status stays PENDING until a worker picks it up."""
        del kind, profile  # retained for call-site clarity / future affinity
        if self._shutdown.is_set():
            print(f"⚠️  Scheduler shut down; not enqueueing task {task_id}", file=sys.stderr)
            return
        if _is_terminal(self._store, task_id):
            return
        self._queue.put((task_id, run, verbose))

    def _worker_loop(self) -> None:
        while True:
            if self._shutdown.is_set() and self._queue.empty():
                break
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                if self._shutdown.is_set():
                    break
                continue
            if item is None:
                self._queue.task_done()
                break
            task_id, run, verbose = item
            try:
                _execute_task(self._store, task_id, run, verbose=verbose)
            finally:
                self._queue.task_done()

    def shutdown(self, *, wait: bool = True, timeout: float = 30.0) -> None:
        """Stop accepting work; optionally wait for in-flight tasks to finish."""
        self._shutdown.set()
        for _ in self._workers:
            self._queue.put(None)
        if not wait:
            return
        deadline = timeout
        per = max(0.1, deadline / max(len(self._workers), 1))
        for thread in self._workers:
            thread.join(timeout=per)


_scheduler_lock = threading.Lock()
_schedulers: dict[int, TaskScheduler] = {}


def get_scheduler(store: Optional[TaskStore] = None) -> TaskScheduler:
    """Return the process-level scheduler for ``store`` (default: global task_store)."""
    if store is None:
        from asc.web.tasks import task_store as default_store

        store = default_store
    key = id(store)
    with _scheduler_lock:
        existing = _schedulers.get(key)
        if existing is not None:
            return existing
        scheduler = TaskScheduler(store)
        _schedulers[key] = scheduler
        return scheduler


def shutdown_scheduler(
    store: Optional[TaskStore] = None,
    *,
    wait: bool = True,
    timeout: float = 30.0,
) -> None:
    """Shut down the scheduler bound to ``store`` (if any)."""
    if store is None:
        from asc.web.tasks import task_store as default_store

        store = default_store
    key = id(store)
    with _scheduler_lock:
        scheduler = _schedulers.pop(key, None)
    if scheduler is not None:
        scheduler.shutdown(wait=wait, timeout=timeout)


def start_background_task(
    store: TaskStore,
    *,
    kind: str,
    profile: str,
    verbose: bool,
    run: RunFn,
    task_id: Optional[str] = None,
    scheduler: Optional[TaskScheduler] = None,
) -> str:
    """Create a task (if needed) and submit it to the bounded worker pool.

    If ``task_id`` is provided, reuse that existing task row (caller may close
    over the id before the worker starts). Status remains PENDING until a
    worker is free, then becomes RUNNING.
    """
    if task_id is None:
        task_id = store.create(kind, profile=profile)

    pool = scheduler if scheduler is not None else get_scheduler(store)
    pool.submit(task_id, run, kind=kind, profile=profile, verbose=verbose)
    return task_id


# LIFO atexit: register after TaskStore so scheduler drains before writer close.
atexit.register(lambda: shutdown_scheduler(wait=True, timeout=5.0))