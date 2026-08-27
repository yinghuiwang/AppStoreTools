"""AG-UI adapter: legacy WebAgent events → TDesign Chat official event types."""
from __future__ import annotations

import json

from asc.web.agent_agui import split_think_delta, translate_legacy_events


def _types(events: list[dict]) -> list[str]:
    return [str(item.get("type") or "") for item in events]


def test_split_think_tags_across_chunks():
    mode = "text"
    hold = ""
    thinking = ""
    visible = ""
    for chunk in ("<thi", "nk>secret plan</th", "ink>hello"):
        split = split_think_delta(mode, hold, chunk)
        thinking += split["thinking"]
        visible += split["visible"]
        mode = split["mode"]
        hold = split["hold"]
    if hold:
        if mode == "think":
            thinking += hold
        else:
            visible += hold
    assert thinking == "secret plan"
    assert visible == "hello"


def test_incremental_visible_tokens_emit_text_content_deltas():
    events = list(
        translate_legacy_events(
            [
                ("session", json.dumps({"session_id": "s1"})),
                ("token", "Hel"),
                ("token", "lo"),
                ("token", " world"),
                ("done", json.dumps({"session_id": "s1", "plan_ids": []})),
            ],
            run_id="run-text",
        )
    )
    deltas = [
        str(item.get("delta") or "")
        for item in events
        if item.get("type") == "TEXT_MESSAGE_CONTENT"
    ]
    assert deltas == ["Hel", "lo", " world"]
    types = _types(events)
    start = types.index("TEXT_MESSAGE_START")
    end = types.index("TEXT_MESSAGE_END")
    content_indexes = [i for i, name in enumerate(types) if name == "TEXT_MESSAGE_CONTENT"]
    assert content_indexes == [start + 1, start + 2, start + 3]
    assert end == start + 4
    assert not any(item.get("type") == "THINKING_TEXT_MESSAGE_CONTENT" for item in events)


def test_incremental_think_tokens_emit_content_deltas():
    events = list(
        translate_legacy_events(
            [
                ("session", json.dumps({"session_id": "s1"})),
                ("token", "<think>先"),
                ("token", "看日志"),
                ("token", "</think>hello"),
                ("done", json.dumps({"session_id": "s1", "plan_ids": []})),
            ],
            run_id="run-think",
        )
    )
    deltas = [
        str(item.get("delta") or "")
        for item in events
        if item.get("type") == "THINKING_TEXT_MESSAGE_CONTENT"
    ]
    assert deltas == ["先", "看日志"]
    assert any(item.get("type") == "THINKING_TEXT_MESSAGE_START" for item in events)
    assert any(item.get("type") == "THINKING_TEXT_MESSAGE_END" for item in events)


def test_token_stream_emits_official_thinking_and_text_events():
    events = list(
        translate_legacy_events(
            [
                ("session", json.dumps({"session_id": "s1", "task_id": "t1"})),
                ("token", "<think>plan"),
                ("token", "</think>hello"),
                ("done", json.dumps({"session_id": "s1", "plan_ids": []})),
            ],
            run_id="run1",
        )
    )
    types = _types(events)
    assert types[0] == "RUN_STARTED"
    assert events[0]["threadId"] == "s1"
    assert events[0]["runId"] == "run1"
    assert "THINKING_TEXT_MESSAGE_START" in types
    assert "THINKING_TEXT_MESSAGE_CONTENT" in types
    assert "THINKING_TEXT_MESSAGE_END" in types
    assert "TEXT_MESSAGE_START" in types
    assert "TEXT_MESSAGE_CONTENT" in types
    assert "TEXT_MESSAGE_END" in types
    assert types[-1] == "RUN_FINISHED"
    think_text = "".join(
        str(item.get("delta") or "")
        for item in events
        if item.get("type") == "THINKING_TEXT_MESSAGE_CONTENT"
    )
    visible = "".join(
        str(item.get("delta") or "")
        for item in events
        if item.get("type") == "TEXT_MESSAGE_CONTENT"
    )
    assert think_text == "plan"
    assert visible == "hello"
    assert "<think>" not in visible
    assert "CUSTOM" in types


def test_tool_events_map_to_official_tool_call_lifecycle():
    events = list(
        translate_legacy_events(
            [
                ("session", json.dumps({"session_id": "s1"})),
                ("tool_start", json.dumps({"id": "c1", "name": "get_task", "arguments": "{}"})),
                (
                    "tool_result",
                    json.dumps({"id": "c1", "name": "get_task", "ok": True, "summary": "metadata error"}),
                ),
                ("done", json.dumps({"session_id": "s1", "plan_ids": []})),
            ],
            run_id="run2",
        )
    )
    types = _types(events)
    assert "TOOL_CALL_START" in types
    assert "TOOL_CALL_ARGS" in types
    assert "TOOL_CALL_END" in types
    assert "TOOL_CALL_RESULT" in types
    start = next(item for item in events if item["type"] == "TOOL_CALL_START")
    result = next(item for item in events if item["type"] == "TOOL_CALL_RESULT")
    assert start["toolCallId"] == "c1"
    assert start["toolCallName"] == "get_task"
    assert result["toolCallId"] == "c1"
    assert result["role"] == "tool"
    payload = json.loads(result["content"])
    assert payload["ok"] is True
    assert payload["summary"] == "metadata error"


def test_error_emits_run_error():
    events = list(
        translate_legacy_events(
            [
                ("session", json.dumps({"session_id": "s1"})),
                ("error", json.dumps({"code": "llm_unavailable", "message": "down"})),
            ],
            run_id="run3",
        )
    )
    err = next(item for item in events if item["type"] == "RUN_ERROR")
    assert err["code"] == "llm_unavailable"
    assert err["message"] == "down"


def test_error_forwards_where():
    events = list(
        translate_legacy_events(
            [
                ("session", json.dumps({"session_id": "s1"})),
                (
                    "error",
                    json.dumps(
                        {
                            "code": "llm_unavailable",
                            "message": "down",
                            "where": "LLM HTTP 401 @ api.minimaxi.com",
                        }
                    ),
                ),
            ],
            run_id="run3b",
        )
    )
    err = next(item for item in events if item["type"] == "RUN_ERROR")
    assert err["where"] == "LLM HTTP 401 @ api.minimaxi.com"


def test_done_emits_plan_activity_snapshot():
    class FakeStore:
        def get_plan(self, plan_id: str):
            return {"id": plan_id, "status": "pending", "summary": "fix", "mutations": []}

    events = list(
        translate_legacy_events(
            [
                ("session", json.dumps({"session_id": "s1"})),
                ("token", "ok"),
                ("done", json.dumps({"session_id": "s1", "plan_ids": ["p1"]})),
            ],
            run_id="run4",
            agent_store=FakeStore(),
        )
    )
    activity = next(item for item in events if item["type"] == "ACTIVITY_SNAPSHOT")
    assert activity["activityType"] == "propose_fix"
    assert activity["content"]["id"] == "p1"
    assert activity["content"]["summary"] == "fix"


def test_choices_event_emits_offer_choices_activity():
    workflow = {
        "phase": "awaiting_choice",
        "kind": "listing",
        "options": [{"id": "opt_1", "label": "Premium"}],
    }
    events = list(
        translate_legacy_events(
            [
                ("session", json.dumps({"session_id": "s1"})),
                ("choices", json.dumps(workflow)),
                ("done", json.dumps({"session_id": "s1", "plan_ids": [], "workflow": workflow})),
            ],
            run_id="run-choices",
        )
    )
    activity = next(
        item
        for item in events
        if item.get("type") == "ACTIVITY_SNAPSHOT" and item.get("activityType") == "offer_choices"
    )
    assert activity["content"]["phase"] == "awaiting_choice"
    assert activity["content"]["options"][0]["id"] == "opt_1"
