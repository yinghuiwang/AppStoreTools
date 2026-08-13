from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from asc.web.agent_store import AgentStore


def test_reuse_session_per_task_and_plan_lifecycle(tmp_path: Path):
    store = AgentStore(tmp_path / "agent.db")
    try:
        a = store.get_or_create_session("task-1", "myapp")
        b = store.get_or_create_session("task-1", "myapp")
        assert a["id"] == b["id"]
        seq = store.append_message(a["id"], "user", "explain")
        assert seq == 1
        plan_id = store.insert_plan_draft(
            a["id"], turn_seq=1, summary="fix csv", mutations=[{"op": "csv_set_fields"}],
            rerun={"task_id": "task-1", "kind": "metadata"}, manual_steps=[],
        )
        plan = store.get_plan(plan_id)
        assert plan["status"] == "draft"
        ids = store.promote_drafts(a["id"], 1)
        assert ids == [plan_id]
        assert store.get_plan(plan_id)["status"] == "pending"
        claimed = store.claim_pending(plan_id)
        assert claimed is not None
        assert store.claim_pending(plan_id) is None
        store.set_plan_status(plan_id, "applied", new_task_id="new-1")
        assert store.get_plan(plan_id)["new_task_id"] == "new-1"
        listed = store.list_plans(a["id"])
        assert listed[0]["id"] == plan_id
        assert listed[0]["status"] == "applied"
    finally:
        store.close()


def test_abandon_drafts_blocks_claim(tmp_path: Path):
    store = AgentStore(tmp_path / "agent.db")
    try:
        session = store.get_or_create_session("t2", "p")
        plan_id = store.insert_plan_draft(
            session["id"], 1, "x", [{"op": "toml_set"}], None, [],
        )
        store.abandon_drafts(session["id"], 1)
        assert store.get_plan(plan_id)["status"] == "abandoned"
        assert store.claim_pending(plan_id) is None
        assert store.reject_pending(plan_id) is False
    finally:
        store.close()


def test_empty_task_id_creates_new_sessions_and_message_seq(tmp_path: Path):
    store = AgentStore(tmp_path / "agent.db")
    try:
        a = store.get_or_create_session(None, "p")
        b = store.get_or_create_session(None, "p")
        c = store.get_or_create_session("", "p")
        assert len({a["id"], b["id"], c["id"]}) == 3
        assert store.get_session(a["id"])["id"] == a["id"]
        assert store.get_session("missing") is None
        assert store.append_message(a["id"], "user", "hi") == 1
        assert store.append_message(a["id"], "assistant", "yo", tool_name=None) == 2
        messages = store.list_messages(a["id"])
        assert [item["content"] for item in messages] == ["hi", "yo"]
        assert [item["seq"] for item in messages] == [1, 2]
        plan_id = store.insert_plan_draft(a["id"], 1, "s", [], None, ["manual"])
        store.promote_drafts(a["id"], 1)
        assert store.reject_pending(plan_id) is True
        assert store.get_plan(plan_id)["status"] == "rejected"
        filtered = store.list_plans(a["id"], statuses=("rejected",))
        assert [item["id"] for item in filtered] == [plan_id]
        assert store.list_plans(a["id"], statuses=("pending",)) == []
    finally:
        store.close()


def test_agent_store_uses_env_path_and_wal(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "from-env.db"
    monkeypatch.setenv("ASC_WEB_AGENT_PATH", str(db_path))
    store = AgentStore()
    try:
        store.get_or_create_session("t", "p")
        assert db_path.exists()
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        assert mode.lower() == "wal"
    finally:
        store.close()


def test_claim_pending_is_atomic_across_threads(tmp_path: Path):
    import threading

    store = AgentStore(tmp_path / "agent.db")
    try:
        session = store.get_or_create_session("race", "p")
        plan_id = store.insert_plan_draft(session["id"], 1, "x", [{"op": "toml_set"}], None, [])
        store.promote_drafts(session["id"], 1)
        results: list[dict | None] = []

        def _claim() -> None:
            results.append(store.claim_pending(plan_id))

        workers = [threading.Thread(target=_claim) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        assert sum(1 for item in results if item is not None) == 1
        assert sum(1 for item in results if item is None) == 1
        assert store.get_plan(plan_id)["status"] == "applying"
    finally:
        store.close()


def test_list_messages_returns_latest_limited_in_order(tmp_path: Path):
    store = AgentStore(tmp_path / "agent.db")
    try:
        session = store.get_or_create_session("msgs", "p")
        for index in range(1, 6):
            store.append_message(session["id"], "user", f"m{index}")
        listed = store.list_messages(session["id"], limit=3)
        assert [item["content"] for item in listed] == ["m3", "m4", "m5"]
        assert [item["seq"] for item in listed] == [3, 4, 5]
    finally:
        store.close()


def test_server_lifespan_closes_agent_store(monkeypatch):
    from asc.web import server
    from asc.web.tasks import TaskStore

    mock_store = MagicMock()
    monkeypatch.setattr(server, "task_store", TaskStore())
    monkeypatch.setattr(server, "agent_store", mock_store)
    with TestClient(server.create_app()):
        pass
    mock_store.close.assert_called_once()
    source = inspect.getsource(server._lifespan)
    assert "agent_store.close()" in source
