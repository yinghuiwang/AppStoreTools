"""Task state store for Web UI background jobs."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Event, Lock
from typing import Any, Optional


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
        if self._storage_path is not None:
            self._load()

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
            "progress": {"pct": 0, "msg": ""},
            "cancel_requested": False,
        }
        with self._lock:
            self._tasks[task_id] = task
            self._order.append(task_id)
            self._cancel_events[task_id] = Event()
            self._save()
        return task_id

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            # Return a shallow copy with a copied logs list to prevent external mutation
            return self._public_task(task)

    def append_log(self, task_id: str, line: str) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["logs"].append(line)
                self._tasks[task_id]["updated_at"] = self._now()
                self._save()

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        with self._lock:
            if task_id in self._tasks:
                normalized = self._normalize_status(status)
                self._tasks[task_id]["status"] = normalized
                now = self._now()
                self._tasks[task_id]["updated_at"] = now
                if normalized in TERMINAL_STATUSES:
                    self._tasks[task_id]["completed_at"] = now
                self._save()

    def request_cancel(self, task_id: str) -> bool:
        with self._lock:
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

    def set_result(self, task_id: str, result: Any) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["result"] = result
                self._tasks[task_id]["updated_at"] = self._now()
                self._save()

    def set_progress(self, task_id: str, pct: int, msg: str) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["progress"] = {"pct": pct, "msg": msg}
                self._tasks[task_id]["updated_at"] = self._now()
                self._save()

    def list_recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            ordered = []
            for tid in reversed(self._order):
                if tid in self._tasks:
                    task = self._tasks[tid]
                    ordered.append(self._public_task(task))
        return ordered[:limit]

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
        if self._storage_path is None or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
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
        self._save()

    def _normalize_loaded_task(self, task_id: str, task: Any) -> Optional[dict]:
        if not isinstance(task, dict):
            return None
        status = self._normalize_status(task.get("status"))
        result = task.get("result")
        logs = task.get("logs") if isinstance(task.get("logs"), list) else []
        if status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            now = self._now()
            status = TaskStatus.ERROR
            logs = list(logs)
            logs.append("⚠️ 服务重启，任务已中断")
            result = {"success": False, "error": "Task interrupted by server restart"}
            task["updated_at"] = now
            task["completed_at"] = now

        progress = task.get("progress")
        if not isinstance(progress, dict):
            progress = {"pct": 0, "msg": ""}
        now = self._now()

        return {
            "id": task.get("id") or task_id,
            "kind": task.get("kind") or "unknown",
            "profile": task.get("profile") or "",
            "status": status,
            "logs": logs,
            "result": result,
            "created_at": task.get("created_at") or now,
            "updated_at": task.get("updated_at") or task.get("created_at") or now,
            "completed_at": task.get("completed_at"),
            "progress": {
                "pct": self._coerce_int(progress.get("pct"), default=0),
                "msg": str(progress.get("msg", "") or ""),
            },
            "cancel_requested": bool(task.get("cancel_requested")),
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

    def _save(self) -> None:
        if self._storage_path is None:
            return

        payload = {
            "version": 1,
            "order": self._order,
            "tasks": self._tasks,
        }
        tmp_name = None
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{self._storage_path.name}.",
                suffix=".tmp",
                dir=str(self._storage_path.parent),
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, self._storage_path)
        except (OSError, TypeError):
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass


def _default_storage_path() -> Optional[Path]:
    env_path = os.getenv("ASC_WEB_TASKS_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / ".config" / "asc" / "web_tasks.json"


# Module-level singleton used by server.py
task_store = TaskStore(_default_storage_path())
