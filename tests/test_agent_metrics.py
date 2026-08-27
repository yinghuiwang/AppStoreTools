from __future__ import annotations

import json
from unittest.mock import patch

import requests_mock as rm

from asc.web.agent_store import AgentStore
from asc.web.tasks import TaskStore


class ScriptedLLM:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = 0

    def chat_stream(self, messages, tools, temperature=0.3):
        self.calls += 1
        for event in self.rounds.pop(0):
            yield event


def test_llm_client_default_timeout_is_180():
    from asc.llm import LLMClient

    client = LLMClient(api_key="k", base_url="https://api.openai.com/v1", model="gpt-4o")
    assert client.timeout == 180


def test_llm_client_constructor_timeout_is_honored():
    from asc.llm import LLMClient

    client = LLMClient(
        api_key="k", base_url="https://api.openai.com/v1", model="gpt-4o", timeout=90
    )
    assert client.timeout == 90


def test_chat_stream_yields_usage_and_not_as_content():
    from asc.llm import LLMClient

    sse = (
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":10,"completion_tokens":4,"total_tokens":14}}\n\n'
        "data: [DONE]\n\n"
    )
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            text=sse,
            headers={"Content-Type": "text/event-stream"},
        )
        client = LLMClient(api_key="k", base_url="https://api.openai.com/v1", model="gpt-4o")
        events = list(client.chat_stream([{"role": "user", "content": "hi"}], tools=[]))
    contents = [e.get("content") for e in events if e.get("content")]
    assert contents == ["Hello"]
    usage_events = [e["usage"] for e in events if e.get("usage")]
    assert usage_events == [{"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}]
    assert all("usage" not in (e.get("content") or "") for e in events)


def test_chat_stream_yields_usage_only_chunk():
    from asc.llm import LLMClient

    sse = (
        'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
        'data: {"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4},"choices":[]}\n\n'
        "data: [DONE]\n\n"
    )
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            text=sse,
            headers={"Content-Type": "text/event-stream"},
        )
        client = LLMClient(api_key="k", base_url="https://api.openai.com/v1", model="gpt-4o")
        events = list(client.chat_stream([{"role": "user", "content": "hi"}], tools=[]))
    assert any(e.get("content") == "Hi" for e in events)
    assert any(e.get("usage", {}).get("total_tokens") == 4 for e in events)


def _client_timeout(monkeypatch, cfg, env=None):
    monkeypatch.delenv("ASC_LLM_TIMEOUT", raising=False)
    if env is not None:
        monkeypatch.setenv("ASC_LLM_TIMEOUT", str(env))
    monkeypatch.setattr(
        "asc.config.Config.get_active_llm_config",
        lambda self: cfg,
    )
    from asc.web.routes_agent import _llm_client_or_none

    return _llm_client_or_none()


def test_llm_client_or_none_timeout_from_cfg(monkeypatch):
    client = _client_timeout(
        monkeypatch,
        {"api_key": "k", "base_url": "http://x", "model": "m", "timeout": 120},
    )
    assert client is not None
    assert client.timeout == 120


def test_llm_client_or_none_timeout_from_env(monkeypatch):
    client = _client_timeout(
        monkeypatch,
        {"api_key": "k", "base_url": "http://x", "model": "m"},
        env=90,
    )
    assert client is not None
    assert client.timeout == 90


def test_llm_client_or_none_timeout_defaults_to_180(monkeypatch):
    client = _client_timeout(
        monkeypatch,
        {"api_key": "k", "base_url": "http://x", "model": "m"},
    )
    assert client is not None
    assert client.timeout == 180


def test_llm_client_or_none_timeout_clamped(monkeypatch):
    low = _client_timeout(
        monkeypatch,
        {"api_key": "k", "base_url": "http://x", "model": "m", "timeout": 10},
    )
    assert low.timeout == 30
    high = _client_timeout(
        monkeypatch,
        {"api_key": "k", "base_url": "http://x", "model": "m", "timeout": 999},
    )
    assert high.timeout == 600


def test_run_turn_done_includes_elapsed_and_tool_batches(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    llm = ScriptedLLM([[{"content": "ok"}, {"finish_reason": "stop"}]])
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(
        agent.run_turn(
            session_id=None,
            task_id=None,
            message="hi",
            auto_analyze=False,
            lang="en",
            llm_client=llm,
        )
    )
    assert events[-1][0] == "done"
    payload = json.loads(events[-1][1])
    assert isinstance(payload["elapsed_ms"], int)
    assert payload["elapsed_ms"] >= 0
    assert payload["tool_batches"] == 0
    assert "usage" not in payload
    tokens = [text for name, text in events if name == "token"]
    assert tokens == ["ok"]
    session_id = json.loads(events[0][1])["session_id"]
    stored = agents.list_messages(session_id)
    assistant = [row["content"] for row in stored if row["role"] == "assistant"]
    assert assistant == ["ok"]
    tasks.close()
    agents.close()


def test_run_turn_done_usage_ints_only_and_not_in_text(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    llm = ScriptedLLM(
        [
            [
                {"content": "hello"},
                {
                    "usage": {
                        "prompt_tokens": "11",
                        "completion_tokens": 5,
                        "total_tokens": 16,
                        "ignored": "x",
                        "prompt_tokens_details": {"cached_tokens": 1},
                    }
                },
                {"finish_reason": "stop"},
            ]
        ]
    )
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(
        agent.run_turn(
            session_id=None,
            task_id=None,
            message="hi",
            auto_analyze=False,
            lang="en",
            llm_client=llm,
        )
    )
    payload = json.loads(events[-1][1])
    assert payload["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 5,
        "total_tokens": 16,
    }
    assert all(isinstance(v, int) for v in payload["usage"].values())
    tokens = [text for name, text in events if name == "token"]
    assert tokens == ["hello"]
    session_id = json.loads(events[0][1])["session_id"]
    assistant = [
        row["content"]
        for row in agents.list_messages(session_id)
        if row["role"] == "assistant"
    ]
    assert assistant == ["hello"]
    assert all("prompt_tokens" not in text for text in assistant)
    tasks.close()
    agents.close()


def test_run_turn_keeps_last_usage_and_counts_tool_batches(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    llm = ScriptedLLM(
        [
            [
                {
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    }
                },
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "c1",
                            "function": {"name": "list_plans", "arguments": "{}"},
                        }
                    ]
                },
                {"finish_reason": "tool_calls"},
            ],
            [
                {"content": "done"},
                {
                    "usage": {
                        "prompt_tokens": 8,
                        "completion_tokens": 3,
                        "total_tokens": 11,
                    }
                },
                {"finish_reason": "stop"},
            ],
        ]
    )
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(
        agent.run_turn(
            session_id=None,
            task_id=None,
            message="hi",
            auto_analyze=False,
            lang="en",
            llm_client=llm,
        )
    )
    payload = json.loads(events[-1][1])
    assert payload["tool_batches"] == 1
    assert payload["usage"] == {
        "prompt_tokens": 8,
        "completion_tokens": 3,
        "total_tokens": 11,
    }
    tasks.close()
    agents.close()


def test_tool_limit_done_includes_metrics(tmp_path, monkeypatch):
    from asc.web import agent as agent_mod
    from asc.web.agent import WebAgent

    monkeypatch.setattr(agent_mod, "AGENT_TOOL_LOOP_MAX", 1)
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
                            "function": {"name": "list_plans", "arguments": "{}"},
                        }
                    ]
                },
                {
                    "usage": {
                        "prompt_tokens": 4,
                        "completion_tokens": 2,
                        "total_tokens": 6,
                    }
                },
                {"finish_reason": "tool_calls"},
            ]
        ]
    )
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(
        agent.run_turn(
            session_id=None,
            task_id=None,
            message="hi",
            auto_analyze=False,
            lang="en",
            llm_client=llm,
        )
    )
    assert events[-1][0] == "done"
    payload = json.loads(events[-1][1])
    assert payload["tool_batches"] == 1
    assert isinstance(payload["elapsed_ms"], int)
    assert payload["usage"] == {
        "prompt_tokens": 4,
        "completion_tokens": 2,
        "total_tokens": 6,
    }
    tasks.close()
    agents.close()


def test_chat_stream_timeout_argument_defaults_to_180():
    import requests
    from asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "OK"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        captured = {}
        original_post = requests.post

        def capture_post(url, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return original_post(url, **kwargs)

        with patch.object(requests, "post", capture_post):
            client.chat([{"role": "user", "content": "Hi"}])
        assert captured["timeout"] == 180
