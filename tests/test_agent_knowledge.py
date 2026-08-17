from __future__ import annotations

from pathlib import Path

from asc.web.agent import _system_prompt
from asc.web.agent_knowledge import (
    TOPIC_FILES,
    get_topic,
    knowledge_root,
    list_topics,
    search_notes,
)
from asc.web.agent_tools import AgentToolContext, MODEL_TOOL_NAMES, execute_model_tool
from asc.web.tasks import TaskStore


def _ctx(tmp_path, store=None):
    return AgentToolContext(
        task_store=store or TaskStore(tmp_path / "tasks.db"),
        agent_store=None,
        bound_task_id=None,
        project_root=tmp_path,
        turn_seq=1,
        session_id="",
    )


def test_knowledge_files_and_index_cover_topics():
    root = knowledge_root()
    index = root.joinpath("INDEX.md").read_text(encoding="utf-8")
    assert "locales" in index
    assert "listing" in index
    assert "screenshots" in index
    assert "iap" in index
    assert "version" in index
    assert "pitfalls" in index
    for topic, name in TOPIC_FILES.items():
        text = root.joinpath(name).read_text(encoding="utf-8")
        assert text.startswith("#")
        assert "keywords:" in text.splitlines()[2].lower() or "keywords:" in text[:200].lower()
        assert topic in list_topics()


def test_search_knowledge_hits_required_queries():
    locale = search_notes("locale")
    assert locale["ok"] is True
    assert any(hit["topic"] == "locales" for hit in locale["hits"])
    assert "zh-Hans" in str(locale)

    keywords = search_notes("keywords 字数")
    assert keywords["ok"] is True
    blob = str(keywords)
    assert "100" in blob
    assert any(hit["topic"] == "listing" for hit in keywords["hits"])

    iap = search_notes("IAP 类型")
    assert iap["ok"] is True
    assert "CONSUMABLE" in str(iap)
    assert any(hit["topic"] == "iap" for hit in iap["hits"])

    whats = search_notes("what's new")
    assert whats["ok"] is True
    assert "4000" in str(whats)
    assert any(hit["topic"] == "version" for hit in whats["hits"])


def test_search_knowledge_ignores_project_root(tmp_path):
    empty = tmp_path / "empty-project"
    empty.mkdir()
    store = TaskStore(tmp_path / "tasks.db")
    ctx = _ctx(empty, store)
    assert list(empty.iterdir()) == []
    out = execute_model_tool(ctx, "search_knowledge", {"query": "locale"})
    assert out["ok"] is True
    assert out["hits"]
    assert "package:asc.web.knowledge" in out["hits"][0]["path"]
    assert list(empty.iterdir()) == []
    got = execute_model_tool(ctx, "get_knowledge", {"topic": "listing"})
    assert got["ok"] is True
    assert "30" in got["content"]
    store.close()


def test_get_knowledge_rejects_unknown_topic():
    out = get_topic("google-play")
    assert out["ok"] is False
    assert "unknown topic" in out["error"]


def test_write_file_cannot_edit_packaged_knowledge(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    ctx = _ctx(tmp_path, store)
    ctx.session_id = "s1"
    packaged = Path(__file__).resolve().parents[1] / "src" / "asc" / "web" / "knowledge" / "INDEX.md"
    before = packaged.read_text(encoding="utf-8")
    out = execute_model_tool(
        ctx,
        "write_file",
        {"path": str(packaged), "content": "hacked"},
    )
    assert out["ok"] is False
    assert packaged.read_text(encoding="utf-8") == before
    store.close()


def test_system_prompt_requires_knowledge_first():
    text = _system_prompt("zh")
    assert "search_knowledge" in text
    assert "get_knowledge" in text
    assert "App Store Connect expert" in text
    assert "search_knowledge" in MODEL_TOOL_NAMES
    assert "get_knowledge" in MODEL_TOOL_NAMES
