"""In-memory task state store for Web UI background jobs."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Any, Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class TaskStore:
    """Thread-safe in-memory store: task_id → {status, kind, logs, result, created_at}."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._order: list[str] = []
        self._lock = Lock()

    def create(self, kind: str) -> str:
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "kind": kind,
            "status": TaskStatus.PENDING,
            "logs": [],
            "result": None,
            "created_at": datetime.now().isoformat(),
        }
        with self._lock:
            self._tasks[task_id] = task
            self._order.append(task_id)
        return task_id

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            # Return a shallow copy with a copied logs list to prevent external mutation
            result = dict(task)
            result["logs"] = list(task["logs"])
            return result

    def append_log(self, task_id: str, line: str) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["logs"].append(line)

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = status

    def set_result(self, task_id: str, result: Any) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["result"] = result

    def list_recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            ordered = []
            for tid in reversed(self._order):
                if tid in self._tasks:
                    task = self._tasks[tid]
                    copy = dict(task)
                    copy["logs"] = list(task["logs"])
                    ordered.append(copy)
        return ordered[:limit]


# Module-level singleton used by server.py
task_store = TaskStore()
