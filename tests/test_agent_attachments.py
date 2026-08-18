from __future__ import annotations

import base64
from pathlib import Path

from asc.web.agent_attachments import (
    MAX_ATTACHMENTS,
    MAX_EXCERPT_CHARS,
    MAX_FILE_BYTES,
    MAX_TOTAL_BYTES,
    attachment_form_paths,
    format_attachments_prompt,
    merge_user_content_with_attachments,
    normalize_attachments,
)
from asc.web.agent_store import AgentStore
from asc.web.agent_tools import AgentToolContext, execute_model_tool
from asc.web.tasks import TaskStore


def test_normalize_path_and_reject_secrets(tmp_path):
    csv = tmp_path / "appstore_info.csv"
    csv.write_text("locale,name\nen-US,Demo\n", encoding="utf-8")
    secret = tmp_path / "AuthKey.p8"
    secret.write_text("SECRET", encoding="utf-8")
    items = normalize_attachments(
        [
            {"kind": "path", "path": str(csv), "name": csv.name},
            {"kind": "path", "path": str(secret), "name": secret.name},
            {"kind": "path", "path": str(tmp_path / "missing.json"), "name": "missing.json"},
        ],
        project_root=tmp_path,
        session_id="s1",
    )
    assert len(items) == 1
    assert items[0]["name"] == "appstore_info.csv"
    assert items[0]["path"] == str(csv.resolve())
    assert "Demo" in items[0]["excerpt"]
    assert attachment_form_paths(items) == [str(csv.resolve())]


def test_normalize_inline_persists_under_inbox(tmp_path):
    items = normalize_attachments(
        [
            {
                "kind": "inline",
                "name": "notes.txt",
                "content": "keyword ideas",
            },
            {
                "kind": "inline",
                "name": "shot.png",
                "content_b64": base64.b64encode(b"\x89PNG\r\n" + b"x" * 20).decode("ascii"),
            },
        ],
        project_root=tmp_path,
        session_id="sess-1",
    )
    assert len(items) == 2
    note = tmp_path / ".asc" / "agent-inbox" / "sess-1" / "notes.txt"
    shot = tmp_path / ".asc" / "agent-inbox" / "sess-1" / "shot.png"
    assert note.read_text(encoding="utf-8") == "keyword ideas"
    assert items[0]["path"] == str(note)
    assert items[0]["excerpt"] == "keyword ideas"
    assert shot.exists()
    assert items[1]["binary"] is True
    assert "excerpt" not in items[1]


def test_normalize_rejects_huge_and_blocked_inline(tmp_path):
    items = normalize_attachments(
        [
            {"kind": "inline", "name": "big.txt", "content": "a" * (MAX_FILE_BYTES + 8)},
            {"kind": "inline", "name": ".env", "content": "TOKEN=1"},
            {"kind": "inline", "name": "ok.md", "content": "# hi"},
        ],
        project_root=tmp_path,
        session_id="s2",
    )
    assert [item["name"] for item in items] == ["ok.md"]


def test_normalize_keeps_excerpt_small_for_large_text(tmp_path):
    log = tmp_path / "export.log"
    body = "line\n" * ((MAX_EXCERPT_CHARS // 5) + 40)
    log.write_text(body, encoding="utf-8")
    items = normalize_attachments(
        [{"kind": "path", "path": str(log), "name": log.name}],
        project_root=tmp_path,
        session_id="s-excerpt",
    )
    assert len(items) == 1
    assert items[0]["size"] == len(body.encode("utf-8"))
    assert items[0]["size"] > MAX_EXCERPT_CHARS
    excerpt = items[0]["excerpt"]
    assert excerpt.endswith("…(truncated)")
    assert len(excerpt) <= MAX_EXCERPT_CHARS + 20


def test_normalize_rejects_over_total_budget(tmp_path, monkeypatch):
    from asc.web import agent_attachments as mod

    monkeypatch.setattr(mod, "MAX_TOTAL_BYTES", 80)
    first = tmp_path / "one.csv"
    second = tmp_path / "two.csv"
    first.write_text("a" * 50, encoding="utf-8")
    second.write_text("b" * 50, encoding="utf-8")
    items = normalize_attachments(
        [
            {"kind": "path", "path": str(first), "name": first.name},
            {"kind": "path", "path": str(second), "name": second.name},
        ],
        project_root=tmp_path,
        session_id="s-total",
    )
    assert [item["name"] for item in items] == ["one.csv"]


def test_frontend_attachment_limits_match_backend():
    assert MAX_ATTACHMENTS == 8
    assert MAX_FILE_BYTES == 10 * 1024 * 1024
    assert MAX_TOTAL_BYTES == 32 * 1024 * 1024
    assert MAX_EXCERPT_CHARS == 8 * 1024
    src = Path(__file__).resolve().parents[1] / "frontend" / "src" / "composables" / "agentAttachments.ts"
    text = src.read_text(encoding="utf-8")
    assert "AGENT_ATTACH_MAX = 8" in text
    assert "AGENT_ATTACH_MAX_BYTES = 10 * 1024 * 1024" in text
    assert "AGENT_ATTACH_MAX_TOTAL_BYTES = 32 * 1024 * 1024" in text
    panel = Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "AgentPanel.vue"
    vue = panel.read_text(encoding="utf-8")
    assert "total_too_large" in vue
    assert "agent.attach_total_too_large" in vue
    assert "t-attachments" in vue
    assert "image-viewer" in vue
    assert "fileType" in text
    assert '"image" as const' in text
    assert '"txt" as const' in text


def test_format_and_merge_prompt():
    items = [
        {"name": "a.csv", "path": "/tmp/a.csv", "excerpt": "locale,name"},
    ]
    text = format_attachments_prompt(items, "en")
    assert "[attachments]" in text
    assert "read_file" in text
    assert "/tmp/a.csv" in text
    assert "locale,name" in text
    merged = merge_user_content_with_attachments("check this", items, "zh")
    assert merged.startswith("check this")
    assert "read_file" in merged or "inspect_local" in merged
    named = merge_user_content_with_attachments("[attachments]\n- a.csv — /tmp/a.csv", items, "en")
    assert named.count("[attachments]") == 1
    assert "[attachment contents]" in named
    assert "locale,name" in named


def test_inspect_local_can_read_attachment_path(tmp_path):
    extra = tmp_path / "outside"
    extra.mkdir()
    note = extra / "review.txt"
    note.write_text("review notes", encoding="utf-8")
    store = TaskStore(tmp_path / "tasks.db")
    ctx = AgentToolContext(
        task_store=store,
        agent_store=None,
        bound_task_id=None,
        project_root=tmp_path,
        turn_seq=1,
        session_id="s",
        form_paths=[str(note)],
        attachment_paths=[str(note)],
    )
    result = execute_model_tool(ctx, "inspect_local", {"path": str(note)})
    assert result["ok"] is True
    assert "review notes" in result["content"]
    store.close()


def test_run_turn_includes_attachments_for_model(tmp_path):
    from asc.web.agent import WebAgent

    csv = tmp_path / "data"
    csv.mkdir()
    path = csv / "appstore_info.csv"
    path.write_text("locale,name\nen-US,A\n", encoding="utf-8")
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
            message="please check",
            auto_analyze=False,
            lang="en",
            llm_client=llm,
            attachments=[{"kind": "path", "path": str(path), "name": path.name}],
        )
    )
    user = llm.messages_seen[0][1]["content"]
    assert "please check" in user
    assert "appstore_info.csv" in user
    assert str(path.resolve()) in user
    session_id = None
    for name, data in events:
        if name == "session":
            import json

            session_id = json.loads(data)["session_id"]
    rows = agents.list_messages(session_id)
    assert any("appstore_info.csv" in str(row.get("content") or "") for row in rows)
    tasks.close()
    agents.close()
