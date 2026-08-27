from __future__ import annotations

import base64
import json
from pathlib import Path

from asc.web.agent_attachments import format_attachments_prompt
from asc.web.agent_store import AgentStore
from asc.web.agent_vision import (
    MAX_VISION_BYTES,
    MAX_VISION_IMAGES,
    MAX_VISION_TOTAL_BYTES,
    image_parts,
)
from asc.web.tasks import TaskStore


def _tiny_png(path: Path, extra: bytes = b"x" * 16) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + extra)
    return path


def test_image_parts_builds_openai_data_urls(tmp_path):
    png = _tiny_png(tmp_path / "a.png")
    jpg = tmp_path / "b.jpg"
    jpg.write_bytes(b"\xff\xd8\xff" + b"j" * 20)
    items = [
        {"name": "a.png", "path": str(png)},
        {"name": "b.jpg", "path": str(jpg)},
    ]
    parts = image_parts(items)
    assert len(parts) == 2
    assert parts[0] == {
        "type": "image_url",
        "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode("ascii"),
        },
    }
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_image_parts_skips_oversize_unreadable_and_non_image(tmp_path):
    ok = _tiny_png(tmp_path / "ok.png")
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG" + b"x" * (MAX_VISION_BYTES + 1))
    csv = tmp_path / "a.csv"
    csv.write_text("locale,name\n", encoding="utf-8")
    missing = tmp_path / "gone.png"
    items = [
        {"name": "big.png", "path": str(big)},
        {"name": "a.csv", "path": str(csv)},
        {"name": "gone.png", "path": str(missing)},
        {"name": "ok.png", "path": str(ok)},
    ]
    parts = image_parts(items)
    assert len(parts) == 1
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_image_parts_caps_at_max_images(tmp_path):
    items = []
    for index in range(MAX_VISION_IMAGES + 1):
        path = _tiny_png(tmp_path / f"{index}.png", extra=bytes([index]) * 8)
        items.append({"name": path.name, "path": str(path)})
    parts = image_parts(items)
    assert MAX_VISION_IMAGES == 8
    assert len(parts) == MAX_VISION_IMAGES


def test_image_parts_respects_total_byte_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("asc.web.agent_vision.MAX_VISION_TOTAL_BYTES", 40)
    first = _tiny_png(tmp_path / "a.png", extra=b"a" * 24)
    second = _tiny_png(tmp_path / "b.png", extra=b"b" * 24)
    parts = image_parts(
        [
            {"name": "a.png", "path": str(first)},
            {"name": "b.png", "path": str(second)},
        ]
    )
    assert MAX_VISION_TOTAL_BYTES == 20 * 1024 * 1024
    assert len(parts) == 1


def test_messages_for_llm_only_last_user_is_multimodal(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    session = agents.get_or_create_session(None, "")
    sid = session["id"]
    agents.append_message(sid, "user", "previous text")
    agents.append_message(sid, "assistant", "ok")
    agents.append_message(sid, "user", "look at this shot")
    png = _tiny_png(tmp_path / "shot.png")
    items = [{"name": "shot.png", "path": str(png)}]
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    messages = agent._messages_for_llm(sid, "en", attachments=items)
    users = [msg for msg in messages if msg.get("role") == "user"]
    assert isinstance(users[0]["content"], str)
    assert users[0]["content"] == "previous text"
    last = users[-1]["content"]
    assert isinstance(last, list)
    assert last[0] == {"type": "text", "text": "look at this shot"}
    assert last[1]["type"] == "image_url"
    assert last[1]["image_url"]["url"].startswith("data:image/png;base64,")
    rows = agents.list_messages(sid)
    user_rows = [row for row in rows if row["role"] == "user"]
    assert all("base64" not in (row.get("content") or "") for row in user_rows)
    assert all("data:image" not in (row.get("content") or "") for row in user_rows)
    tasks.close()
    agents.close()


def test_run_turn_vision_not_persisted_to_sqlite(tmp_path):
    from asc.web.agent import WebAgent

    png = _tiny_png(tmp_path / "shot.png")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")

    class ScriptedLLM:
        def __init__(self) -> None:
            self.messages_seen = []

        def chat_stream(self, messages, tools, temperature=0.3):
            self.messages_seen.append(messages)
            yield {"content": "ok", "finish_reason": "stop"}

    llm = ScriptedLLM()
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(
        agent.run_turn(
            session_id=None,
            task_id=None,
            message="what is this",
            auto_analyze=False,
            lang="en",
            llm_client=llm,
            attachments=[{"kind": "path", "path": str(png), "name": png.name}],
        )
    )
    last_user = [msg for msg in llm.messages_seen[0] if msg["role"] == "user"][-1]
    assert isinstance(last_user["content"], list)
    assert last_user["content"][0]["type"] == "text"
    assert "what is this" in last_user["content"][0]["text"]
    assert last_user["content"][1]["type"] == "image_url"
    session_id = None
    for name, data in events:
        if name == "session":
            session_id = json.loads(data)["session_id"]
    rows = agents.list_messages(session_id)
    user_text = next(row["content"] for row in rows if row["role"] == "user")
    assert isinstance(user_text, str)
    assert "data:image" not in user_text
    assert "base64" not in user_text
    assert str(png.resolve()) in user_text
    tasks.close()
    agents.close()


def test_attachment_prompt_mentions_direct_vision():
    items = [{"name": "a.png", "path": "/tmp/a.png"}]
    text_en = format_attachments_prompt(items, "en")
    assert "seen directly" in text_en.lower()
    assert "inspect_local" in text_en
    assert "/tmp/a.png" in text_en
    text_zh = format_attachments_prompt(items, "zh")
    assert "inspect_local" in text_zh
    assert "/tmp/a.png" in text_zh
