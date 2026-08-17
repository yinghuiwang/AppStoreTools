"""UI message-state contract for Agent tool cards (mirrors agentStream.ts)."""
from __future__ import annotations

import json
from pathlib import Path

from asc.web.agent_store import AgentStore
from asc.web.tasks import TaskStatus, TaskStore
from tests.test_web_agent import ScriptedLLM

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"

OPEN_TAGS = ("<think>", "<thinking>", "<reasoning>")
CLOSE_TAGS = ("</think>", "</thinking>", "</reasoning>")


def _parse_obj(data: str) -> dict:
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _find_tag(buf: str, tags: tuple[str, ...]) -> tuple[int, int] | None:
    lower = buf.lower()
    best: tuple[int, int] | None = None
    for tag in tags:
        index = lower.find(tag)
        if index >= 0 and (best is None or index < best[0]):
            best = (index, len(tag))
    return best


def _suffix_prefix_len(buf: str, tags: tuple[str, ...]) -> int:
    lower = buf.lower()
    max_keep = 0
    for tag in tags:
        n = min(len(tag) - 1, len(lower))
        for k in range(n, 0, -1):
            if lower.endswith(tag[:k]):
                max_keep = max(max_keep, k)
                break
    return max_keep


def split_think_delta(mode: str, hold: str, chunk: str) -> dict:
    buf = hold + chunk
    thinking = ""
    visible = ""
    current = mode
    while buf:
        tags = OPEN_TAGS if current == "text" else CLOSE_TAGS
        hit = _find_tag(buf, tags)
        if hit is None:
            keep = _suffix_prefix_len(buf, tags)
            ready = buf[: len(buf) - keep] if keep else buf
            if current == "think":
                thinking += ready
            else:
                visible += ready
            buf = buf[len(buf) - keep :] if keep else ""
            break
        index, length = hit
        before = buf[:index]
        if current == "think":
            thinking += before
        else:
            visible += before
        buf = buf[index + length :]
        current = "think" if current == "text" else "text"
    return {"thinking": thinking, "visible": visible, "mode": current, "hold": buf}


def _tool_index(messages: list[dict], tid: str) -> int:
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("kind") == "tool" and msg.get("id") == tid:
            return i
    return -1


def _last_think_index(messages: list[dict]) -> int:
    for i in range(len(messages) - 1, -1, -1):
        kind = messages[i].get("kind")
        if kind == "plan":
            continue
        if kind == "thinking":
            return i
        if kind in {"user", "tool", "error"}:
            return -1
    return -1


def _stream_meta(messages: list[dict]) -> tuple[str, str]:
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        kind = msg.get("kind")
        if kind == "plan":
            continue
        if kind == "thinking":
            mode = "think" if msg.get("mode") == "think" else "text"
            return mode, str(msg.get("hold") or "")
        if kind in {"user", "tool", "error"}:
            break
    return "text", ""


def _append_assistant(messages: list[dict], fragment: str) -> list[dict]:
    if messages and messages[-1].get("kind") == "assistant":
        last = messages[-1]
        messages[-1] = {**last, "text": last["text"] + fragment}
        return messages
    return messages + [{"kind": "assistant", "text": fragment}]


def _apply_thinking(messages: list[dict], text: str) -> list[dict]:
    if not text.strip():
        return messages
    idx = _last_think_index(messages)
    if idx >= 0:
        current = messages[idx]
        messages[idx] = {**current, "text": current["text"] + text, "streaming": True}
        return messages
    return messages + [{"kind": "thinking", "text": text, "streaming": True, "mode": "text"}]


def _stamp_think_state(messages: list[dict], mode: str, hold: str) -> list[dict]:
    idx = _last_think_index(messages)
    if idx >= 0:
        current = messages[idx]
        messages[idx] = {
            **current,
            "mode": mode,
            "hold": hold,
            "streaming": bool(current.get("streaming") or mode == "think"),
        }
        return messages
    if mode == "think" or hold:
        return messages + [{
            "kind": "thinking",
            "text": "",
            "streaming": mode == "think",
            "mode": mode,
            "hold": hold,
        }]
    return messages


def apply_token(messages: list[dict], fragment: str) -> list[dict]:
    mode, hold = _stream_meta(messages)
    split = split_think_delta(mode, hold, fragment)
    if split["thinking"]:
        messages = _apply_thinking(messages, split["thinking"])
    if split["visible"]:
        messages = _append_assistant(messages, split["visible"])
    return _stamp_think_state(messages, split["mode"], split["hold"])


def finish_think_stream(messages: list[dict]) -> list[dict]:
    mode, hold = _stream_meta(messages)
    if hold:
        if mode == "think":
            messages = _apply_thinking(messages, hold)
        else:
            messages = _append_assistant(messages, hold)
    out = []
    for msg in messages:
        if msg.get("kind") == "thinking":
            text = str(msg.get("text") or "")
            if not text.strip():
                continue
            out.append({**msg, "streaming": False, "hold": "", "mode": "text"})
        else:
            out.append(msg)
    return out


def apply_agent_event(messages: list[dict], event: str, data: str) -> list[dict]:
    if event == "token":
        return apply_token(messages, data)
    if event == "thinking":
        return _apply_thinking(messages, data)
    payload = json.loads(data) if data else {}
    if event == "tool_start":
        tid = str(payload.get("id") or "")
        if not tid:
            return messages
        idx = _tool_index(messages, tid)
        if idx >= 0:
            msg = messages[idx]
            messages[idx] = {
                **msg,
                "name": str(payload.get("name") or msg.get("name") or "tool"),
                "status": "running",
            }
            return messages
        return messages + [{
            "kind": "tool",
            "id": tid,
            "name": str(payload.get("name") or "tool"),
            "status": "running",
            "summary": "",
        }]
    if event == "tool_result":
        tid = str(payload.get("id") or "")
        if not tid:
            return messages
        ok = payload.get("ok") is not False
        idx = _tool_index(messages, tid)
        if idx >= 0:
            msg = messages[idx]
            messages[idx] = {
                **msg,
                "name": str(payload.get("name") or msg.get("name") or "tool"),
                "status": "success" if ok else "error",
                "summary": str(payload.get("summary") or msg.get("summary") or ""),
                "ok": ok,
            }
            return messages
        return messages + [{
            "kind": "tool",
            "id": tid,
            "name": str(payload.get("name") or "tool"),
            "status": "success" if ok else "error",
            "summary": str(payload.get("summary") or ""),
            "ok": ok,
        }]
    return messages


def visible_reply(messages: list[dict], *, thinking_open: bool = False) -> str:
    parts: list[str] = []
    for msg in messages:
        kind = msg.get("kind")
        if kind == "assistant":
            parts.append(str(msg.get("text") or ""))
        elif kind == "thinking" and thinking_open:
            parts.append(str(msg.get("text") or ""))
    return "".join(parts)


def test_tool_start_then_result_updates_same_id():
    messages: list[dict] = [{"kind": "user", "text": "why"}]
    messages = apply_agent_event(messages, "token", "looking")
    messages = apply_agent_event(
        messages, "tool_start", json.dumps({"id": "c1", "name": "get_task"})
    )
    assert [m.get("kind") for m in messages] == ["user", "assistant", "tool"]
    tool = messages[-1]
    assert tool["id"] == "c1"
    assert tool["name"] == "get_task"
    assert tool["status"] == "running"
    messages = apply_agent_event(
        messages,
        "tool_result",
        json.dumps({"id": "c1", "name": "get_task", "ok": True, "summary": "metadata error"}),
    )
    assert sum(1 for m in messages if m.get("kind") == "tool") == 1
    tool = next(m for m in messages if m.get("kind") == "tool")
    assert tool["status"] == "success"
    assert tool["summary"] == "metadata error"
    messages = apply_agent_event(messages, "token", " done")
    assert messages[-1]["kind"] == "assistant"
    assert messages[-1]["text"] == " done"


def test_tool_result_false_is_error():
    messages = apply_agent_event(
        [], "tool_start", json.dumps({"id": "c2", "name": "inspect_local"})
    )
    messages = apply_agent_event(
        messages,
        "tool_result",
        json.dumps({"id": "c2", "name": "inspect_local", "ok": False, "summary": "missing file"}),
    )
    tool = messages[0]
    assert tool["status"] == "error"
    assert tool["ok"] is False
    assert tool["summary"] == "missing file"


def test_empty_thinking_is_not_inserted():
    assert apply_agent_event([], "thinking", "   ") == []
    inserted = apply_agent_event([], "thinking", "step")
    assert inserted[0]["kind"] == "thinking"
    assert inserted[0]["text"] == "step"


def test_think_tags_are_stripped_from_assistant_body():
    messages: list[dict] = []
    for chunk in ("<thi", "nk>secret plan</th", "ink>hello"):
        messages = apply_agent_event(messages, "token", chunk)
    messages = finish_think_stream(messages)
    kinds = [m.get("kind") for m in messages]
    assert kinds == ["thinking", "assistant"]
    assert messages[0]["text"] == "secret plan"
    assert messages[1]["text"] == "hello"
    assert "secret" not in visible_reply(messages)
    assert "hello" in visible_reply(messages)
    assert "secret plan" in visible_reply(messages, thinking_open=True)
    assert "<think>" not in visible_reply(messages, thinking_open=True)
    assert "</think>" not in visible_reply(messages, thinking_open=True)


def test_empty_think_tags_do_not_create_visible_block():
    messages = apply_agent_event([], "token", "<think></think>hello")
    messages = finish_think_stream(messages)
    assert [m.get("kind") for m in messages] == ["assistant"]
    assert messages[0]["text"] == "hello"


def test_thinking_event_stays_out_of_assistant_markdown():
    messages = apply_agent_event([], "thinking", "chain of thought")
    messages = apply_agent_event(messages, "token", "final answer")
    assert visible_reply(messages) == "final answer"
    assert "chain of thought" not in visible_reply(messages)


def test_backend_tool_events_have_id_name_ok_summary(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    task_id = tasks.create("metadata", profile="myapp")
    tasks.set_status(task_id, TaskStatus.ERROR)
    llm = ScriptedLLM([
        [
            {
                "tool_calls": [{
                    "index": 0,
                    "id": "c1",
                    "function": {"name": "get_task", "arguments": json.dumps({"task_id": task_id})},
                }],
            },
            {"finish_reason": "tool_calls"},
        ],
        [{"content": "failed at metadata", "finish_reason": "stop"}],
    ])
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(agent.run_turn(
        session_id=None, task_id=task_id, message="", auto_analyze=True,
        lang="zh", llm_client=llm,
    ))
    start = json.loads(next(data for name, data in events if name == "tool_start"))
    result = json.loads(next(data for name, data in events if name == "tool_result"))
    assert start["id"] == "c1"
    assert start["name"] == "get_task"
    assert result["id"] == "c1"
    assert result["name"] == "get_task"
    assert "ok" in result
    assert result.get("summary")
    ui: list[dict] = []
    for name, data in events:
        ui = apply_agent_event(ui, name, data)
    tools = [m for m in ui if m.get("kind") == "tool"]
    assert len(tools) == 1
    assert tools[0]["status"] in {"success", "error"}
    tasks.close()
    agents.close()


def attach_menu_should_close(opened: bool, target_inside_root: bool) -> bool:
    """Mirrors AgentPanel onDocPointerDown: outside click closes an open menu."""
    if not opened:
        return False
    return not target_inside_root


def test_attach_menu_closes_on_outside_click_not_inside():
    assert attach_menu_should_close(True, False) is True
    assert attach_menu_should_close(True, True) is False
    assert attach_menu_should_close(False, False) is False
    src = (FRONTEND / "components" / "AgentPanel.vue").read_text(encoding="utf-8")
    assert "onDocPointerDown" in src
    assert 'addEventListener("pointerdown"' in src
    assert "root.contains" in src
    assert 'event.key === "Escape"' in src
    assert "closeAttach" in src
    assert "data-agent-attach-menu" in src


def test_composer_is_multiline_textarea_with_icon_send():
    src = (FRONTEND / "components" / "AgentPanel.vue").read_text(encoding="utf-8")
    assert "<textarea" in src
    assert 'rows="2"' in src
    assert 'type="text"' not in src.split("data-agent-stream", 1)[1].split("</form>", 1)[0]
    assert "width: 52px" not in src
    assert "min-width: 52px" not in src
    assert "--composer-min: 56px" in src
    assert "--composer-max: 136px" in src
    assert "white-space: nowrap" in src
    assert "SendIcon" in src
    assert "PauseIcon" in src
    assert "data-agent-send" in src
    assert "data-agent-stop" in src
    assert "align-items: flex-end" in src
    send_btn = src.split('data-agent-send')[1].split("</button>", 1)[0]
    assert "agent.send" in send_btn
    assert "{{ t(\"agent.send\") }}" not in send_btn.split(":title")[0]
    assert "<SendIcon" in send_btn
    composer = src.split(".composer {", 1)[1].split(".row {", 1)[0]
    assert "padding: 10px;" in composer
    assert "min-width: 0" in composer


def test_built_spa_serves_textarea_composer():
    index = ROOT / "src" / "asc" / "web" / "static" / "spa" / "index.html"
    html = index.read_text(encoding="utf-8")
    assert "/static/spa/assets/index-" in html
    js_files = list((ROOT / "src" / "asc" / "web" / "static" / "spa" / "assets").glob("index-*.js"))
    assert js_files
    js = js_files[0].read_text(encoding="utf-8")
    assert "data-agent-input" in js
    assert "textarea" in js
    assert "data-agent-send" in js


def test_agent_stream_sends_form_paths():
    src = (FRONTEND / "composables" / "useAgent.ts").read_text(encoding="utf-8")
    assert "collectedFormPaths" in src
    assert "form_paths" in src
    helper = (FRONTEND / "composables" / "useFormPaths.ts").read_text(encoding="utf-8")
    assert "rememberFormPath" in helper
    assert "snap?.paths" in helper or "paths.csv" in helper


def test_tool_display_names_are_i18n_friendly():
    src = (FRONTEND / "components" / "AgentPanel.vue").read_text(encoding="utf-8")
    assert "toolDisplayName" in src
    assert "agent.tool.name." in src
    zh = json.loads((ROOT / "src" / "asc" / "web" / "locales" / "zh.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "src" / "asc" / "web" / "locales" / "en.json").read_text(encoding="utf-8"))
    for name in (
        "grep",
        "search_files",
        "read_file",
        "write_file",
        "create_file",
        "delete_file",
        "search_knowledge",
        "get_knowledge",
    ):
        key = f"agent.tool.name.{name}"
        assert zh[key]
        assert en[key]
        assert zh[key] != name
        assert en[key] != name


def test_thinking_body_is_collapsed_until_expanded():
    src = (FRONTEND / "components" / "AgentPanel.vue").read_text(encoding="utf-8")
    assert "data-agent-thinking" in src
    assert "data-agent-thinking-title" in src
    assert "data-agent-thinking-body" in src
    assert "openThinks" in src
    assert 'v-if="openThinks.includes(thinkName(idx))"' in src
    assert "agent.thinking_done" in src
    assert 'data-agent-thinking-open' in src
    assert "v-html=\"renderMd(msg.text)\"" in src
    think_block = src.split("data-agent-thinking")[1].split("data-agent-tool")[0]
    assert "v-html" not in think_block
