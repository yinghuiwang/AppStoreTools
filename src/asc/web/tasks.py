"""Task state store for Web UI background jobs."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable, Optional


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
    "iap": "内购上传",
    "iap-review-screenshots": "IAP 审核截图上传",
    "urls": "URL 更新",
    "update": "工具更新",
}


TASK_KIND_RETRY_PATHS = {
    "metadata": "/metadata",
    "build": "/build",
    "whats-new": "/whats-new",
    "iap": "/iap",
    "iap-review-screenshots": "/iap",
    "urls": "/urls",
    "update": "/update",
}


TERMINAL_STATUSES = {TaskStatus.DONE, TaskStatus.ERROR, TaskStatus.CANCELED}


class TaskStore:
    """Thread-safe task store with optional JSON persistence."""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._tasks: dict[str, dict] = {}
        self._order: list[str] = []
        self._cancel_events: dict[str, Event] = {}
        self._lock = Lock()
        self._storage_path = storage_path
        self._db_path = self._resolve_db_path(storage_path)
        self._last_db_error: str = ""
        self._db_write_failures: int = 0
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

    def create(self, kind: str, *, profile: str = "") -> str:
        task_id = str(uuid.uuid4())
        now = self._now()
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
        }
        with self._lock:
            if self._db_path is not None:

                def _write(conn: sqlite3.Connection) -> None:
                    conn.execute(
                        """INSERT INTO task_runs
                        (id, kind, profile, status, created_at, updated_at,
                         progress_pct, progress_msg, progress_phase, progress_phase_label,
                         phase_index, phase_total)
                        VALUES (?, ?, ?, ?, ?, ?, 0, '', '', '', 0, 0)""",
                        (task_id, kind, profile, TaskStatus.PENDING.value, now, now),
                    )
                    conn.execute("INSERT INTO task_order (task_id) VALUES (?)", (task_id,))

                self._db_write(_write, critical=True)
                self._cancel_events[task_id] = Event()
                return task_id
            self._refresh_db()
            self._tasks[task_id] = task
            self._order.append(task_id)
            self._cancel_events[task_id] = Event()
            self._save()
        return task_id

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            if self._db_path is not None:
                with self._connect() as conn:
                    row = conn.execute("SELECT * FROM task_runs WHERE id = ?", (task_id,)).fetchone()
                    if row is None:
                        return None
                    logs = conn.execute(
                        "SELECT message FROM task_logs WHERE task_id = ? ORDER BY seq", (task_id,)
                    ).fetchall()
                return self._public_task(self._task_from_row(row, logs))
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
        with self._lock:
            if self._db_path is not None:
                now = self._now()

                def _write(conn: sqlite3.Connection) -> None:
                    conn.execute("BEGIN IMMEDIATE")
                    exists = conn.execute(
                        "SELECT 1 FROM task_runs WHERE id = ?", (task_id,)
                    ).fetchone()
                    if exists is None:
                        conn.rollback()
                        return
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
                    conn.execute(
                        "UPDATE task_runs SET updated_at = ? WHERE id = ?", (now, task_id)
                    )
                    conn.commit()

                return self._db_write(_write, critical=False)
            self._refresh_db()
            if task_id in self._tasks:
                self._tasks[task_id]["logs"].extend(str(line) for line in lines)
                self._tasks[task_id]["updated_at"] = self._now()
                self._save()
            return True

    def get_logs_after(self, task_id: str, seq: int = 0) -> list[dict[str, Any]]:
        """Return sequenced task logs after the supplied cursor."""
        if self._db_path is not None:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT seq, message FROM task_logs WHERE task_id = ? AND seq > ? ORDER BY seq",
                    (task_id, int(seq)),
                ).fetchall()
            return [{"seq": row[0], "message": row[1]} for row in rows]
        self._refresh_db()
        if self._db_path is None:
            task = self._tasks.get(task_id, {})
            return [
                {"seq": index, "message": message}
                for index, message in enumerate(task.get("logs", []), start=1)
                if index > seq
            ]
        return []

    def set_status(self, task_id: str, status: TaskStatus) -> bool:
        with self._lock:
            if self._db_path is not None:
                normalized = self._normalize_status(status)
                now = self._now()
                completed_at = now if normalized in TERMINAL_STATUSES else None

                def _write(conn: sqlite3.Connection) -> None:
                    conn.execute(
                        "UPDATE task_runs SET status = ?, updated_at = ?, "
                        "completed_at = COALESCE(?, completed_at) WHERE id = ?",
                        (normalized.value, now, completed_at, task_id),
                    )

                return self._db_write(_write, critical=True)
            self._refresh_db()
            if task_id in self._tasks:
                normalized = self._normalize_status(status)
                self._tasks[task_id]["status"] = normalized
                now = self._now()
                self._tasks[task_id]["updated_at"] = now
                if normalized in TERMINAL_STATUSES:
                    self._tasks[task_id]["completed_at"] = now
                self._save()
            return True

    def request_cancel(self, task_id: str) -> bool:
        with self._lock:
            if self._db_path is not None:
                now = self._now()
                with self._connect() as conn:
                    row = conn.execute("SELECT status FROM task_runs WHERE id = ?", (task_id,)).fetchone()
                    if row is None:
                        return False
                    if self._normalize_status(row["status"]) not in TERMINAL_STATUSES:
                        conn.execute(
                            "UPDATE task_runs SET cancel_requested = 1, updated_at = ? WHERE id = ?",
                            (now, task_id),
                        )
                event = self._cancel_events.setdefault(task_id, Event())
                event.set()
                return True
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
        with self._lock:
            if self._db_path is not None:
                with self._connect() as conn:
                    row = conn.execute("SELECT cancel_requested FROM task_runs WHERE id = ?", (task_id,)).fetchone()
                return bool(row and row[0])
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
        with self._lock:
            if self._db_path is not None:
                now = self._now()
                payload = json.dumps(result, ensure_ascii=False)

                def _write(conn: sqlite3.Connection) -> None:
                    conn.execute(
                        "UPDATE task_runs SET result_json = ?, updated_at = ? WHERE id = ?",
                        (payload, now, task_id),
                    )

                return self._db_write(_write, critical=True)
            self._refresh_db()
            if task_id in self._tasks:
                self._tasks[task_id]["result"] = result
                self._tasks[task_id]["updated_at"] = self._now()
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
        with self._lock:
            if self._db_path is not None:
                now = self._now()

                def _write(conn: sqlite3.Connection) -> None:
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
                            now,
                            task_id,
                        ),
                    )

                return self._db_write(_write, critical=False)
            self._refresh_db()
            if task_id in self._tasks:
                self._tasks[task_id]["progress"] = progress
                self._tasks[task_id]["updated_at"] = self._now()
                self._save()
            return True

    def list_recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            if self._db_path is not None:
                with self._connect() as conn:
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
        with self._lock:
            if self._db_path is not None:
                with self._connect() as conn:
                    rows = conn.execute(
                        """SELECT r.*, o.position FROM task_order o
                        JOIN task_runs r ON r.id = o.task_id
                        ORDER BY o.position DESC LIMIT ?""",
                        (normalized_limit,),
                    ).fetchall()
                return [self._public_task(self._task_from_row(row, [])) for row in rows]
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

    def get_state(self, task_id: str) -> Optional[dict]:
        """Return task metadata without loading its log history."""
        if self._db_path is None:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            state = dict(task)
            state["logs"] = []
            return self._public_task(state)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM task_runs WHERE id = ?", (task_id,)).fetchone()
        return self._public_task(self._task_from_row(row, [])) if row is not None else None

    def _task_from_row(self, row: Any, log_rows: list[Any]) -> dict:
        logs = [row["message"] for row in log_rows]
        result_json = row["result_json"]
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
        }

    @staticmethod
    def _update_result_looks_successful(result: Any) -> bool:
        if not isinstance(result, dict):
            return False
        return bool(
            result.get("success") is True
            or result.get("restarting") is True
            or result.get("installed") is True
            or result.get("restarted") is True
        )

    def _recover_non_terminal_task(self, task: dict) -> dict:
        """Finalize or interrupt a PENDING/RUNNING task after process restart."""
        now = self._now()
        kind = str(task.get("kind") or "")
        result = task.get("result") if isinstance(task.get("result"), dict) else None
        logs = list(task.get("logs") or [])
        if kind == "update" and self._update_result_looks_successful(result):
            merged = dict(result or {})
            merged["success"] = True
            merged["restarting"] = False
            merged["restarted"] = True
            logs.append("✅ 服务已重启，更新任务已收尾")
            return {
                "status": TaskStatus.DONE,
                "result": merged,
                "logs": logs,
                "updated_at": now,
                "completed_at": task.get("completed_at") or now,
            }
        logs.append("⚠️ 服务重启，任务已中断")
        return {
            "status": TaskStatus.ERROR,
            "result": {"success": False, "error": "Task interrupted by server restart"},
            "logs": logs,
            "updated_at": now,
            "completed_at": now,
        }

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
        # strict=False so missing parent dirs do not raise; we create them in _connect.
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

    def _note_db_error(self, exc: BaseException) -> None:
        self._db_write_failures += 1
        msg = self._format_db_error(exc)
        if msg == self._last_db_error:
            return
        self._last_db_error = msg
        print(f"⚠️  {msg}", file=sys.stderr)

    def _db_write(self, writer: Callable[[sqlite3.Connection], None], *, critical: bool) -> bool:
        """Run *writer* with retries. Soft-fail (return False) unless *critical*."""
        attempts = 3 if critical else 2
        last_exc: BaseException | None = None
        for attempt in range(attempts):
            try:
                with self._connect() as conn:
                    writer(conn)
                return True
            except (OSError, sqlite3.Error) as exc:
                last_exc = exc
                if attempt + 1 < attempts:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                self._note_db_error(exc)
                if critical:
                    # Keep a clear path-bearing message for callers / task fail logs.
                    raise sqlite3.OperationalError(self._format_db_error(exc)) from exc
                return False
        if last_exc is not None and critical:
            raise sqlite3.OperationalError(self._format_db_error(last_exc)) from last_exc
        return False

    def _connect(self) -> sqlite3.Connection:
        assert self._db_path is not None
        self._ensure_db_dir()
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=30)
        except sqlite3.Error as exc:
            raise sqlite3.OperationalError(
                f"unable to open database file: {self._db_path} ({exc})"
            ) from exc
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
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
                    cancel_requested INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS task_order (
                    position INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS task_logs (
                    task_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, seq)
                );
                """
            )
            existing = {row[1] for row in conn.execute("PRAGMA table_info(task_runs)")}
            for column, declaration in (
                ("progress_phase", "TEXT NOT NULL DEFAULT ''"),
                ("progress_phase_label", "TEXT NOT NULL DEFAULT ''"),
                ("phase_index", "INTEGER NOT NULL DEFAULT 0"),
                ("phase_total", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if column not in existing:
                    conn.execute(f"ALTER TABLE task_runs ADD COLUMN {column} {declaration}")

    def _db_is_empty(self) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM task_runs LIMIT 1").fetchone() is None

    def _load_db(self, *, recover: bool = False) -> None:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM task_runs ORDER BY id").fetchall()
            order_rows = conn.execute("SELECT task_id FROM task_order ORDER BY position").fetchall()
            logs = conn.execute("SELECT task_id, message FROM task_logs ORDER BY task_id, seq").fetchall()
        by_id = {row["id"]: row for row in rows}
        self._tasks = {}
        self._order = [row["task_id"] for row in order_rows if row["task_id"] in by_id]
        for task_id, row in by_id.items():
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
                    and task["result"].get("restarting") is True
                ):
                    result = dict(task["result"])
                    result["restarting"] = False
                    result["restarted"] = True
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
            with self._connect() as conn:
                conn.execute("BEGIN")
                for task in self._tasks.values():
                    result_json = json.dumps(task["result"], ensure_ascii=False) if task["result"] is not None else None
                    progress = self._normalize_progress(task.get("progress"))
                    conn.execute(
                        """INSERT OR REPLACE INTO task_runs
                        (id, kind, profile, status, result_json, created_at, updated_at, completed_at,
                         progress_pct, progress_msg, progress_phase, progress_phase_label,
                         phase_index, phase_total, cancel_requested)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        ),
                    )
                    conn.execute("DELETE FROM task_logs WHERE task_id = ?", (task["id"],))
                    conn.executemany(
                        "INSERT INTO task_logs (task_id, seq, message, created_at) VALUES (?, ?, ?, ?)",
                        [(task["id"], seq, message, task["updated_at"]) for seq, message in enumerate(task["logs"], start=1)],
                    )
                conn.execute("DELETE FROM task_order")
                conn.executemany("INSERT INTO task_order (task_id) VALUES (?)", [(task_id,) for task_id in self._order])
                conn.commit()
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
