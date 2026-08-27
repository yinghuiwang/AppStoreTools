from __future__ import annotations

import json

from asc.web.agent import WebAgent, _row_to_openai, sanitize_llm_messages
from asc.web.agent_store import AgentStore
from asc.web.tasks import TaskStore


def test_row_to_openai_compacts_ok_tool_payload():
    payload = {
        "ok": True,
        "error_count": 3,
        "warning_count": 1,
        "item_count": 2,
        "group_count": 1,
        "locales": [
            {"locale": "en-US", "fields": {"name": "HugeNameShouldNotReachLLM"}},
            {"locale": "zh-Hans", "fields": {"name": "应用"}},
        ],
        "issues": [{"level": "error", "message": f"e{i}"} for i in range(20)],
        "items": [{"productId": "x", "name": "should-not-appear"}],
        "summary": "3 errors",
    }
    raw = json.dumps(payload, ensure_ascii=False)
    row = {
        "role": "tool",
        "content": raw,
        "tool_call_id": "c1",
        "tool_name": "validate_listing",
    }
    out = _row_to_openai(row)
    sent = json.loads(out["content"])
    assert sent["ok"] is True
    assert sent["error_count"] == 3
    assert sent["warning_count"] == 1
    assert sent["item_count"] == 2
    assert sent["group_count"] == 1
    assert sent["summary"] == "3 errors"
    assert sent["locales"] == ["en-US", "zh-Hans"]
    assert len(sent["issues"]) == 12
    assert "items" not in sent
    assert "HugeNameShouldNotReachLLM" not in out["content"]
    assert out["tool_call_id"] == "c1"
    assert out["name"] == "validate_listing"
    assert row["content"] == raw


def test_row_to_openai_truncates_non_json_tool_content():
    content = "not-json " * 400
    assert len(content) > 2048
    out = _row_to_openai({"role": "tool", "content": content, "tool_call_id": "c2"})
    assert len(out["content"]) == 2048
    assert out["content"] == content[:2048]


def test_row_to_openai_keeps_knowledge_content_when_no_domain_keys():
    payload = {
        "ok": True,
        "topic": "listing",
        "content": "appstore-listing legal block " + ("x" * 100),
    }
    raw = json.dumps(payload)
    out = _row_to_openai({"role": "tool", "content": raw, "tool_call_id": "c3"})
    sent = json.loads(out["content"])
    assert sent["ok"] is True
    assert "appstore-listing" in sent["content"]


def _assistant_calls(*pairs: tuple[str, str]) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": ident,
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
            for ident, name in pairs
        ],
    }


def test_sanitize_drops_orphan_tool_from_truncated_window():
    # Sliding window dropped the assistant that declared dee5b, but kept
    # the validate_listing result — MiniMax 2013.
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "content": "{}", "tool_call_id": "call_01a0412a9e4f7b71960dee5b"},
        {"role": "user", "content": "continue"},
    ]
    out = sanitize_llm_messages(messages)
    assert [msg["role"] for msg in out] == ["system", "user"]
    assert all(msg.get("tool_call_id") != "call_01a0412a9e4f7b71960dee5b" for msg in out)


def test_sanitize_keeps_complete_tool_group():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "check listing"},
        _assistant_calls(
            ("call_dee20", "get_listing_snapshot"),
            ("call_dee5b", "validate_listing"),
        ),
        {"role": "tool", "content": "{}", "tool_call_id": "call_dee20", "name": "get_listing_snapshot"},
        {"role": "tool", "content": "{}", "tool_call_id": "call_dee5b", "name": "validate_listing"},
        {"role": "assistant", "content": "done"},
    ]
    assert sanitize_llm_messages(messages) == messages


def test_sanitize_strips_incomplete_assistant_tool_group():
    messages = [
        {"role": "user", "content": "go"},
        _assistant_calls(("call_a", "get_knowledge"), ("call_b", "search_knowledge")),
        {"role": "tool", "content": "{}", "tool_call_id": "call_a", "name": "get_knowledge"},
        {"role": "assistant", "content": "later"},
    ]
    out = sanitize_llm_messages(messages)
    assert [msg["role"] for msg in out] == ["user", "assistant"]
    assert out[1]["content"] == "later"
    assert not any(msg.get("role") == "tool" for msg in out)
    assert "tool_calls" not in out[1]


def test_messages_for_llm_drops_orphan_tool_id(tmp_path):
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    sid = agents.get_or_create_session(None, "")["id"]
    agents.append_message(
        sid,
        "tool",
        "{}",
        tool_name="validate_listing",
        tool_call_id="call_01a0412a9e4f7b71960dee5b",
    )
    agents.append_message(sid, "user", "continue")
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    messages = agent._messages_for_llm(sid, "en")
    assert all(
        msg.get("tool_call_id") != "call_01a0412a9e4f7b71960dee5b" for msg in messages
    )
    assert any(msg.get("role") == "user" and msg.get("content") == "continue" for msg in messages)
    tasks.close()
    agents.close()
