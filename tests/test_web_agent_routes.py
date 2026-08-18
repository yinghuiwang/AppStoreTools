from __future__ import annotations

import json
import threading
from unittest.mock import patch

from fastapi.testclient import TestClient

from asc.web import routes_agent, routes_api, routes_listing  # noqa: F401
from asc.web.server import create_app
from asc.web.tasks import TaskStatus, TaskStore


def _isolate_task_store(monkeypatch, store: TaskStore) -> None:
    """Patch every module-level TaskStore alias for one test."""
    monkeypatch.setattr("asc.web.tasks.task_store", store)
    monkeypatch.setattr("asc.web.server.task_store", store)
    monkeypatch.setattr("asc.web.routes_api._task_store", store)
    monkeypatch.setattr("asc.web.routes_listing.task_store", store)


def _isolate_agent_store(monkeypatch, agents) -> None:
    monkeypatch.setattr("asc.web.agent_store.agent_store", agents)
    monkeypatch.setattr("asc.web.routes_agent.agent_store", agents)


def test_agent_stream_is_sse_and_task_stream_still_exists(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    _isolate_task_store(monkeypatch, store)
    task_id = store.create("metadata", profile="myapp")
    store.set_status(task_id, TaskStatus.ERROR)

    def fake_turn(**kwargs):
        yield ("session", '{"session_id":"s1","task_id":"%s"}' % task_id)
        yield ("token", "hello")
        yield ("done", '{"session_id":"s1","plan_ids":[]}')

    monkeypatch.setattr("asc.web.agent.WebAgent.run_turn", lambda self, **k: fake_turn())
    monkeypatch.setattr("asc.config.Config.get_active_llm_config", lambda self: {"api_key": "k", "base_url": "http://x", "model": "m"})
    client = TestClient(create_app())
    resp = client.post("/api/agent/stream", json={"task_id": task_id, "auto_analyze": True, "message": ""})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    for name in ("session", "token", "done"):
        assert f"event: {name}" in body
    assert "event: log" not in body
    task_stream = client.get(f"/api/task/{task_id}/stream")
    assert task_stream.status_code == 200
    store.close()


def test_agent_agui_streams_each_visible_token_as_text_content(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    _isolate_task_store(monkeypatch, store)
    task_id = store.create("metadata", profile="myapp")
    store.set_status(task_id, TaskStatus.ERROR)

    def fake_turn(**kwargs):
        yield ("session", '{"session_id":"s1","task_id":"%s"}' % task_id)
        yield ("token", "Hel")
        yield ("token", "lo")
        yield ("token", " world")
        yield ("done", '{"session_id":"s1","plan_ids":[]}')

    monkeypatch.setattr("asc.web.agent.WebAgent.run_turn", lambda self, **k: fake_turn())
    monkeypatch.setattr(
        "asc.config.Config.get_active_llm_config",
        lambda self: {"api_key": "k", "base_url": "http://x", "model": "m"},
    )
    client = TestClient(create_app())
    resp = client.post(
        "/api/agent/agui",
        json={"task_id": task_id, "prompt": "hi"},
    )
    assert resp.status_code == 200
    frames = [
        line[5:].strip()
        for line in resp.text.splitlines()
        if line.startswith("data:") and line[5:].strip()
    ]
    payloads = [json.loads(frame) for frame in frames]
    deltas = [
        str(item.get("delta") or "")
        for item in payloads
        if item.get("type") == "TEXT_MESSAGE_CONTENT"
    ]
    assert deltas == ["Hel", "lo", " world"]
    assert any(item.get("type") == "TEXT_MESSAGE_START" for item in payloads)
    assert any(item.get("type") == "TEXT_MESSAGE_END" for item in payloads)
    store.close()


def test_agent_agui_is_sse_and_uses_official_event_types(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    _isolate_task_store(monkeypatch, store)
    task_id = store.create("metadata", profile="myapp")
    store.set_status(task_id, TaskStatus.ERROR)

    def fake_turn(**kwargs):
        yield ("session", '{"session_id":"s1","task_id":"%s"}' % task_id)
        yield ("token", "<think>plan</think>hello")
        yield ("done", '{"session_id":"s1","plan_ids":[]}')

    monkeypatch.setattr("asc.web.agent.WebAgent.run_turn", lambda self, **k: fake_turn())
    monkeypatch.setattr(
        "asc.config.Config.get_active_llm_config",
        lambda self: {"api_key": "k", "base_url": "http://x", "model": "m"},
    )
    client = TestClient(create_app())
    resp = client.post(
        "/api/agent/agui",
        json={"task_id": task_id, "prompt": "hi", "auto_analyze": True},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "RUN_STARTED" in body
    assert "THINKING_TEXT_MESSAGE_CONTENT" in body
    assert "TEXT_MESSAGE_CONTENT" in body
    assert "RUN_FINISHED" in body
    assert "event: token" not in body
    store.close()


def test_failed_tasks_excludes_canceled_and_done(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    _isolate_task_store(monkeypatch, store)
    e = store.create("iap", profile="a")
    store.set_status(e, TaskStatus.ERROR)
    d = store.create("iap", profile="a")
    store.set_status(d, TaskStatus.DONE)
    c = store.create("iap", profile="a")
    store.set_status(c, TaskStatus.CANCELED)
    client = TestClient(create_app())
    rows = client.get("/api/agent/failed-tasks").json()["tasks"]
    ids = [row["id"] for row in rows]
    assert e in ids
    assert d not in ids
    assert c not in ids
    store.close()


def test_apply_draft_conflict_and_pending_success(tmp_path, monkeypatch):
    from asc.web.agent_store import AgentStore
    from asc.web.server import create_app

    store = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    _isolate_task_store(monkeypatch, store)
    _isolate_agent_store(monkeypatch, agents)
    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    task_id = store.create(
        "metadata",
        profile="myapp",
        replay={"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}},
    )
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
        {"task_id": task_id, "kind": "metadata"},
        [],
    )
    client = TestClient(create_app())
    shown = client.get(f"/api/agent/plans/{plan_id}").json()
    assert shown["status"] == "draft"
    assert client.post("/api/agent/apply", json={"plan_id": plan_id, "rerun": False}).status_code == 409
    empty_id = agents.insert_plan_draft(session["id"], 1, "manual", [], None, ["do it yourself"])
    agents.promote_drafts(session["id"], 1)
    assert client.post("/api/agent/apply", json={"plan_id": empty_id, "rerun": False}).status_code == 400
    ok = client.post("/api/agent/apply", json={"plan_id": plan_id, "rerun": False})
    assert ok.status_code == 200
    assert "new" in csv_path.read_text(encoding="utf-8")
    store.close()
    agents.close()


def test_concurrent_apply_one_409(tmp_path, monkeypatch):
    from asc.web.agent_store import AgentStore
    from asc.web.server import create_app

    store = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    _isolate_task_store(monkeypatch, store)
    _isolate_agent_store(monkeypatch, agents)
    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    task_id = store.create(
        "metadata",
        profile="myapp",
        replay={"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}},
    )
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
    codes: list[int] = []

    def _post():
        codes.append(client.post("/api/agent/apply", json={"plan_id": plan_id, "rerun": False}).status_code)

    t1 = threading.Thread(target=_post)
    t2 = threading.Thread(target=_post)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert sorted(codes) == [200, 409]
    store.close()
    agents.close()


def test_stream_without_ids_creates_session(tmp_path, monkeypatch):
    from asc.web.agent_store import AgentStore

    store = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    _isolate_task_store(monkeypatch, store)
    _isolate_agent_store(monkeypatch, agents)
    captured = {}

    def fake_turn(self, **kwargs):
        captured.update(kwargs)
        yield ("session", '{"session_id":"free-1","task_id":null}')
        yield ("token", "hello")
        yield ("done", '{"session_id":"free-1","plan_ids":[]}')

    monkeypatch.setattr("asc.web.agent.WebAgent.run_turn", fake_turn)
    monkeypatch.setattr(
        "asc.config.Config.get_active_llm_config",
        lambda self: {"api_key": "k", "base_url": "http://x", "model": "m"},
    )
    client = TestClient(create_app())
    resp = client.post(
        "/api/agent/stream",
        json={"message": "hello", "auto_analyze": False},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert captured.get("task_id") in (None, "")
    assert captured.get("session_id") in (None, "")
    assert captured.get("auto_analyze") is False
    assert captured.get("message") == "hello"
    assert "event: session" in resp.text
    store.close()
    agents.close()


def test_sessions_by_session_id_and_missing_ids(tmp_path, monkeypatch):
    from asc.web.agent_store import AgentStore

    store = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    _isolate_task_store(monkeypatch, store)
    _isolate_agent_store(monkeypatch, agents)
    session = agents.get_or_create_session(None, "")
    agents.append_message(session["id"], "user", "hi")
    client = TestClient(create_app())
    listed = client.get("/api/agent/sessions")
    assert listed.status_code == 200
    rows = listed.json()["sessions"]
    assert any(row["id"] == session["id"] and row["title"] == "hi" for row in rows)
    missing = client.get("/api/agent/sessions?session_id=does-not-exist")
    assert missing.status_code == 404
    ok = client.get(f"/api/agent/sessions?session_id={session['id']}")
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["session"]["id"] == session["id"]
    assert payload["session"]["task_id"] is None
    assert [row["content"] for row in payload["messages"]] == ["hi"]
    created = client.post("/api/agent/sessions", json={})
    assert created.status_code == 200
    new_session = created.json()["session"]
    assert new_session["id"] != session["id"]
    assert created.json()["messages"] == []
    assert created.json()["plans"] == []
    newest = client.get("/api/agent/sessions").json()["sessions"]
    assert newest[0]["id"] == new_session["id"]
    store.close()
    agents.close()


def test_reject_non_pending_is_409(tmp_path, monkeypatch):
    from asc.web.agent_store import AgentStore

    store = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    _isolate_task_store(monkeypatch, store)
    _isolate_agent_store(monkeypatch, agents)
    task_id = store.create("iap", profile="myapp")
    session = agents.get_or_create_session(task_id, "myapp")
    plan_id = agents.insert_plan_draft(
        session["id"], 1, "manual", [], None, ["do it yourself"],
    )
    client = TestClient(create_app())
    shown = client.get(f"/api/agent/plans/{plan_id}").json()
    assert "status" in shown
    assert shown["status"] == "draft"
    assert client.post("/api/agent/reject", json={"plan_id": plan_id}).status_code == 409
    agents.promote_drafts(session["id"], 1)
    ok = client.post("/api/agent/reject", json={"plan_id": plan_id})
    assert ok.status_code == 200
    assert client.post("/api/agent/reject", json={"plan_id": plan_id}).status_code == 409
    store.close()
    agents.close()


def test_stream_missing_llm_does_not_instantiate_client(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    _isolate_task_store(monkeypatch, store)
    task_id = store.create("iap", profile="myapp")
    store.set_status(task_id, TaskStatus.ERROR)

    def fake_turn(**kwargs):
        assert kwargs.get("llm_client") is None
        yield ("session", '{"session_id":"s1","task_id":"%s"}' % task_id)
        yield ("error", '{"code":"llm_not_configured","message":"missing"}')

    monkeypatch.setattr("asc.web.agent.WebAgent.run_turn", lambda self, **k: fake_turn(**k))
    monkeypatch.setattr("asc.config.Config.get_active_llm_config", lambda self: None)
    with patch("asc.llm.LLMClient") as llm_cls:
        client = TestClient(create_app())
        resp = client.post(
            "/api/agent/stream",
            json={"task_id": task_id, "auto_analyze": True, "message": ""},
        )
        assert resp.status_code == 200
        llm_cls.assert_not_called()
    store.close()
