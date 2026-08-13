from __future__ import annotations

import json

from asc.web.agent_store import AgentStore
from asc.web.tasks import TaskStatus, TaskStore


class ScriptedLLM:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = 0
        self.messages_seen = []
        self.tools_seen = []

    def chat_stream(self, messages, tools, temperature=0.3):
        self.calls += 1
        self.messages_seen.append(messages)
        self.tools_seen.append(tools)
        for event in self.rounds.pop(0):
            yield event


def test_tool_call_pauses_then_forwards_tokens(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    task_id = tasks.create("metadata", profile="myapp")
    tasks.set_status(task_id, TaskStatus.ERROR)
    llm = ScriptedLLM([
        [
            {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "get_task", "arguments": "{\"task_id\":\"" + task_id + "\"}"}}]},
            {"finish_reason": "tool_calls"},
        ],
        [
            {"content": "failed at metadata"},
            {"finish_reason": "stop"},
        ],
    ])
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(agent.run_turn(
        session_id=None, task_id=task_id, message="", auto_analyze=True,
        lang="zh", llm_client=llm,
    ))
    names = [e[0] for e in events]
    assert names[0] == "session"
    assert "tool_start" in names
    assert "tool_result" in names
    assert "token" in names
    assert names[-1] == "done"
    assert llm.calls == 2
    tool_names = {item["function"]["name"] for item in llm.tools_seen[0]}
    assert "apply_fix" not in tool_names
    assert "rerun_task" not in tool_names
    tasks.close()
    agents.close()


def test_hallucinated_apply_does_not_create_task_or_write(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    csv_path = tmp_path / "a.csv"
    csv_path.write_text("locale,name\nen-US,A\n", encoding="utf-8")
    before = csv_path.read_bytes()
    task_id = tasks.create("metadata", profile="myapp")
    tasks.set_status(task_id, TaskStatus.ERROR)
    llm = ScriptedLLM([
        [
            {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "apply_fix", "arguments": "{}"}}]},
            {"finish_reason": "tool_calls"},
        ],
        [{"content": "cannot apply directly", "finish_reason": "stop"}],
    ])
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    list(agent.run_turn(session_id=None, task_id=task_id, message="fix", auto_analyze=False, lang="en", llm_client=llm))
    assert csv_path.read_bytes() == before
    assert len(tasks.list_recent_states(limit=20)) == 1
    tasks.close()
    agents.close()


def test_stop_abandons_draft_and_skips_done(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    replay = {
        "kind": "metadata",
        "profile": "myapp",
        "verbose": False,
        "params": {"csv_path": str(csv_path)},
    }
    task_id = tasks.create("metadata", profile="myapp", replay=replay)
    tasks.set_status(task_id, TaskStatus.ERROR)
    session = agents.get_or_create_session(task_id, "myapp")
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    args = {
        "summary": "truncate keywords",
        "mutations": [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "zh-Hans",
            "fields": {"keywords": "new"},
            "before": {"keywords": "oldkeywords"},
        }],
        "manual_steps": [],
    }

    class StopAfterPropose:
        def __init__(self) -> None:
            self.round = 0

        def chat_stream(self, messages, tools, temperature=0.3):
            self.round += 1
            if self.round == 1:
                yield {
                    "tool_calls": [{
                        "index": 0,
                        "id": "c1",
                        "function": {
                            "name": "propose_fix",
                            "arguments": json.dumps(args),
                        },
                    }]
                }
                yield {"finish_reason": "tool_calls"}
                return
            agent.request_stop(session["id"])
            yield {"content": "should not promote"}
            yield {"finish_reason": "stop"}

    events = list(agent.run_turn(
        session_id=session["id"],
        task_id=task_id,
        message="hi",
        auto_analyze=False,
        lang="zh",
        llm_client=StopAfterPropose(),
    ))
    assert any(name == "stopped" for name, _ in events)
    assert all(name != "done" for name, _ in events)
    plans = agents.list_plans(session["id"])
    assert plans
    assert all(plan["status"] == "abandoned" for plan in plans)
    assert csv_path.read_text(encoding="utf-8") == "locale,keywords\nzh-Hans,oldkeywords\n"
    assert agents.claim_pending(plans[0]["id"]) is None
    tasks.close()
    agents.close()


def test_missing_llm_does_not_construct_http_client(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    task_id = tasks.create("iap", profile="myapp")
    tasks.set_status(task_id, TaskStatus.ERROR)
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(agent.run_turn(
        session_id=None, task_id=task_id, message="", auto_analyze=True,
        lang="zh", llm_client=None,
    ))
    assert events[-1][0] == "error"
    assert "llm_not_configured" in events[-1][1]
    tasks.close()
    agents.close()


def test_redacted_logs_never_reach_llm_messages(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    task_id = tasks.create("metadata", profile="myapp")
    tasks.append_log(task_id, "-----BEGIN PRIVATE KEY-----\nMIIHideMe\n-----END PRIVATE KEY-----")
    tasks.append_log(task_id, "api_key=sk-secret")
    tasks.set_status(task_id, TaskStatus.ERROR)
    llm = ScriptedLLM([
        [
            {
                "tool_calls": [{
                    "index": 0,
                    "id": "c1",
                    "function": {
                        "name": "get_task_log",
                        "arguments": json.dumps({"task_id": task_id}),
                    },
                }]
            },
            {"finish_reason": "tool_calls"},
        ],
        [
            {"content": "the upload failed", "finish_reason": "stop"},
        ],
    ])
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    list(agent.run_turn(
        session_id=None, task_id=task_id, message="", auto_analyze=True,
        lang="en", llm_client=llm,
    ))
    blob = json.dumps(llm.messages_seen)
    assert "BEGIN PRIVATE KEY" not in blob
    assert "MIIHideMe" not in blob
    assert "sk-secret" not in blob
    tasks.close()
    agents.close()


def test_done_promotes_draft_without_writing_csv(tmp_path, monkeypatch):
    from asc.web.agent import WebAgent

    monkeypatch.chdir(tmp_path)
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    before = csv_path.read_bytes()
    replay = {
        "kind": "metadata",
        "profile": "myapp",
        "verbose": False,
        "params": {"csv_path": str(csv_path)},
    }
    task_id = tasks.create("metadata", profile="myapp", replay=replay)
    tasks.set_status(task_id, TaskStatus.ERROR)
    args = {
        "summary": "truncate keywords",
        "mutations": [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "zh-Hans",
            "fields": {"keywords": "new"},
            "before": {"keywords": "oldkeywords"},
        }],
        "manual_steps": [],
    }
    llm = ScriptedLLM([
        [
            {
                "tool_calls": [{
                    "index": 0,
                    "id": "c1",
                    "function": {
                        "name": "propose_fix",
                        "arguments": json.dumps(args),
                    },
                }]
            },
            {"finish_reason": "tool_calls"},
        ],
        [{"content": "please confirm", "finish_reason": "stop"}],
    ])
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(agent.run_turn(
        session_id=None, task_id=task_id, message="fix", auto_analyze=False,
        lang="zh", llm_client=llm,
    ))
    assert events[-1][0] == "done"
    payload = json.loads(events[-1][1])
    assert payload["plan_ids"]
    plan = agents.get_plan(payload["plan_ids"][0])
    assert plan["status"] == "pending"
    assert csv_path.read_bytes() == before
    tasks.close()
    agents.close()

