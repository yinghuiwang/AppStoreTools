from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from asc.web.agent_store import AgentStore
from asc.web.agent_tools import (
    MODEL_TOOL_NAMES,
    OPENAI_TOOLS,
    AgentToolContext,
    execute_model_tool,
)
from asc.web.tasks import TaskStore
from tests.test_web_agent import ScriptedLLM


def _ctx(tmp_path: Path, agents: AgentStore, session_id: str) -> AgentToolContext:
    tasks = TaskStore(tmp_path / "tasks.db")
    return AgentToolContext(
        task_store=tasks,
        agent_store=agents,
        bound_task_id=None,
        project_root=tmp_path,
        turn_seq=1,
        session_id=session_id,
    )


def test_store_workflow_column_and_get_set_default(tmp_path: Path):
    store = AgentStore(tmp_path / "agent.db")
    try:
        session = store.get_or_create_session(None, "p")
        conn = sqlite3.connect(str(tmp_path / "agent.db"))
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        finally:
            conn.close()
        assert "workflow_json" in cols
        assert store.get_workflow(session["id"]) == {"phase": "idle"}
        assert store.get_workflow("missing") == {"phase": "idle"}

        saved = store.set_workflow(
            session["id"],
            {
                "phase": "awaiting_choice",
                "kind": "listing",
                "prompt": "Pick a plan",
                "options": [{"id": "opt_1", "label": "Premium", "description": "best"}],
                "selected_id": None,
                "extra": "drop-me",
            },
        )
        assert saved["phase"] == "awaiting_choice"
        assert saved["kind"] == "listing"
        assert saved["prompt"] == "Pick a plan"
        assert saved["options"][0]["id"] == "opt_1"
        assert saved["selected_id"] is None
        assert "extra" not in saved
        assert saved.get("updated_at")
        got = store.get_workflow(session["id"])
        assert got["phase"] == "awaiting_choice"
        assert got["kind"] == "listing"
        assert got["options"][0]["label"] == "Premium"
    finally:
        store.close()


def test_offer_choices_validation_and_pending(tmp_path: Path):
    agents = AgentStore(tmp_path / "agent.db")
    try:
        session = agents.get_or_create_session(None, "p")
        ctx = _ctx(tmp_path, agents, session["id"])
        csv_path = tmp_path / "appstore_info.csv"
        csv_path.write_text("locale,name\nen-US,App\n", encoding="utf-8")
        before = csv_path.read_bytes()

        one = execute_model_tool(
            ctx,
            "offer_choices",
            {"prompt": "Pick", "options": [{"label": "Only"}]},
        )
        assert one["ok"] is False

        thirteen = execute_model_tool(
            ctx,
            "offer_choices",
            {
                "prompt": "Pick",
                "options": [{"label": f"N{i}"} for i in range(13)],
            },
        )
        assert thirteen["ok"] is False

        empty_prompt = execute_model_tool(
            ctx,
            "offer_choices",
            {"prompt": "  ", "options": [{"label": "A"}, {"label": "B"}]},
        )
        assert empty_prompt["ok"] is False

        ok = execute_model_tool(
            ctx,
            "offer_choices",
            {
                "prompt": "Pick a plan",
                "kind": "listing",
                "options": [{"label": "Premium"}, {"id": "custom", "label": "Basic"}],
            },
        )
        assert ok == {
            "ok": True,
            "status": "pending",
            "option_count": 2,
            "phase": "awaiting_choice",
        }
        workflow = agents.get_workflow(session["id"])
        assert workflow["phase"] == "awaiting_choice"
        assert workflow["kind"] == "listing"
        assert workflow["selected_id"] is None
        assert workflow["options"][0]["id"] == "opt_1"
        assert workflow["options"][1]["id"] == "custom"
        assert csv_path.read_bytes() == before
        assert execute_model_tool(ctx, "choose", {"option_id": "opt_1"})["ok"] is False
    finally:
        ctx.task_store.close()
        agents.close()


def test_set_workflow_requires_existing_options_for_awaiting(tmp_path: Path):
    agents = AgentStore(tmp_path / "agent.db")
    try:
        session = agents.get_or_create_session(None, "p")
        ctx = _ctx(tmp_path, agents, session["id"])
        missing = execute_model_tool(ctx, "set_workflow", {"phase": "awaiting_choice"})
        assert missing["ok"] is False
        collecting = execute_model_tool(ctx, "set_workflow", {"phase": "collecting", "kind": "iap"})
        assert collecting == {"ok": True, "phase": "collecting", "kind": "iap"}
        execute_model_tool(
            ctx,
            "offer_choices",
            {"prompt": "Pick", "options": [{"label": "A"}, {"label": "B"}]},
        )
        again = execute_model_tool(ctx, "set_workflow", {"phase": "awaiting_choice"})
        assert again["ok"] is True
        assert again["phase"] == "awaiting_choice"
    finally:
        ctx.task_store.close()
        agents.close()


def test_apply_choice_happy_and_conflict(tmp_path: Path):
    from asc.web.agent_workflow import apply_choice

    agents = AgentStore(tmp_path / "agent.db")
    try:
        session = agents.get_or_create_session(None, "p")
        idle = apply_choice(agents, session["id"], "opt_1")
        assert idle == {"ok": False, "code": "conflict"}

        ctx = _ctx(tmp_path, agents, session["id"])
        execute_model_tool(
            ctx,
            "offer_choices",
            {
                "prompt": "Pick",
                "kind": "iap",
                "options": [{"label": "Monthly"}, {"label": "Yearly"}],
            },
        )
        missing = apply_choice(agents, session["id"], "nope")
        assert missing == {"ok": False, "code": "conflict"}
        happy = apply_choice(agents, session["id"], "opt_1")
        assert happy["ok"] is True
        assert happy["prompt"].startswith("[choice] kind=iap id=opt_1 label=Monthly")
        assert "Continue the workflow from this confirmed choice. Do not re-ask these options." in happy["prompt"]
        workflow = agents.get_workflow(session["id"])
        assert workflow["phase"] == "confirmed"
        assert workflow["selected_id"] == "opt_1"
        again = apply_choice(agents, session["id"], "opt_1")
        assert again == {"ok": False, "code": "conflict"}
    finally:
        ctx.task_store.close()
        agents.close()


def test_choose_route_requires_confirm_and_conflicts(tmp_path, monkeypatch):
    from asc.web.server import create_app
    from tests.test_web_agent_routes import _isolate_agent_store, _isolate_task_store

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    _isolate_task_store(monkeypatch, tasks)
    _isolate_agent_store(monkeypatch, agents)
    session = agents.get_or_create_session(None, "p")
    ctx = _ctx(tmp_path, agents, session["id"])
    execute_model_tool(
        ctx,
        "offer_choices",
        {"prompt": "Pick", "options": [{"label": "A"}, {"label": "B"}]},
    )
    client = TestClient(create_app())
    no_confirm = client.post(
        "/api/agent/choose",
        json={"session_id": session["id"], "option_id": "opt_1"},
    )
    assert no_confirm.status_code == 400
    ok = client.post(
        "/api/agent/choose",
        json={"session_id": session["id"], "option_id": "opt_1", "confirm": True},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    assert "[choice]" in body["prompt"]
    conflict = client.post(
        "/api/agent/choose",
        json={"session_id": session["id"], "option_id": "opt_1", "confirm": True},
    )
    assert conflict.status_code == 409
    shown = client.get(f"/api/agent/sessions?session_id={session['id']}")
    assert shown.status_code == 200
    workflow = shown.json()["session"]["workflow"]
    assert workflow["phase"] == "confirmed"
    assert workflow["selected_id"] == "opt_1"
    ctx.task_store.close()
    tasks.close()
    agents.close()


def test_run_turn_injects_workflow_into_system_not_sqlite(tmp_path: Path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    session = agents.get_or_create_session(None, "p")
    agents.set_workflow(
        session["id"],
        {
            "phase": "awaiting_choice",
            "kind": "listing",
            "prompt": "Pick a plan",
            "options": [
                {"id": "opt_1", "label": "Premium long label that should be truncated past forty"},
                {"id": "opt_2", "label": "Basic"},
            ],
        },
    )
    llm = ScriptedLLM([[{"content": "ok", "finish_reason": "stop"}]])
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(
        agent.run_turn(
            session_id=session["id"],
            task_id=None,
            message="hello",
            auto_analyze=False,
            lang="en",
            llm_client=llm,
        )
    )
    system = llm.messages_seen[0][0]["content"]
    assert llm.messages_seen[0][0]["role"] == "system"
    assert "[workflow]" in system
    assert "phase=awaiting_choice" in system
    assert "kind=listing" in system
    assert "opt_1:" in system or "opt_1=" in system
    assert "Premium long label that should be truncated past forty" not in system
    assert "offer_choices" in system
    assert "set_workflow" in system
    assert "listing 10 options as plain text" in system
    assert "choose" in system
    stored = " ".join(row["content"] for row in agents.list_messages(session["id"]))
    assert "[workflow]" not in stored
    done = json.loads(events[-1][1])
    assert events[-1][0] == "done"
    assert done["workflow"]["phase"] == "awaiting_choice"
    tool_names = {item["function"]["name"] for item in llm.tools_seen[0]}
    assert "offer_choices" in tool_names
    assert "set_workflow" in tool_names
    assert "choose" not in tool_names
    assert "apply_fix" not in tool_names
    tasks.close()
    agents.close()


def test_offer_choices_emits_choices_sse_and_agui_activity(tmp_path: Path):
    from asc.web.agent import WebAgent
    from asc.web.agent_agui import translate_legacy_events

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    llm = ScriptedLLM(
        [
            [
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "c1",
                            "function": {
                                "name": "offer_choices",
                                "arguments": json.dumps(
                                    {
                                        "prompt": "Pick",
                                        "kind": "generic",
                                        "options": [{"label": "A"}, {"label": "B"}],
                                    }
                                ),
                            },
                        }
                    ]
                },
                {"finish_reason": "tool_calls"},
            ],
            [{"content": "please pick", "finish_reason": "stop"}],
        ]
    )
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(
        agent.run_turn(
            session_id=None,
            task_id=None,
            message="help me choose",
            auto_analyze=False,
            lang="en",
            llm_client=llm,
        )
    )
    names = [item[0] for item in events]
    assert "choices" in names
    assert names.index("choices") > names.index("tool_result")
    payload = json.loads(next(data for name, data in events if name == "choices"))
    assert payload["phase"] == "awaiting_choice"
    assert len(payload["options"]) == 2

    agui = list(translate_legacy_events(events, run_id="run-choice"))
    activity = next(
        item
        for item in agui
        if item.get("type") == "ACTIVITY_SNAPSHOT"
        and item.get("activityType") == "offer_choices"
    )
    assert activity["content"]["phase"] == "awaiting_choice"
    tasks.close()
    agents.close()


def test_model_tool_names_include_workflow_not_choose():
    names = {item["function"]["name"] for item in OPENAI_TOOLS}
    assert "offer_choices" in MODEL_TOOL_NAMES
    assert "set_workflow" in MODEL_TOOL_NAMES
    assert "choose" not in MODEL_TOOL_NAMES
    assert "apply_choice" not in MODEL_TOOL_NAMES
    assert names == set(MODEL_TOOL_NAMES)
