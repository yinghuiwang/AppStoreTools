"""SQLite store for Web Agent sessions, messages, and gated fix plans."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

PLAN_STATUSES = (
    "draft",
    "pending",
    "applying",
    "applied",
    "rejected",
    "abandoned",
    "apply_failed",
)

_SETTLED_STATUSES = frozenset({"applied", "rejected", "abandoned", "apply_failed"})


def _default_agent_path() -> Path:
    env_path = os.getenv("ASC_WEB_AGENT_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / ".config" / "asc" / "agent_sessions.db"


class AgentStore:
    """SQLite-backed Agent session store. New connection per operation."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else _default_agent_path()
        self._closed = False
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def close(self) -> None:
        self._closed = True

    def _open_configured_connection(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
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
        with self._connection(write=True) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    profile TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    session_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_name TEXT,
                    tool_call_id TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, seq)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_seq INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    mutations_json TEXT NOT NULL DEFAULT '[]',
                    rerun_json TEXT,
                    manual_steps_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    new_task_id TEXT,
                    created_at TEXT NOT NULL,
                    settled_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_task_id ON sessions(task_id)"
            )

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _session_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "profile": row["profile"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _plan_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        rerun_raw = row["rerun_json"]
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "turn_seq": row["turn_seq"],
            "status": row["status"],
            "summary": row["summary"],
            "mutations": json.loads(row["mutations_json"] or "[]"),
            "rerun": json.loads(rerun_raw) if rerun_raw else None,
            "manual_steps": json.loads(row["manual_steps_json"] or "[]"),
            "error": row["error"],
            "new_task_id": row["new_task_id"],
            "created_at": row["created_at"],
            "settled_at": row["settled_at"],
        }

    def _message_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "seq": row["seq"],
            "role": row["role"],
            "content": row["content"],
            "tool_name": row["tool_name"],
            "tool_call_id": row["tool_call_id"],
            "created_at": row["created_at"],
        }

    def get_or_create_session(self, task_id: str | None, profile: str) -> dict:
        lookup_id = task_id if task_id else None
        if lookup_id is not None:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
                    (lookup_id,),
                ).fetchone()
            if row is not None:
                return self._session_from_row(row)
        session_id = str(uuid.uuid4())
        now = self._now()
        with self._connection(write=True) as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, task_id, profile, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, lookup_id, profile, now, now),
            )
        return {
            "id": session_id,
            "task_id": lookup_id,
            "profile": profile,
            "created_at": now,
            "updated_at": now,
        }

    def get_session(self, session_id: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._session_from_row(row)

    def list_messages(self, session_id: str, limit: int = 20) -> list[dict]:
        if limit <= 0:
            return []
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT * FROM messages
                    WHERE session_id = ?
                    ORDER BY seq DESC
                    LIMIT ?
                ) AS recent
                ORDER BY seq ASC
                """,
                (session_id, int(limit)),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
    ) -> int:
        now = self._now()
        with self._connection(write=True) as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            seq = int(row["max_seq"]) + 1
            conn.execute(
                """
                INSERT INTO messages (
                    session_id, seq, role, content, tool_name, tool_call_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, seq, role, content, tool_name, tool_call_id, now),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        return seq

    def list_plans(
        self,
        session_id: str,
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> list[dict]:
        with self._connection() as conn:
            if statuses:
                placeholders = ",".join("?" for _ in statuses)
                rows = conn.execute(
                    f"""
                    SELECT * FROM plans
                    WHERE session_id = ? AND status IN ({placeholders})
                    ORDER BY created_at ASC, id ASC
                    """,
                    (session_id, *statuses),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM plans
                    WHERE session_id = ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (session_id,),
                ).fetchall()
        return [self._plan_from_row(row) for row in rows]

    def insert_plan_draft(
        self,
        session_id: str,
        turn_seq: int,
        summary: str,
        mutations: list,
        rerun: dict | None,
        manual_steps: list,
    ) -> str:
        plan_id = str(uuid.uuid4())
        now = self._now()
        with self._connection(write=True) as conn:
            conn.execute(
                """
                INSERT INTO plans (
                    id, session_id, turn_seq, status, summary,
                    mutations_json, rerun_json, manual_steps_json,
                    error, new_task_id, created_at, settled_at
                ) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, NULL, NULL, ?, NULL)
                """,
                (
                    plan_id,
                    session_id,
                    int(turn_seq),
                    summary,
                    json.dumps(list(mutations), ensure_ascii=False),
                    json.dumps(rerun, ensure_ascii=False) if rerun is not None else None,
                    json.dumps(list(manual_steps), ensure_ascii=False),
                    now,
                ),
            )
        return plan_id

    def promote_drafts(self, session_id: str, turn_seq: int) -> list[str]:
        with self._connection(write=True) as conn:
            rows = conn.execute(
                """
                SELECT id FROM plans
                WHERE session_id = ? AND turn_seq = ? AND status = 'draft'
                ORDER BY created_at ASC, id ASC
                """,
                (session_id, int(turn_seq)),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                conn.execute(
                    """
                    UPDATE plans SET status = 'pending'
                    WHERE session_id = ? AND turn_seq = ? AND status = 'draft'
                    """,
                    (session_id, int(turn_seq)),
                )
        return ids

    def abandon_drafts(self, session_id: str, turn_seq: int) -> int:
        now = self._now()
        with self._connection(write=True) as conn:
            cursor = conn.execute(
                """
                UPDATE plans
                SET status = 'abandoned', settled_at = ?
                WHERE session_id = ? AND turn_seq = ? AND status = 'draft'
                """,
                (now, session_id, int(turn_seq)),
            )
            return int(cursor.rowcount)

    def get_plan(self, plan_id: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        return self._plan_from_row(row)

    def claim_pending(self, plan_id: str) -> dict | None:
        with self._connection(write=True) as conn:
            cursor = conn.execute(
                "UPDATE plans SET status = 'applying' WHERE id = ? AND status = 'pending'",
                (plan_id,),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute(
                "SELECT * FROM plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        return self._plan_from_row(row)

    def set_plan_status(
        self,
        plan_id: str,
        status: str,
        *,
        error: str | None = None,
        new_task_id: str | None = None,
    ) -> None:
        if status not in PLAN_STATUSES:
            raise ValueError(f"invalid plan status: {status}")
        assignments = ["status = ?"]
        params: list[Any] = [status]
        if error is not None:
            assignments.append("error = ?")
            params.append(error)
        if new_task_id is not None:
            assignments.append("new_task_id = ?")
            params.append(new_task_id)
        if status in _SETTLED_STATUSES:
            assignments.append("settled_at = ?")
            params.append(self._now())
        params.append(plan_id)
        with self._connection(write=True) as conn:
            conn.execute(
                f"UPDATE plans SET {', '.join(assignments)} WHERE id = ?",
                params,
            )

    def reject_pending(self, plan_id: str) -> bool:
        now = self._now()
        with self._connection(write=True) as conn:
            cursor = conn.execute(
                """
                UPDATE plans
                SET status = 'rejected', settled_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, plan_id),
            )
            return cursor.rowcount == 1


agent_store = AgentStore()
