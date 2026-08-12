"""Shared background task runner for Web UI jobs."""

from __future__ import annotations

import atexit
import os
import queue
import sys
import traceback
import threading
from dataclasses import dataclass
from enum import Enum
from threading import Event
from typing import Any, Callable, Optional

from asc.progress import ProcessCanceled
from asc.reporting import TaskReporter, make_web_reporter
from asc.web.tasks import (
    TERMINAL_STATUSES,
    WRITE_OP_APPLYING,
    TaskStatus,
    TaskStore,
    TaskStoreWritePending,
)

SSE_ABSOLUTE_TIMEOUT_SEC = 7200

DEFAULT_MAX_WORKERS = 2
MAX_WORKERS_CAP = 4
TERMINAL_STATUS_CONFIRM_TIMEOUT_SEC = 0.25
TERMINAL_STATUS_SETTLE_TIMEOUT_SEC = 0.20
TERMINAL_RECOVERY_KEY = "_asc_terminal_recovery"

RunFn = Callable[[TaskReporter, Event], Any]


class TaskTerminalError(RuntimeError):
    """Carry a structured terminal error result from a command core."""

    def __init__(self, message: str, result: dict[str, Any]) -> None:
        super().__init__(message)
        self.result = result


class TerminalWriteState(str, Enum):
    """How far the terminal status write got before the caller moved on."""

    COMMITTED = "committed"
    PENDING_COMMIT = "pending_commit"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class TerminalWriteOutcome:
    """Deterministic handoff between finalize and terminal side effects.

    ``COMMITTED``: the desired status is readable from the store.
    ``PENDING_COMMIT``: the writer claimed the op and is committing it. This is
    not success; only recovery-aware side effects may use the durable result hint.
    ``BLOCKED``: the op was skipped or failed, so no side effect may run.
    """

    state: TerminalWriteState
    status: TaskStatus
    detail: str = ""
    recovery_confirmed: bool = False

    @property
    def persisted(self) -> bool:
        return self.state is TerminalWriteState.COMMITTED

    @property
    def blocked(self) -> bool:
        return self.state is TerminalWriteState.BLOCKED

    def __bool__(self) -> bool:
        return self.persisted


def _max_workers_from_env() -> int:
    raw = os.getenv("ASC_WEB_MAX_WORKERS", str(DEFAULT_MAX_WORKERS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_WORKERS
    return max(1, min(value, MAX_WORKERS_CAP))


def _is_terminal(store: TaskStore, task_id: str) -> bool:
    try:
        task = store.get_state(task_id) or store.get(task_id)
    except Exception as exc:  # noqa: BLE001
        print(
            f"⚠️  Task state read failed task_id={task_id} "
            f"operation=get_state path={getattr(store, '_db_path', 'unknown')}: {exc}",
            file=sys.stderr,
        )
        return False
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


def _store_path(store: TaskStore) -> object:
    return getattr(store, "_db_path", "unknown")


def _guarded_flush(
    store: TaskStore,
    reporter: TaskReporter,
    task_id: str,
    *,
    failed: bool | None = None,
) -> bool:
    resolved_failed = bool(
        failed is True or getattr(reporter, "failed", False)
    )
    try:
        if reporter.flush(failed=resolved_failed) is False:
            print(
                f"⚠️  Task reporter flush was not durable task_id={task_id} "
                f"operation=flush path={_store_path(store)}",
                file=sys.stderr,
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        print(
            f"⚠️  Task reporter flush failed task_id={task_id} "
            f"operation=flush path={_store_path(store)}: {exc}",
            file=sys.stderr,
        )
        return False


def _status_value(status: object) -> object:
    return getattr(status, "value", status)


def _result_with_terminal_recovery(
    result: dict[str, Any],
    status: TaskStatus,
) -> dict[str, Any]:
    durable_result = dict(result)
    durable_result[TERMINAL_RECOVERY_KEY] = {
        "version": 1,
        "status": status.value,
    }
    return durable_result


def _read_task_state(store: TaskStore, task_id: str) -> dict[str, Any] | None:
    return store.get_state(task_id) or store.get(task_id)


def _desired_status_is_persisted(
    store: TaskStore,
    task_id: str,
    status: TaskStatus,
) -> bool:
    try:
        current = _read_task_state(store, task_id)
    except Exception as exc:  # noqa: BLE001
        print(
            f"⚠️  Task terminal confirmation failed task_id={task_id} "
            f"operation=get_state path={_store_path(store)}: {exc}",
            file=sys.stderr,
        )
        return False
    return bool(
        current is not None
        and _status_value(current.get("status")) == status.value
    )


def _record_terminal_uncertainty(
    store: TaskStore,
    task_id: str,
    status: TaskStatus,
    result: dict[str, Any],
    error: BaseException,
) -> None:
    uncertain_result = dict(result)
    uncertain_result["terminal_write_uncertainty"] = (
        f"set_status({status.value}) could not be confirmed: {error}"
    )
    try:
        writer = getattr(store, "set_result_if_nonterminal", None)
        if writer is None:
            ok = store.set_result(task_id, uncertain_result)
        else:
            ok = writer(task_id, uncertain_result, wait=False)
        if ok is False:
            raise RuntimeError("TaskStore uncertainty result enqueue returned False")
    except Exception as exc:  # noqa: BLE001
        print(
            f"⚠️  Task terminal uncertainty write failed task_id={task_id} "
            f"operation=set_result_if_nonterminal path={_store_path(store)}: {exc}",
            file=sys.stderr,
        )


def finalize_task(
    store: TaskStore,
    reporter: TaskReporter,
    task_id: str,
    status: TaskStatus,
    result: dict[str, Any],
) -> bool:
    """Publish logs, result and terminal status; True when side effects may run."""
    return bool(finalize_task_outcome(store, reporter, task_id, status, result))


def _resolve_pending_status(
    store: TaskStore,
    task_id: str,
    status: TaskStatus,
    result: dict[str, Any],
    exc: TaskStoreWritePending,
) -> TerminalWriteOutcome:
    """Turn a timed-out status write into a definite committed/pending/blocked state."""
    if _desired_status_is_persisted(store, task_id, status):
        return TerminalWriteOutcome(TerminalWriteState.COMMITTED, status)
    exc.wait(TERMINAL_STATUS_CONFIRM_TIMEOUT_SEC)
    if _desired_status_is_persisted(store, task_id, status):
        return TerminalWriteOutcome(TerminalWriteState.COMMITTED, status)
    if exc.abandon():
        # The writer had not started this op, so it will never be applied.
        _record_terminal_uncertainty(store, task_id, status, result, exc)
        return TerminalWriteOutcome(
            TerminalWriteState.BLOCKED,
            status,
            "writer op abandoned before it was applied",
            recovery_confirmed=True,
        )
    # The writer already claimed the op: wait a bounded window for the commit.
    exc.wait_settled(TERMINAL_STATUS_SETTLE_TIMEOUT_SEC)
    if _desired_status_is_persisted(store, task_id, status):
        return TerminalWriteOutcome(TerminalWriteState.COMMITTED, status)
    if exc.outcome() == WRITE_OP_APPLYING:
        print(
            f"⚠️  Task terminal write still committing task_id={task_id} "
            f"operation=set_status path={_store_path(store)}; "
            "relying on durable recovery",
            file=sys.stderr,
        )
        return TerminalWriteOutcome(
            TerminalWriteState.PENDING_COMMIT,
            status,
            "writer is committing the terminal status",
            recovery_confirmed=True,
        )
    settled_error = exc.op_error() or exc
    _record_terminal_uncertainty(store, task_id, status, result, settled_error)
    return TerminalWriteOutcome(
        TerminalWriteState.BLOCKED,
        status,
        f"writer settled without persisting the status ({exc.outcome()})",
        recovery_confirmed=True,
    )


def finalize_task_outcome(
    store: TaskStore,
    reporter: TaskReporter,
    task_id: str,
    status: TaskStatus,
    result: dict[str, Any],
) -> TerminalWriteOutcome:
    """Publish logs, a non-empty result, then the terminal status."""
    if not result:
        raise ValueError("terminal task result must be non-empty")

    if not _guarded_flush(
        store,
        reporter,
        task_id,
        failed=status == TaskStatus.ERROR,
    ):
        return TerminalWriteOutcome(
            TerminalWriteState.BLOCKED,
            status,
            "terminal log flush was not durable",
        )

    try:
        current = _read_task_state(store, task_id)
    except Exception as exc:  # noqa: BLE001
        print(
            f"⚠️  Task terminal state read failed task_id={task_id} "
            f"operation=get_state path={_store_path(store)}: {exc}",
            file=sys.stderr,
        )
        current = None
    if current is not None and _status_value(current.get("status")) in {
        terminal.value for terminal in TERMINAL_STATUSES
    }:
        if not current.get("result"):
            try:
                if store.set_result(task_id, result) is False:
                    raise RuntimeError("TaskStore set_result returned False")
            except Exception as exc:  # noqa: BLE001
                print(
                    f"⚠️  Task terminal result repair failed task_id={task_id} "
                    f"operation=set_result path={_store_path(store)}: {exc}",
                    file=sys.stderr,
                )
                return TerminalWriteOutcome(
                    TerminalWriteState.BLOCKED,
                    status,
                    "terminal result repair failed",
                )
        if _status_value(current.get("status")) == status.value:
            return TerminalWriteOutcome(TerminalWriteState.COMMITTED, status)
        return TerminalWriteOutcome(
            TerminalWriteState.BLOCKED,
            status,
            f"another terminal status already won: {_status_value(current.get('status'))}",
        )

    durable_result = _result_with_terminal_recovery(result, status)
    try:
        result_writer = getattr(store, "set_result_if_nonterminal", None)
        if result_writer is None:
            result_written = store.set_result(task_id, durable_result)
        else:
            result_written = result_writer(task_id, durable_result, wait=True)
        if result_written is False:
            raise RuntimeError("TaskStore set_result returned False")
    except Exception as exc:  # noqa: BLE001
        print(
            f"⚠️  Task terminal write failed task_id={task_id} "
            f"operation=set_result path={_store_path(store)}: {exc}",
            file=sys.stderr,
        )
        return TerminalWriteOutcome(
            TerminalWriteState.BLOCKED,
            status,
            f"terminal result write failed: {exc}",
        )

    try:
        if store.set_status(task_id, status) is False:
            error = RuntimeError("TaskStore set_status returned False")
            if _desired_status_is_persisted(store, task_id, status):
                return TerminalWriteOutcome(TerminalWriteState.COMMITTED, status)
            _record_terminal_uncertainty(
                store, task_id, status, durable_result, error
            )
            return TerminalWriteOutcome(
                TerminalWriteState.BLOCKED,
                status,
                "terminal status write was rejected",
                recovery_confirmed=True,
            )
        return TerminalWriteOutcome(TerminalWriteState.COMMITTED, status)
    except TaskStoreWritePending as exc:
        print(
            f"⚠️  Task terminal write pending task_id={task_id} "
            f"operation=set_status path={_store_path(store)}: {exc}",
            file=sys.stderr,
        )
        return _resolve_pending_status(
            store, task_id, status, durable_result, exc
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"⚠️  Task terminal write failed task_id={task_id} "
            f"operation=set_status path={_store_path(store)}: {exc}",
            file=sys.stderr,
        )
        if _desired_status_is_persisted(store, task_id, status):
            return TerminalWriteOutcome(TerminalWriteState.COMMITTED, status)
        _record_terminal_uncertainty(
            store, task_id, status, durable_result, exc
        )
        return TerminalWriteOutcome(
            TerminalWriteState.BLOCKED,
            status,
            f"terminal status write failed: {exc}",
            recovery_confirmed=True,
        )


def _notify_task_finished(
    store: TaskStore,
    reporter: TaskReporter,
    task_id: str,
) -> str | None:
    try:
        from asc.web import notifications

        notifications.notify_task_finished(task_id, task_store=store)
        return None
    except Exception as exc:  # noqa: BLE001
        reporter.log(f"群通知处理失败：{exc.__class__.__name__}", level="error")
        try:
            current = store.get_state(task_id) or store.get(task_id) or {}
            current_result = current.get("result")
            if isinstance(current_result, dict) and current_result:
                merged = dict(current_result)
                merged["notification_error"] = str(exc)
                if store.set_result(task_id, merged) is False:
                    raise RuntimeError("TaskStore set_result returned False")
        except Exception as store_exc:  # noqa: BLE001
            print(
                f"⚠️  Task notification result write failed task_id={task_id} "
                f"operation=set_result path={_store_path(store)}: {store_exc}",
                file=sys.stderr,
            )
        _guarded_flush(store, reporter, task_id, failed=True)
        return str(exc)


def _execute_task(
    store: TaskStore,
    task_id: str,
    task_kind: str,
    run: RunFn,
    *,
    verbose: bool,
) -> None:
    """Run one task to completion (cooperative cancel; no forced kill)."""
    reporter = make_web_reporter(store, task_id, task_kind, verbose=verbose)
    retry_terminal: tuple[TaskStatus, dict[str, Any]] | None = None

    def finish(status: TaskStatus, payload: dict[str, Any]) -> bool:
        nonlocal retry_terminal
        outcome = finalize_task_outcome(
            store,
            reporter,
            task_id,
            status,
            payload,
        )
        if outcome.persisted:
            retry_terminal = None
            _notify_task_finished(store, reporter, task_id)
            return True
        if outcome.blocked and not outcome.recovery_confirmed:
            retry_terminal = (status, payload)
        return False

    # Cancel (or other terminal finish) may win the race before the worker starts.
    try:
        if _is_terminal(store, task_id):
            return
        if _cancel_requested(store, task_id):
            finish(
                TaskStatus.CANCELED,
                {"success": False, "canceled": True},
            )
            return
        try:
            store.set_status(task_id, TaskStatus.RUNNING)
        except Exception as exc:  # noqa: BLE001
            print(
                f"⚠️  Failed to mark task {task_id} running "
                f"path={_store_path(store)}: {exc}",
                file=sys.stderr,
            )
        cancel_event = store.cancel_event(task_id)
        try:
            result = run(reporter, cancel_event)
            if _is_terminal(store, task_id):
                return
            if cancel_event.is_set():
                finish(
                    TaskStatus.CANCELED,
                    {"success": False, "canceled": True},
                )
                return
            payload = result if isinstance(result, dict) and result else {"success": True}
            finish(TaskStatus.DONE, payload)
        except ProcessCanceled:
            if _is_terminal(store, task_id):
                return
            finish(
                TaskStatus.CANCELED,
                {"success": False, "canceled": True},
            )
        except Exception as exc:
            tb = traceback.format_exc()
            if not reporter.failed:
                reporter.fail(str(exc), detail=tb)
            else:
                # Core already logged a friendly fail; still attach traceback for the drawer.
                reporter.log(tb, level="error")
            if _is_terminal(store, task_id):
                return
            payload = (
                exc.result
                if isinstance(exc, TaskTerminalError) and exc.result
                else {"success": False, "error": str(exc)}
            )
            finish(TaskStatus.ERROR, payload)
    finally:
        if retry_terminal is not None and not _is_terminal(store, task_id):
            status, payload = retry_terminal
            finish(status, payload)
        _guarded_flush(store, reporter, task_id)


class TaskScheduler:
    """Bounded worker pool: overflow stays PENDING until a worker is free."""

    def __init__(self, store: TaskStore, *, max_workers: Optional[int] = None) -> None:
        self._store = store
        if max_workers is None:
            self._max_workers = _max_workers_from_env()
        else:
            self._max_workers = max(1, min(int(max_workers), MAX_WORKERS_CAP))
        self._queue: queue.Queue[Optional[tuple[str, str, RunFn, bool]]] = queue.Queue()
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
        del profile  # retained for call-site clarity / future affinity
        if self._shutdown.is_set():
            print(f"⚠️  Scheduler shut down; not enqueueing task {task_id}", file=sys.stderr)
            return
        if _is_terminal(self._store, task_id):
            return
        self._queue.put((task_id, kind, run, verbose))

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
            task_id, kind, run, verbose = item
            try:
                _execute_task(self._store, task_id, kind, run, verbose=verbose)
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