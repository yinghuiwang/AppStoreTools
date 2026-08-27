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

    listing_skill = search_notes("appstore-listing")
    assert listing_skill["ok"] is True
    assert any(hit["topic"] == "listing" for hit in listing_skill["hits"])
    assert "en-US" in str(listing_skill)
    assert "27" in str(listing_skill)

    iap_skill = search_notes("groupLevel")
    assert iap_skill["ok"] is True
    assert any(hit["topic"] == "iap" for hit in iap_skill["hits"])
    assert "crossgrade" in str(iap_skill).lower()


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
    assert "csv_set_fields" in got["content"]
    assert "zh-Hans" in got["content"]
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
    assert "get_knowledge(listing)" in text or "topic listing" in text
    assert "get_knowledge(iap)" in text or "topic iap" in text
    assert "get_listing_snapshot" in text
    assert "validate_listing" in text
    assert "count_listing_fields" in text
    assert "get_iap_snapshot" in text
    assert "validate_iap" in text
    assert "inspect_screenshots" in text
    assert "search_files" not in text
    assert "en-US and zh-Hans" not in text
    assert "search_knowledge" in MODEL_TOOL_NAMES
    assert "get_knowledge" in MODEL_TOOL_NAMES


def test_get_knowledge_includes_skill_workflows():
    listing = get_topic("listing")
    assert listing["ok"] is True
    assert listing.get("truncated") is not True
    assert "appstore-listing" in listing["content"]
    assert "legal block" in listing["content"]

    iap = get_topic("iap")
    assert iap["ok"] is True
    assert iap.get("truncated") is not True
    assert "iap-packages" in iap["content"]
    assert "infer_iap_products.rb" in iap["content"]
    assert "groupLevel" in iap["content"]
    assert "one category per message" in iap["content"]


def test_get_topic_second_call_does_not_reread_disk(monkeypatch):
    from asc.web import agent_knowledge as ak

    ak._NOTE_CACHE.clear()
    first = get_topic("listing")
    assert first["ok"] is True

    def boom(*_args, **_kwargs):
        raise AssertionError("should not re-read disk")

    monkeypatch.setattr(ak.resources, "files", boom)
    second = get_topic("listing")
    assert second["ok"] is True
    assert second["content"] == first["content"]
