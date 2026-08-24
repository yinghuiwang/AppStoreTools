from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from asc.web.server import create_app
from asc.web.tasks import TaskStore
from tests.test_web_agent_routes import _isolate_agent_store, _isolate_task_store


def test_update_run_rejects_without_confirm():
    client = TestClient(create_app())
    with patch("asc.web.routes_api._start_update_task") as start:
        resp = client.post("/api/update/run", data={"version": "0.1.27"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "confirm is required"
    start.assert_not_called()


def test_update_run_starts_after_confirm():
    client = TestClient(create_app())
    with patch("asc.web.routes_api._start_update_task", return_value="upd-1") as start:
        resp = client.post(
            "/api/update/run",
            data={"version": "0.1.27", "confirm": "true"},
        )
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "upd-1"
    start.assert_called_once()


def test_guard_manual_bind_rejects_without_confirm():
    client = TestClient(create_app())
    with patch("asc.guard.Guard") as guard_cls:
        resp = client.post(
            "/api/guard/manual-bind",
            data={"fingerprint": "SERIAL-A", "profile": "myapp"},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "confirm is required"
    guard_cls.assert_not_called()


def test_agent_apply_rejects_without_confirm(tmp_path, monkeypatch):
    from asc.web.agent_store import AgentStore

    store = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    _isolate_task_store(monkeypatch, store)
    _isolate_agent_store(monkeypatch, agents)
    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    task_id = store.create("metadata", profile="myapp")
    session = agents.get_or_create_session(task_id, "myapp")
    plan_id = agents.insert_plan_draft(
        session["id"],
        1,
        "fix",
        [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "zh-Hans",
            "fields": {"keywords": "new"},
            "before": {"keywords": "oldkeywords"},
        }],
        None,
        [],
    )
    agents.promote_drafts(session["id"], 1)
    client = TestClient(create_app())
    resp = client.post("/api/agent/apply", json={"plan_id": plan_id, "rerun": False})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "confirm is required"
    assert "oldkeywords" in csv_path.read_text(encoding="utf-8")
    store.close()
    agents.close()
