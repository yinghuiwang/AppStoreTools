"""Task state store for Web UI background jobs."""
from __future__ import annotations

import atexit
import json
import os
import queue
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable, Iterator, Optional, TypedDict


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELED = "canceled"


TASK_KIND_LABELS = {
    "metadata": "元数据上传",
    "build": "构建上传",
    "whats-new": "更新说明上传",
    "whats-new-translate": "更新说明翻译",
    "iap": "内购上传",
    "iap-compare": "内购商店核对",
    "iap-review-screenshots": "IAP 审核截图上传",
    "urls": "URL 更新",
    "update": "工具更新",
    "listing-pull-screenshots": "拉取截图",
    "listing-compare": "商品页商店核对",
}


TASK_KIND_RETRY_PATHS = {
    "metadata": "/metadata",
    "build": "/build",
    "whats-new": "/whats-new",
    "whats-new-translate": "/whats-new",
    "iap": "/iap",
    "iap-compare": "/iap",
    "iap-review-screenshots": "/iap",
    "urls": "/urls",
    "update": "/update",
    "listing-pull-screenshots": "/listing",
    "listing-compare": "/listing",
}


TERMINAL_STATUSES = {TaskStatus.DONE, TaskStatus.ERROR, TaskStatus.CANCELED}

DEFAULT_TASK_LOG_LIMIT = 2000


class StreamSnapshot(TypedDict):
    task: dict[str, Any]
    logs: list[dict[str, Any]]


def _task_log_limit() -> int:
    """Return per-task log row cap (ASC_WEB_TASK_LOG_LIMIT, default 2000)."""
    raw = os.getenv("ASC_WEB_TASK_LOG_LIMIT", str(DEFAULT_TASK_LOG_LIMIT))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TASK_LOG_LIMIT
    return max(1, value)


WRITE_OP_PENDING = "pending"
WRITE_OP_APPLYING = "applying"
WRITE_OP_APPLIED = "applied"
WRITE_OP_REJECTED = "rejected"
WRITE_OP_SKIPPED = "skipped"
WRITE_OP_ERROR = "error"


@dataclass
class _WriteOp:
    kind: str
    task_id: Optional[str] = None
    payload: dict = field(default_factory=dict)
    done: Optional[Event] = None
    error: list = field(default_factory=list)
    critical: bool = False
    result_box: list = field(default_factory=list)
    abandoned: Event = field(default_factory=Event)
    settled: Event = field(default_factory=Event)
    claimed: Event = field(default_factory=Event)
    gate: Lock = field(default_factory=Lock)

    def claim(self) -> bool:
        """Writer takes ownership; False once a caller has abandoned the op."""
        with self.gate:
            if self.abandoned.is_set():
                return False
            self.claimed.set()
            return True

    def abandon(self) -> bool:
        """Caller gives up; False once the writer started applying the op."""
        with self.gate:
            if self.claimed.is_set():
                return False
            self.abandoned.set()
            return True

    def outcome(self) -> str:
        """Report how far this op got, so callers never guess from timing."""
        if not self.settled.is_set():
            return WRITE_OP_APPLYING if self.claimed.is_set() else WRITE_OP_PENDING
        if self.error:
            return WRITE_OP_ERROR
        if not self.claimed.is_set():
            return WRITE_OP_SKIPPED
        if self.result_box and self.result_box[0] is False:
            return WRITE_OP_REJECTED
        return WRITE_OP_APPLIED


class TaskStoreWritePending(sqlite3.OperationalError):
    """A timed-out writer operation that may still be queued."""

    def __init__(self, message: str, op: _WriteOp) -> None:
        super().__init__(message)
        self.kind = op.kind
        self.task_id = op.task_id
        self._op = op

    def wait(self, timeout: float) -> bool:
        return bool(self._op.done and self._op.done.wait(timeout=max(0.0, timeout)))

    def wait_settled(self, timeout: float) -> bool:
        return self._op.settled.wait(timeout=max(0.0, timeout))

    def abandon(self) -> bool:
        """Cancel the queued op; False when the writer already claimed it."""
        return self._op.abandon()

    def outcome(self) -> str:
        return self._op.outcome()

    def op_error(self) -> BaseException | None:
        return self._op.error[0] if self._op.error else None


class TaskStore:
    """Thread-safe task store with optional JSON persistence."""

    _WRITE_BATCH_SIZE = 64
    _WRITE_BATCH_WAIT_SEC = 0.05
    _WRITE_WAIT_TIMEOUT_SEC = 30.0

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._tasks: dict[str, dict] = {}
        self._order: list[str] = []
        self._cancel_events: dict[str, Event] = {}
        self._lock = Lock()
        self._storage_path = storage_path
        self._db_path = self._resolve_db_path(storage_path)
        self._last_db_error: str = ""
        self._db_write_failures: int = 0
        self._write_q: queue.Queue[_WriteOp] = queue.Queue()
        self._writer_stop = Event()
        self._writer: Optional[Thread] = None
        self._closed = False
        if self._storage_path is not None:
            self._load()
        if self._db_path is not None:
            self._init_db()
            # Legacy JSON may populate ``_tasks`` while SQLite is already the live
            # store. Always migrate-then-reload from DB so recover cannot be skipped
            # (otherwise RUNNING update tasks survive process restarts forever).
            if self._db_is_empty() and self._tasks:
                self._save()
            self._load_db(recover=True)
            self._writer = Thread(
                target=self._writer_loop,
                name="asc-task-writer",
                daemon=True,
            )
            self._writer.start()

    def create(self, kind: str, *, profile: str = "", replay: dict | None = None) -> str:
        task_id = str(uuid.uuid4())
        now = self._now()
        stored_replay = replay if isinstance(replay, dict) else None
        task = {
            "id": task_id,
            "kind": kind,
            "profile": profile,
            "status": TaskStatus.PENDING,
            "logs": [],
            "result": None,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "progress": {
                "pct": 0,
                "msg": "",
                "phase": "",
                "phase_label": "",
                "phase_index": 0,
                "phase_total": 0,
            },
            "cancel_requested": False,
            "replay": stored_replay,
        }
        if self._db_path is not None:
            self._enqueue(
                "create",
                task_id,
                {
                    "kind": kind,
                    "profile": profile,
                    "now": now,
                    "replay_json": self._replay_to_json(stored_replay),
                },
                wait=True,
                critical=True,
            )
            with self._lock:
                self._cancel_events[task_id] = Event()
            return task_id
        with self._lock:
            self._refresh_db()
            self._tasks[task_id] = task
            self._order.append(task_id)
            self._cancel_events[task_id] = Event()
            self._save()
        return task_id

    def get(self, task_id: str) -> Optional[dict]:
        if self._db_path is not None:
            with self._connection() as conn:
                row = conn.execute("SELECT * FROM task_runs WHERE id = ?", (task_id,)).fetchone()
                if row is None:
                    return None
                logs = conn.execute(
                    "SELECT message FROM task_logs WHERE task_id = ? ORDER BY seq", (task_id,)
                ).fetchall()
            return self._public_task(self._task_from_row(row, logs))
        with self._lock:
            self._refresh_db()
            task = self._tasks.get(task_id)
            if task is None:
                return None
            # Return a shallow copy with a copied logs list to prevent external mutation
            return self._public_task(task)

    def append_log(self, task_id: str, line: str) -> None:
        self.append_logs(task_id, [line])

    def append_logs(self, task_id: str, lines: list[str]) -> bool:
        """Append multiple log lines atomically, assigning contiguous sequences.

        Returns False when the SQLite write fails after retries (degraded mode)
        so callers such as pip progress streaming can keep running.
        """
        if not lines:
            return True
        if self._db_path is not None:
            # Soft path waits on the writer Event (not SQLite) so callers still see
            # durable seqs; enqueue remains the only thread that touches the DB.
            return self._enqueue(
                "append_logs",
                task_id,
                {"lines": [str(line) for line in lines], "now": self._now()},
                wait=True,
                critical=False,
            )
        with self._lock:
            self._refresh_db()
            if task_id in self._tasks:
                self._tasks[task_id]["logs"].extend(str(line) for line in lines)
                limit = _task_log_limit()
                if len(self._tasks[task_id]["logs"]) > limit:
                    self._tasks[task_id]["logs"] = self._tasks[task_id]["logs"][-limit:]
                self._tasks[task_id]["updated_at"] = self._now()
                self._save()
            return True

    def get_logs_after(self, task_id: str, seq: int = 0) -> list[dict[str, Any]]:
        """Return sequenced task logs after the supplied cursor."""
        if self._db_path is not None:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT seq, message FROM task_logs WHERE task_id = ? AND seq > ? ORDER BY seq",
                    (task_id, int(seq)),
                ).fetchall()
            return [{"seq": row[0], "message": row[1]} for row in rows]
        with self._lock:
            self._refresh_db()
            task = self._tasks.get(task_id, {})
            return [
                {"seq": index, "message": message}
                for index, message in enumerate(task.get("logs", []), start=1)
                if index > seq
            ]

    def set_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        overwrite_terminal: bool = False,
    ) -> bool:
        if self._db_path is not None:
            normalized = self._normalize_status(status)
            now = self._now()
            completed_at = now if normalized in TERMINAL_STATUSES else None
            return self._enqueue(
                "set_status",
                task_id,
                {
                    "status": normalized.value,
                    "now": now,
                    "completed_at": completed_at,
                    "overwrite_terminal": overwrite_terminal,
                },
                wait=True,
                critical=True,
            )
        with self._lock:
            self._refresh_db()
            if task_id in self._tasks:
                normalized = self._normalize_status(status)
                task = self._tasks[task_id]
                if self._normalize_status(task.get("status")) == normalized:
                    return True
                task["status"] = normalized
                now = self._now()
                task["updated_at"] = now
                if normalized in TERMINAL_STATUSES:
                    task["completed_at"] = task.get("completed_at") or now
                self._save()
            return True

    def request_cancel(self, task_id: str) -> bool:
        if self._db_path is not None:
            ok = self._enqueue(
                "request_cancel",
                task_id,
                {"now": self._now()},
                wait=True,
                critical=True,
            )
            if ok:
                with self._lock:
                    event = self._cancel_events.setdefault(task_id, Event())
                    event.set()
            return ok
        with self._lock:
            self._refresh_db()
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if self._normalize_status(task.get("status")) in TERMINAL_STATUSES:
                return True
            task["cancel_requested"] = True
            task["updated_at"] = self._now()
            event = self._cancel_events.get(task_id)
            if event is None:
                event = Event()
                self._cancel_events[task_id] = event
            event.set()
            self._save()
            return True

    def is_cancel_requested(self, task_id: str) -> bool:
        if self._db_path is not None:
            with self._connection() as conn:
                row = conn.execute("SELECT cancel_requested FROM task_runs WHERE id = ?", (task_id,)).fetchone()
            return bool(row and row[0])
        with self._lock:
            task = self._tasks.get(task_id)
            return bool(task and task.get("cancel_requested"))

    def cancel_event(self, task_id: str) -> Event:
        with self._lock:
            event = self._cancel_events.get(task_id)
            if event is None:
                event = Event()
                if self._tasks.get(task_id, {}).get("cancel_requested"):
                    event.set()
                self._cancel_events[task_id] = event
            return event

    def set_result(self, task_id: str, result: Any) -> bool:
        if self._db_path is not None:
            return self._enqueue(
                "set_result",
                task_id,
                {
                    "payload": json.dumps(result, ensure_ascii=False),
                    "now": self._now(),
                },
                wait=True,
                critical=True,
            )
        with self._lock:
            self._refresh_db()
            if task_id in self._tasks:
                self._tasks[task_id]["result"] = result
                self._tasks[task_id]["updated_at"] = self._now()
                self._save()
            return True

    def set_result_if_nonterminal(
        self,
        task_id: str,
        result: Any,
        *,
        wait: bool = True,
    ) -> bool:
        """Set result only while no terminal status has won the race."""
        if self._db_path is not None:
            return self._enqueue(
                "set_result_if_nonterminal",
                task_id,
                {
                    "payload": json.dumps(result, ensure_ascii=False),
                    "now": self._now(),
                },
                wait=wait,
                critical=wait,
            )
        with self._lock:
            self._refresh_db()
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if self._normalize_status(task.get("status")) in TERMINAL_STATUSES:
                return False
            task["result"] = result
            task["updated_at"] = self._now()
            self._save()
            return True

    def set_progress(
        self,
        task_id: str,
        pct: int,
        msg: str,
        *,
        phase: str = "",
        phase_label: str = "",
        phase_index: int = 0,
        phase_total: int = 0,
    ) -> bool:
        progress = {
            "pct": int(pct),
            "msg": msg,
            "phase": phase,
            "phase_label": phase_label,
            "phase_index": int(phase_index),
            "phase_total": int(phase_total),
        }
        if self._db_path is not None:
            return self._enqueue(
                "set_progress",
                task_id,
                {"progress": progress, "now": self._now()},
                wait=True,
                critical=False,
            )
        with self._lock:
            self._refresh_db()
            if task_id in self._tasks:
                self._tasks[task_id]["progress"] = progress
                self._tasks[task_id]["updated_at"] = self._now()
                self._save()
            return True

    def close(self) -> None:
        """Drain the write queue and stop the writer thread."""
        if self._db_path is None or self._writer is None:
            self._closed = True
            return
        if self._closed:
            return
        self._closed = True
        if self._writer_stop.is_set() or not self._writer.is_alive():
            # Writer already gone: settle leftovers instead of waiting for a
            # shutdown op nobody will ever consume.
            self._abort_writer(RuntimeError("TaskStore writer already stopped"))
            return
        done = Event()
        shutdown_op = _WriteOp(kind="shutdown", done=done)
        self._write_q.put(shutdown_op)
        deadline = time.monotonic() + self._WRITE_WAIT_TIMEOUT_SEC
        while not done.wait(timeout=0.05):
            if self._writer_stop.is_set() or not self._writer.is_alive():
                error = RuntimeError("TaskStore writer stopped during shutdown")
                self._abort_writer(error)
                if not shutdown_op.settled.is_set():
                    self._settle_write_op(shutdown_op, error=error)
                self._note_db_error(error, operation="shutdown")
                break
            if time.monotonic() >= deadline:
                break
        if not shutdown_op.settled.is_set():
            print("⚠️  TaskStore writer shutdown timed out", file=sys.stderr)
        if self._writer.is_alive():
            self._writer.join(timeout=1.0)

    def flush(self, timeout: float = 5.0) -> None:
        """Wait until previously enqueued writes have been committed."""
        if (
            self._db_path is None
            or self._writer is None
            or self._closed
            or self._writer_stop.is_set()
        ):
            return
        done = Event()
        self._write_q.put(_WriteOp(kind="flush", done=done))
        done.wait(timeout=timeout)
    def list_recent(self, limit: int = 20) -> list[dict]:
        if self._db_path is not None:
            with self._connection() as conn:
                rows = conn.execute(
                    """SELECT r.*, o.position FROM task_order o
                    JOIN task_runs r ON r.id = o.task_id
                    ORDER BY o.position DESC LIMIT ?""",
                    (int(limit),),
                ).fetchall()
                logs = conn.execute(
                    "SELECT task_id, message FROM task_logs WHERE task_id IN "
                    "(SELECT task_id FROM task_order ORDER BY position DESC LIMIT ?) ORDER BY task_id, seq",
                    (int(limit),),
                ).fetchall()
            logs_by_id: dict[str, list] = {}
            for log in logs:
                logs_by_id.setdefault(log["task_id"], []).append(log)
            return [
                self._public_task(self._task_from_row(row, logs_by_id.get(row["id"], [])))
                for row in rows
            ]
        with self._lock:
            self._refresh_db()
            ordered = []
            for tid in reversed(self._order):
                if tid in self._tasks:
                    task = self._tasks[tid]
                    ordered.append(self._public_task(task))
        return ordered[:limit]

    def list_recent_states(self, limit: int = 500) -> list[dict]:
        """Return recent task metadata without loading log history."""
        normalized_limit = max(1, min(int(limit), 5000))
        if self._db_path is not None:
            with self._connection() as conn:
                rows = conn.execute(
                    """SELECT r.*, o.position FROM task_order o
                    JOIN task_runs r ON r.id = o.task_id
                    ORDER BY o.position DESC LIMIT ?""",
                    (normalized_limit,),
                ).fetchall()
            return [self._public_task(self._task_from_row(row, [])) for row in rows]
        with self._lock:
            self._refresh_db()
            ordered = []
            for task_id in reversed(self._order):
                if task_id in self._tasks:
                    state = dict(self._tasks[task_id])
                    state["logs"] = []
                    ordered.append(self._public_task(state))
                    if len(ordered) >= normalized_limit:
                        break
            return ordered

    def get_replay(self, task_id: str) -> dict | None:
        """Return the sanitized replay snapshot, or None when missing."""
        if self._db_path is not None:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT replay_json FROM task_runs WHERE id = ?", (task_id,)
                ).fetchone()
            if row is None:
                return None
            keys = set(row.keys())
            raw = row["replay_json"] if "replay_json" in keys else None
            replay = self._replay_from_value(raw)
            return dict(replay) if replay is not None else None
        with self._lock:
            self._refresh_db()
            task = self._tasks.get(task_id)
            if task is None:
                return None
            replay = task.get("replay")
            return dict(replay) if isinstance(replay, dict) else None

    def set_replay(self, task_id: str, replay: dict | None) -> None:
        stored_replay = replay if isinstance(replay, dict) else None
        if self._db_path is not None:
            self._enqueue(
                "set_replay",
                task_id,
                {
                    "replay_json": self._replay_to_json(stored_replay),
                    "now": self._now(),
                },
                wait=True,
                critical=True,
            )
            return
        with self._lock:
            self._refresh_db()
            task = self._tasks.get(task_id)
            if task is None:
                return
            task["replay"] = stored_replay
            task["updated_at"] = self._now()
            self._save()

    def list_failed(
        self,
        *,
        limit: int = 20,
        kind: str | None = None,
        profile: str | None = None,
        prefer_profile: str | None = None,
    ) -> list[dict]:
        """Return recent error tasks; cookie profile is sort-only."""
        capped = max(1, min(int(limit), 50))
        if self._db_path is not None:
            sql = "SELECT * FROM task_runs WHERE status = ?"
            params: list[Any] = [TaskStatus.ERROR.value]
            if kind:
                sql += " AND kind = ?"
                params.append(kind)
            if profile:
                sql += " AND profile = ?"
                params.append(profile)
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(capped)
            with self._connection() as conn:
                rows = conn.execute(sql, params).fetchall()
            tasks = [
                self._public_task(self._task_from_row(row, [])) for row in rows
            ]
        else:
            with self._lock:
                self._refresh_db()
                collected: list[dict] = []
                for task_id in self._order:
                    task = self._tasks.get(task_id)
                    if task is None:
                        continue
                    if self._normalize_status(task.get("status")) != TaskStatus.ERROR:
                        continue
                    if kind and str(task.get("kind") or "") != kind:
                        continue
                    if profile and str(task.get("profile") or "") != profile:
                        continue
                    state = dict(task)
                    state["logs"] = []
                    collected.append(self._public_task(state))
            collected.sort(
                key=lambda row: str(row.get("updated_at") or ""),
                reverse=True,
            )
            tasks = collected[:capped]
        if prefer_profile:
            preferred = [row for row in tasks if row.get("profile") == prefer_profile]
            others = [row for row in tasks if row.get("profile") != prefer_profile]
            tasks = preferred + others
        return tasks

    def get_state(self, task_id: str) -> Optional[dict]:
        """Return task metadata without loading its log history."""
        if self._db_path is None:
            with self._lock:
                task = self._tasks.get(task_id)
                if task is None:
                    return None
                state = dict(task)
                state["logs"] = []
                return self._public_task(state)
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM task_runs WHERE id = ?", (task_id,)).fetchone()
        return self._public_task(self._task_from_row(row, [])) if row is not None else None

    def get_stream_snapshot(self, task_id: str, after: int) -> StreamSnapshot | None:
        """Return task state and incremental logs from one consistent snapshot."""
        cursor = max(0, int(after))
        if self._db_path is not None:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM task_runs WHERE id = ?",
                    (task_id,),
                ).fetchone()
                if row is None:
                    return None
                log_rows = conn.execute(
                    "SELECT seq, message FROM task_logs "
                    "WHERE task_id = ? AND seq > ? ORDER BY seq",
                    (task_id, cursor),
                ).fetchall()
                task = self._public_task(self._task_from_row(row, []))
                logs = [
                    {"seq": int(log["seq"]), "message": log["message"]}
                    for log in log_rows
                ]
                return {"task": task, "logs": logs}
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            state = dict(task)
            messages = list(task.get("logs", []))
            state["logs"] = []
            return {
                "task": self._public_task(state),
                "logs": [
                    {"seq": index, "message": message}
                    for index, message in enumerate(messages, start=1)
                    if index > cursor
                ],
            }

    def count_logs(self, task_id: str) -> int:
        """Return log line count without loading messages."""
        if self._db_path is not None:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM task_logs WHERE task_id = ?", (task_id,)
                ).fetchone()
            return int(row[0]) if row else 0
        with self._lock:
            task = self._tasks.get(task_id)
            return len(task.get("logs", [])) if task else 0

    def _task_from_row(self, row: Any, log_rows: list[Any]) -> dict:
        logs = [row["message"] for row in log_rows]
        result_json = row["result_json"]
        keys = set(row.keys())
        replay = None
        if "replay_json" in keys:
            replay = self._replay_from_value(row["replay_json"])
        return {
            "id": row["id"],
            "kind": row["kind"],
            "profile": row["profile"],
            "status": self._normalize_status(row["status"]),
            "logs": logs,
            "result": json.loads(result_json) if result_json else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
            "progress": self._progress_from_row(row),
            "cancel_requested": bool(row["cancel_requested"]),
            "replay": replay,
        }

    def _progress_from_row(self, row: Any) -> dict:
        keys = set(row.keys())
        return {
            "pct": row["progress_pct"],
            "msg": row["progress_msg"],
            "phase": row["progress_phase"] if "progress_phase" in keys else "",
            "phase_label": row["progress_phase_label"] if "progress_phase_label" in keys else "",
            "phase_index": int(row["phase_index"]) if "phase_index" in keys else 0,
            "phase_total": int(row["phase_total"]) if "phase_total" in keys else 0,
        }

    def _normalize_progress(self, progress: Any) -> dict:
        if not isinstance(progress, dict):
            progress = {}
        return {
            "pct": self._coerce_int(progress.get("pct"), default=0),
            "msg": str(progress.get("msg", "") or ""),
            "phase": str(progress.get("phase", "") or ""),
            "phase_label": str(progress.get("phase_label", "") or ""),
            "phase_index": self._coerce_int(progress.get("phase_index"), default=0),
            "phase_total": self._coerce_int(progress.get("phase_total"), default=0),
        }

    def _public_task(self, task: dict) -> dict:
        result = dict(task)
        result["logs"] = list(task["logs"])
        kind = str(result.get("kind", ""))
        result["title"] = TASK_KIND_LABELS.get(kind, kind or "未知任务")
        result["retry_path"] = TASK_KIND_RETRY_PATHS.get(kind)
        duration_seconds = self._duration_seconds(result)
        result["duration_seconds"] = duration_seconds
        result["duration_label"] = self._format_duration(duration_seconds)
        replay = result.pop("replay", None)
        result.pop("params", None)
        result["has_replay"] = bool(replay)
        return result

    def _load(self) -> None:
        if (
            self._storage_path is None
            or self._storage_path.suffix.lower() != ".json"
            or not self._storage_path.exists()
        ):
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return

        tasks = data.get("tasks", {})
        order = data.get("order", [])
        if not isinstance(tasks, dict) or not isinstance(order, list):
            return

        loaded_tasks: dict[str, dict] = {}
        loaded_order: list[str] = []
        for task_id in order:
            if not isinstance(task_id, str) or task_id not in tasks:
                continue
            task = self._normalize_loaded_task(task_id, tasks[task_id])
            if task is None:
                continue
            loaded_tasks[task_id] = task
            loaded_order.append(task_id)

        self._tasks = loaded_tasks
        self._order = loaded_order

    def _normalize_loaded_task(self, task_id: str, task: Any) -> Optional[dict]:
        if not isinstance(task, dict):
            return None
        status = self._normalize_status(task.get("status"))
        result = task.get("result")
        logs = task.get("logs") if isinstance(task.get("logs"), list) else []
        kind = str(task.get("kind") or "unknown")
        if status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            now = self._now()
            recovered = self._recover_non_terminal_task(
                {
                    "kind": kind,
                    "status": status,
                    "result": result if isinstance(result, dict) else None,
                    "logs": list(logs),
                    "updated_at": now,
                    "completed_at": now,
                }
            )
            status = recovered["status"]
            result = recovered["result"]
            logs = recovered["logs"]
            task["updated_at"] = recovered["updated_at"]
            task["completed_at"] = recovered["completed_at"]

        now = self._now()

        replay = task.get("replay")
        if not isinstance(replay, dict):
            replay = None

        return {
            "id": task.get("id") or task_id,
            "kind": kind,
            "profile": task.get("profile") or "",
            "status": status,
            "logs": logs,
            "result": result,
            "created_at": task.get("created_at") or now,
            "updated_at": task.get("updated_at") or task.get("created_at") or now,
            "completed_at": task.get("completed_at"),
            "progress": self._normalize_progress(task.get("progress")),
            "cancel_requested": bool(task.get("cancel_requested")),
            "replay": replay,
        }

    @staticmethod
    def _update_result_looks_successful(result: Any) -> bool:
        if not isinstance(result, dict):
            return False
        if result.get("restart_blocked") is True:
            return False
        return bool(
            result.get("success") is True
            or result.get("restarting") is True
            or result.get("installed") is True
            or result.get("pending_install") is True
            or result.get("restarted") is True
        )

    @staticmethod
    def _read_update_marker_for_task(task_id: str) -> dict | None:
        try:
            from asc.web.daemon import read_update_restart_marker

            marker = read_update_restart_marker()
        except Exception:
            return None
        if not isinstance(marker, dict):
            return None
        if str(marker.get("task_id") or "") != str(task_id):
            return None
        return marker

    def _recover_non_terminal_task(self, task: dict) -> dict:
        """Finalize or interrupt a PENDING/RUNNING task after process restart."""
        now = self._now()
        kind = str(task.get("kind") or "")
        result = task.get("result") if isinstance(task.get("result"), dict) else None
        logs = list(task.get("logs") or [])
        recovery = (
            result.get("_asc_terminal_recovery")
            if isinstance(result, dict)
            else None
        )
        intended_status: TaskStatus | None = None
        if isinstance(recovery, dict) and recovery.get("version") == 1:
            try:
                candidate = TaskStatus(recovery.get("status"))
            except (TypeError, ValueError):
                candidate = None
            if candidate in TERMINAL_STATUSES:
                intended_status = candidate

        if (
            kind == "update"
            and isinstance(result, dict)
            and result.get("restarting") is True
            and self._update_result_looks_successful(result)
            and intended_status in {None, TaskStatus.DONE}
        ):
            marker = self._read_update_marker_for_task(str(task.get("id") or ""))
            if marker and marker.get("install_error"):
                merged = dict(result or {})
                merged["success"] = False
                merged["installed"] = False
                merged["pending_install"] = False
                merged["restarting"] = False
                merged["restarted"] = True
                merged["error"] = str(marker.get("install_error"))
                logs.append(f"❌ 重启后安装失败：{marker.get('install_error')}")
                return {
                    "status": TaskStatus.ERROR,
                    "result": merged,
                    "logs": logs,
                    "updated_at": now,
                    "completed_at": now,
                }
            merged = dict(result or {})
            merged["success"] = True
            merged["restarting"] = False
            merged["restarted"] = True
            if marker and marker.get("installed"):
                merged["installed"] = True
                merged["pending_install"] = False
            elif merged.get("pending_install") and not (marker and marker.get("install_error")):
                # Helper finished install before start; marker may already say installed,
                # or was written then partially read — treat pending as completed when
                # there is no install_error.
                if marker is None or marker.get("installed") is not False:
                    merged["installed"] = True
                    merged["pending_install"] = False
            logs.append("✅ 服务已重启，更新任务已收尾")
            return {
                "status": TaskStatus.DONE,
                "result": merged,
                "logs": logs,
                "updated_at": now,
                "completed_at": task.get("completed_at") or now,
            }
        if intended_status is not None:
            logs.append(
                f"⚠️ 服务重启，已按持久化终态意图恢复为 {intended_status.value}"
            )
            return {
                "status": intended_status,
                "result": dict(result or {}),
                "logs": logs,
                "updated_at": now,
                "completed_at": task.get("completed_at") or now,
            }
        logs.append("⚠️ 服务重启，任务已中断")
        interrupted = dict(result or {})
        interrupted.update(
            {
                "success": False,
                "installed": False,
                "pending_install": False,
                "restarting": False,
                "error": "Task interrupted by server restart",
            }
        )
        return {
            "status": TaskStatus.ERROR,
            "result": interrupted,
            "logs": logs,
            "updated_at": now,
            "completed_at": now,
        }

    @staticmethod
    def _replay_to_json(replay: Any) -> str | None:
        if not isinstance(replay, dict):
            return None
        return json.dumps(replay, ensure_ascii=False)

    @staticmethod
    def _replay_from_value(value: Any) -> dict | None:
        if value is None or value == "":
            return None
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _normalize_status(self, value: Any) -> TaskStatus:
        try:
            return TaskStatus(value)
        except (TypeError, ValueError):
            return TaskStatus.ERROR

    def _coerce_int(self, value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _duration_seconds(self, task: dict) -> int:
        start = self._parse_datetime(task.get("created_at"))
        if start is None:
            return 0

        status = self._normalize_status(task.get("status"))
        end = None
        if status in TERMINAL_STATUSES:
            end = self._parse_datetime(task.get("completed_at")) or self._parse_datetime(
                task.get("updated_at")
            )
        end = end or datetime.now()
        return max(0, int((end - start).total_seconds()))

    def _format_duration(self, seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        minutes, secs = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes}m {secs}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m"

    def _resolve_db_path(self, storage_path: Optional[Path]) -> Optional[Path]:
        if storage_path is None:
            return None
        if storage_path.suffix.lower() == ".json":
            path = storage_path.with_suffix(".db")
        else:
            path = storage_path
        path = path.expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        # strict=False so missing parent dirs do not raise; the connection opener creates them.
        return path.resolve(strict=False)

    def _ensure_db_dir(self) -> Path:
        assert self._db_path is not None
        parent = self._db_path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise sqlite3.OperationalError(
                f"unable to create database directory {parent}: {exc}"
            ) from exc
        if parent.exists() and not os.access(parent, os.W_OK | os.X_OK):
            raise sqlite3.OperationalError(
                f"unable to open database file: {self._db_path} "
                f"(directory not writable: {parent})"
            )
        if self._db_path.exists() and self._db_path.is_dir():
            raise sqlite3.OperationalError(
                f"unable to open database file: {self._db_path} (path is a directory)"
            )
        return parent

    def _format_db_error(self, exc: BaseException) -> str:
        return f"TaskStore DB error ({self._db_path}): {exc}"

    def _note_db_error(
        self,
        exc: BaseException,
        *,
        task_id: str | None = None,
        operation: str = "unknown",
    ) -> None:
        self._db_write_failures += 1
        msg = (
            f"TaskStore DB error task_id={task_id or '-'} "
            f"operation={operation} path={self._db_path}: {exc}"
        )
        if msg == self._last_db_error:
            return
        self._last_db_error = msg
        print(f"⚠️  {msg}", file=sys.stderr)

    def _enqueue(
        self,
        kind: str,
        task_id: Optional[str],
        payload: dict,
        *,
        wait: bool,
        critical: bool,
    ) -> bool:
        if self._closed or self._writer_stop.is_set():
            exc = sqlite3.OperationalError("TaskStore writer is closed")
            self._note_db_error(exc, task_id=task_id, operation=kind)
            if critical:
                raise exc
            return False
        done = Event() if wait else None
        op = _WriteOp(
            kind=kind,
            task_id=task_id,
            payload=payload,
            done=done,
            critical=critical,
        )
        self._write_q.put(op)
        if self._writer_stop.is_set() and not op.settled.is_set():
            # The writer died between the guard above and this put; settle here so
            # the caller fails fast instead of waiting out the write timeout.
            if op.abandon():
                exc = sqlite3.OperationalError("TaskStore writer stopped")
                self._settle_write_op(op, error=exc)
                self._note_db_error(exc, task_id=task_id, operation=kind)
                if critical:
                    raise exc
                return False
        if not wait or done is None:
            return True
        if not done.wait(timeout=self._WRITE_WAIT_TIMEOUT_SEC):
            message = self._format_db_error(
                TimeoutError(f"TaskStore write timed out ({kind}); operation still pending")
            )
            exc = TaskStoreWritePending(message, op)
            self._note_db_error(exc, task_id=task_id, operation=kind)
            if critical:
                raise exc
            return False
        if op.error:
            exc = op.error[0]
            if critical:
                if isinstance(exc, sqlite3.Error):
                    raise sqlite3.OperationalError(self._format_db_error(exc)) from exc
                raise exc
            return False
        if op.result_box:
            return bool(op.result_box[0])
        return True

    def _writer_loop(self) -> None:
        """Serve writes; any exit path stops the writer and settles pending ops."""
        try:
            self._writer_serve()
        except BaseException as exc:
            self._note_db_error(exc, operation="writer_loop")
            self._abort_writer(exc)
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
        finally:
            self._writer_stop.set()

    def _writer_serve(self) -> None:
        while True:
            op = self._write_q.get()
            if op.kind == "shutdown":
                try:
                    self._writer_drain_remaining()
                finally:
                    self._settle_write_op(op)
                    self._writer_stop.set()
                    self._write_q.task_done()
                return
            batch = [op]
            try:
                deadline = time.monotonic() + self._WRITE_BATCH_WAIT_SEC
                while len(batch) < self._WRITE_BATCH_SIZE:
                    timeout = deadline - time.monotonic()
                    if timeout <= 0:
                        try:
                            nxt = self._write_q.get_nowait()
                        except queue.Empty:
                            break
                    else:
                        try:
                            nxt = self._write_q.get(timeout=timeout)
                        except queue.Empty:
                            break
                    if nxt.kind == "shutdown":
                        self._write_q.task_done()
                        self._write_q.put(nxt)
                        break
                    batch.append(nxt)
                self._writer_run_batch(batch)
            except BaseException as exc:
                self._abort_writer(exc, batch=batch)
                raise
            finally:
                for _ in batch:
                    self._write_q.task_done()

    def _abort_writer(
        self,
        exc: BaseException,
        *,
        batch: Optional[list[_WriteOp]] = None,
    ) -> None:
        """Stop the writer and settle every op so callers never wait for a dead thread."""
        self._writer_stop.set()
        error = sqlite3.OperationalError(
            f"TaskStore writer terminated ({exc.__class__.__name__}): {exc}"
        )
        current = [op for op in (batch or []) if not op.settled.is_set()]
        orphans: list[_WriteOp] = []
        while True:
            try:
                orphans.append(self._write_q.get_nowait())
            except queue.Empty:
                break
        for op in (*current, *orphans):
            if not op.settled.is_set():
                self._settle_write_op(op, error=error)
        pending = [*current, *orphans]
        if pending:
            self._note_db_error(
                error,
                task_id=next(
                    (op.task_id for op in pending if op.task_id is not None),
                    None,
                ),
                operation=",".join(dict.fromkeys(op.kind for op in pending)),
            )
        for _ in orphans:
            self._write_q.task_done()

    def _writer_drain_remaining(self) -> None:
        remaining: list[_WriteOp] = []
        while True:
            try:
                remaining.append(self._write_q.get_nowait())
            except queue.Empty:
                break
        writes = [op for op in remaining if op.kind not in {"shutdown", "flush"}]
        flushes = [op for op in remaining if op.kind == "flush"]
        shutdowns = [op for op in remaining if op.kind == "shutdown"]
        try:
            if writes:
                self._writer_run_batch(writes)
        finally:
            for op in (*flushes, *shutdowns):
                self._settle_write_op(op)
            for _ in remaining:
                self._write_q.task_done()

    @staticmethod
    def _settle_write_op(
        op: _WriteOp,
        *,
        error: BaseException | None = None,
    ) -> None:
        if error is not None and not op.error:
            op.error.append(error)
        op.settled.set()
        if op.done is not None:
            op.done.set()

    def _writer_run_batch(self, ops: list[_WriteOp]) -> None:
        flushes = [op for op in ops if op.kind == "flush"]
        writes: list[_WriteOp] = []
        for op in ops:
            if op.kind == "flush":
                continue
            # Claim atomically so an abandoning caller learns whether this op is
            # definitely skipped or already being applied.
            if op.claim():
                writes.append(op)
            else:
                op.result_box.append(False)
                self._settle_write_op(op)
        fatal_exc: BaseException | None = None
        if writes:
            critical = any(op.critical for op in writes)
            attempts = 3 if critical else 2
            last_exc: BaseException | None = None
            for attempt in range(attempts):
                try:
                    with self._connection(write=True) as conn:
                        for op in writes:
                            op.result_box.clear()
                            op.result_box.append(self._apply_op(conn, op))
                    last_exc = None
                    break
                except (OSError, sqlite3.Error) as exc:
                    last_exc = exc
                    if attempt + 1 < attempts:
                        time.sleep(0.05 * (attempt + 1))
                        continue
                    self._note_db_error(
                        exc,
                        task_id=writes[0].task_id,
                        operation=",".join(dict.fromkeys(op.kind for op in writes)),
                    )
                    for op in writes:
                        op.error.append(exc)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    self._note_db_error(
                        exc,
                        task_id=writes[0].task_id,
                        operation=",".join(dict.fromkeys(op.kind for op in writes)),
                    )
                    break
                except BaseException as exc:
                    last_exc = exc
                    fatal_exc = exc
                    self._note_db_error(
                        exc,
                        task_id=writes[0].task_id,
                        operation=",".join(dict.fromkeys(op.kind for op in writes)),
                    )
                    break
            for op in writes:
                self._settle_write_op(op, error=last_exc)
        for op in flushes:
            self._settle_write_op(op)
        if fatal_exc is not None:
            raise fatal_exc

    def _apply_op(self, conn: sqlite3.Connection, op: _WriteOp) -> Any:
        kind = op.kind
        task_id = op.task_id
        payload = op.payload
        if kind == "create":
            assert task_id is not None
            conn.execute(
                """INSERT INTO task_runs
                (id, kind, profile, status, created_at, updated_at,
                 progress_pct, progress_msg, progress_phase, progress_phase_label,
                 phase_index, phase_total, replay_json)
                VALUES (?, ?, ?, ?, ?, ?, 0, '', '', '', 0, 0, ?)""",
                (
                    task_id,
                    payload["kind"],
                    payload["profile"],
                    TaskStatus.PENDING.value,
                    payload["now"],
                    payload["now"],
                    payload.get("replay_json"),
                ),
            )
            conn.execute("INSERT INTO task_order (task_id) VALUES (?)", (task_id,))
            return True
        if kind == "append_logs":
            assert task_id is not None
            lines = payload["lines"]
            now = payload["now"]
            exists = conn.execute(
                "SELECT 1 FROM task_runs WHERE id = ?", (task_id,)
            ).fetchone()
            if exists is None:
                return False
            seq = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM task_logs WHERE task_id = ?",
                (task_id,),
            ).fetchone()[0]
            conn.executemany(
                "INSERT INTO task_logs (task_id, seq, message, created_at) VALUES (?, ?, ?, ?)",
                [
                    (task_id, seq + index, str(line), now)
                    for index, line in enumerate(lines)
                ],
            )
            limit = _task_log_limit()
            conn.execute(
                """DELETE FROM task_logs
                   WHERE task_id = ?
                     AND seq <= (
                       SELECT COALESCE(MAX(seq), 0) - ? FROM task_logs WHERE task_id = ?
                     )""",
                (task_id, limit, task_id),
            )
            conn.execute(
                "UPDATE task_runs SET updated_at = ? WHERE id = ?", (now, task_id)
            )
            return True
        if kind == "set_status":
            assert task_id is not None
            desired = self._normalize_status(payload["status"])
            terminal_values = tuple(status.value for status in TERMINAL_STATUSES)
            placeholders = ", ".join("?" for _ in terminal_values)
            # A same-terminal retry must stay a no-op: keep the original
            # completion/update timestamps instead of restamping "now".
            params: list[Any] = [
                desired.value,
                desired.value,
                payload["now"],
                desired.value,
                payload["completed_at"],
                task_id,
            ]
            if payload.get("overwrite_terminal"):
                condition = "1 = 1"
            else:
                condition = f"status NOT IN ({placeholders})"
                params.extend(terminal_values)
                if desired in TERMINAL_STATUSES:
                    condition = f"({condition} OR status = ?)"
                    params.append(desired.value)
            cursor = conn.execute(
                "UPDATE task_runs SET status = ?, "
                "updated_at = CASE WHEN status = ? THEN updated_at ELSE ? END, "
                "completed_at = CASE WHEN status = ? THEN completed_at "
                "ELSE COALESCE(?, completed_at) END "
                f"WHERE id = ? AND {condition}",
                params,
            )
            return cursor.rowcount > 0
        if kind in {"set_result", "set_result_if_nonterminal"}:
            assert task_id is not None
            params = [payload["payload"], payload["now"], task_id]
            condition = ""
            if kind == "set_result_if_nonterminal":
                terminal_values = tuple(status.value for status in TERMINAL_STATUSES)
                placeholders = ", ".join("?" for _ in terminal_values)
                condition = f" AND status NOT IN ({placeholders})"
                params.extend(terminal_values)
            cursor = conn.execute(
                "UPDATE task_runs SET result_json = ?, updated_at = ? "
                f"WHERE id = ?{condition}",
                params,
            )
            return cursor.rowcount > 0
        if kind == "set_progress":
            assert task_id is not None
            progress = payload["progress"]
            conn.execute(
                """UPDATE task_runs SET progress_pct = ?, progress_msg = ?,
                   progress_phase = ?, progress_phase_label = ?,
                   phase_index = ?, phase_total = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    progress["pct"],
                    progress["msg"],
                    progress["phase"],
                    progress["phase_label"],
                    progress["phase_index"],
                    progress["phase_total"],
                    payload["now"],
                    task_id,
                ),
            )
            return True
        if kind == "request_cancel":
            assert task_id is not None
            row = conn.execute(
                "SELECT status FROM task_runs WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                return False
            if self._normalize_status(row["status"]) not in TERMINAL_STATUSES:
                conn.execute(
                    "UPDATE task_runs SET cancel_requested = 1, updated_at = ? WHERE id = ?",
                    (payload["now"], task_id),
                )
            return True
        if kind == "set_replay":
            assert task_id is not None
            conn.execute(
                "UPDATE task_runs SET replay_json = ?, updated_at = ? WHERE id = ?",
                (payload["replay_json"], payload["now"], task_id),
            )
            return True
        raise ValueError(f"unknown write op: {kind}")

    def _db_write(self, writer: Callable[[sqlite3.Connection], None], *, critical: bool) -> bool:
        """Run *writer* with retries. Soft-fail (return False) unless *critical*.

        Prefer ``_enqueue`` for hot-path mutations; kept for init-time ``_save`` helpers.
        """
        attempts = 3 if critical else 2
        last_exc: BaseException | None = None
        for attempt in range(attempts):
            try:
                with self._connection(write=True) as conn:
                    writer(conn)
                return True
            except (OSError, sqlite3.Error) as exc:
                last_exc = exc
                if attempt + 1 < attempts:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                self._note_db_error(exc, operation="db_write")
                if critical:
                    # Keep a clear path-bearing message for callers / task fail logs.
                    raise sqlite3.OperationalError(self._format_db_error(exc)) from exc
                return False
        if last_exc is not None and critical:
            raise sqlite3.OperationalError(self._format_db_error(last_exc)) from last_exc
        return False

    def _open_configured_connection(self) -> sqlite3.Connection:
        assert self._db_path is not None
        self._ensure_db_dir()
        conn: sqlite3.Connection | None = None
        try:
            # timeout covers sqlite busy waits; keep moderate so a stuck writer
            # cannot pin callers for tens of seconds after we stopped holding
            # the Python lock across I/O.
            conn = sqlite3.connect(str(self._db_path), timeout=5.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # Persist/confirm WAL on every connection; cheap no-op once enabled.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            return conn
        except BaseException:
            if conn is not None:
                conn.close()
            raise

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self._open_configured_connection()
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        try:
            with self._connection(write=True) as conn:
                conn.execute(
                    """
                CREATE TABLE IF NOT EXISTS task_runs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    profile TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    progress_pct INTEGER NOT NULL DEFAULT 0,
                    progress_msg TEXT NOT NULL DEFAULT '',
                    progress_phase TEXT NOT NULL DEFAULT '',
                    progress_phase_label TEXT NOT NULL DEFAULT '',
                    phase_index INTEGER NOT NULL DEFAULT 0,
                    phase_total INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    replay_json TEXT
                )
                """
                )
                conn.execute(
                    """
                CREATE TABLE IF NOT EXISTS task_order (
                    position INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE
                )
                """
                )
                conn.execute(
                    """
                CREATE TABLE IF NOT EXISTS task_logs (
                    task_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, seq)
                )
                """
                )
                existing = {row[1] for row in conn.execute("PRAGMA table_info(task_runs)")}
                for column, declaration in (
                    ("progress_phase", "TEXT NOT NULL DEFAULT ''"),
                    ("progress_phase_label", "TEXT NOT NULL DEFAULT ''"),
                    ("phase_index", "INTEGER NOT NULL DEFAULT 0"),
                    ("phase_total", "INTEGER NOT NULL DEFAULT 0"),
                    ("replay_json", "TEXT"),
                ):
                    if column not in existing:
                        conn.execute(f"ALTER TABLE task_runs ADD COLUMN {column} {declaration}")
        except (OSError, sqlite3.Error) as exc:
            self._note_db_error(exc, operation="init_db")
            raise

    def _db_is_empty(self) -> bool:
        with self._connection() as conn:
            return conn.execute("SELECT 1 FROM task_runs LIMIT 1").fetchone() is None

    def _load_db(self, *, recover: bool = False) -> None:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM task_runs ORDER BY id").fetchall()
            order_rows = conn.execute("SELECT task_id FROM task_order ORDER BY position").fetchall()
            logs = conn.execute("SELECT task_id, message FROM task_logs ORDER BY task_id, seq").fetchall()
        by_id = {row["id"]: row for row in rows}
        self._tasks = {}
        self._order = [row["task_id"] for row in order_rows if row["task_id"] in by_id]
        for task_id, row in by_id.items():
            keys = set(row.keys())
            replay = None
            if "replay_json" in keys:
                replay = self._replay_from_value(row["replay_json"])
            task = {
                "id": task_id,
                "kind": row["kind"],
                "profile": row["profile"],
                "status": self._normalize_status(row["status"]),
                "logs": [],
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
                "progress": self._progress_from_row(row),
                "cancel_requested": bool(row["cancel_requested"]),
                "replay": replay,
            }
            self._tasks[task_id] = task
        for row in logs:
            if row["task_id"] in self._tasks:
                self._tasks[row["task_id"]]["logs"].append(row["message"])
        for task_id in self._tasks:
            self._cancel_events[task_id] = Event()
            if self._tasks[task_id]["cancel_requested"]:
                self._cancel_events[task_id].set()

        if not recover:
            return
        changed = False
        for task_id in list(self._order):
            task = self._tasks[task_id]
            if self._normalize_status(task["status"]) not in {
                TaskStatus.PENDING,
                TaskStatus.RUNNING,
            }:
                # Successful update may still advertise restarting=true after the
                # new process boots; clear that flag so clients see a finished task.
                if (
                    str(task.get("kind") or "") == "update"
                    and self._normalize_status(task["status"]) == TaskStatus.DONE
                    and isinstance(task.get("result"), dict)
                    and task["result"].get("restart_blocked") is not True
                    and (
                        task["result"].get("restarting") is True
                        or task["result"].get("pending_install") is True
                    )
                ):
                    marker = self._read_update_marker_for_task(str(task.get("id") or ""))
                    if marker and marker.get("install_error"):
                        result = dict(task["result"])
                        result["success"] = False
                        result["installed"] = False
                        result["pending_install"] = False
                        result["restarting"] = False
                        result["restarted"] = True
                        result["error"] = str(marker.get("install_error"))
                        task["result"] = result
                        task["status"] = TaskStatus.ERROR
                        task["updated_at"] = self._now()
                        task["completed_at"] = task.get("completed_at") or task["updated_at"]
                        task["logs"].append(
                            f"❌ 重启后安装失败：{marker.get('install_error')}"
                        )
                        changed = True
                        continue
                    result = dict(task["result"])
                    result["restarting"] = False
                    result["restarted"] = True
                    if marker and marker.get("installed"):
                        result["installed"] = True
                        result["pending_install"] = False
                    elif result.get("pending_install") and (
                        marker is None or marker.get("installed") is not False
                    ):
                        result["installed"] = True
                        result["pending_install"] = False
                    task["result"] = result
                    task["updated_at"] = self._now()
                    task["logs"].append("✅ Web UI 已重启，更新完成")
                    changed = True
                continue
            recovered = self._recover_non_terminal_task(task)
            task["status"] = recovered["status"]
            task["result"] = recovered["result"]
            task["logs"] = recovered["logs"]
            task["updated_at"] = recovered["updated_at"]
            task["completed_at"] = recovered["completed_at"]
            changed = True
        if changed:
            self._save()

    def _refresh_db(self) -> None:
        if self._db_path is not None:
            self._load_db(recover=False)

    def _save(self) -> None:
        if self._db_path is None:
            return
        try:
            with self._connection(write=True) as conn:
                for task in self._tasks.values():
                    result_json = json.dumps(task["result"], ensure_ascii=False) if task["result"] is not None else None
                    progress = self._normalize_progress(task.get("progress"))
                    conn.execute(
                        """INSERT OR REPLACE INTO task_runs
                        (id, kind, profile, status, result_json, created_at, updated_at, completed_at,
                         progress_pct, progress_msg, progress_phase, progress_phase_label,
                         phase_index, phase_total, cancel_requested, replay_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            task["id"],
                            task["kind"],
                            task["profile"],
                            self._normalize_status(task["status"]).value,
                            result_json,
                            task["created_at"],
                            task["updated_at"],
                            task["completed_at"],
                            progress["pct"],
                            progress["msg"],
                            progress["phase"],
                            progress["phase_label"],
                            progress["phase_index"],
                            progress["phase_total"],
                            int(task["cancel_requested"]),
                            self._replay_to_json(task.get("replay")),
                        ),
                    )
                    conn.execute("DELETE FROM task_logs WHERE task_id = ?", (task["id"],))
                    conn.executemany(
                        "INSERT INTO task_logs (task_id, seq, message, created_at) VALUES (?, ?, ?, ?)",
                        [(task["id"], seq, message, task["updated_at"]) for seq, message in enumerate(task["logs"], start=1)],
                    )
                conn.execute("DELETE FROM task_order")
                conn.executemany("INSERT INTO task_order (task_id) VALUES (?)", [(task_id,) for task_id in self._order])
        except (OSError, sqlite3.Error, TypeError):
            return


def _default_storage_path() -> Optional[Path]:
    env_path = os.getenv("ASC_WEB_TASKS_PATH")
    if env_path:
        return Path(env_path).expanduser()
    state_dir = Path.home() / ".config" / "asc"
    legacy_path = state_dir / "web_tasks.json"
    if legacy_path.exists():
        return legacy_path
    return state_dir / "tasks.db"


# Module-level singleton used by server.py
task_store = TaskStore(_default_storage_path())
atexit.register(task_store.close)
