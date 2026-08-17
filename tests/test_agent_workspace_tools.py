"""Workspace file tools: grep/read execute now; write/create/delete stay gated."""
from __future__ import annotations

from pathlib import Path

from asc.web.agent_store import AgentStore
from asc.web.agent_tools import (
    MODEL_TOOL_NAMES,
    OPENAI_TOOLS,
    AgentToolContext,
    apply_fix,
    execute_model_tool,
)
from asc.web.tasks import TaskStore


def _ctx(tmp_path, store, task_id=None, agent_store=None, session_id="", form_paths=None):
    return AgentToolContext(
        task_store=store,
        agent_store=agent_store,
        bound_task_id=task_id,
        project_root=tmp_path,
        turn_seq=1,
        session_id=session_id,
        form_paths=list(form_paths or []),
    )


def _session_ctx(tmp_path):
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    session = agents.get_or_create_session(None, "myapp")
    ctx = _ctx(tmp_path, tasks, agent_store=agents, session_id=session["id"])
    return tasks, agents, ctx


def test_workspace_tools_are_registered_and_apply_stays_gated():
    names = {item["function"]["name"] for item in OPENAI_TOOLS}
    assert names == set(MODEL_TOOL_NAMES)
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
        assert name in names
    assert "apply_fix" not in names
    assert "rerun_task" not in names


def test_grep_hits_in_project_and_skips_ignored_dirs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("hello unique_token_xyz\n", encoding="utf-8")
    ignored = tmp_path / "node_modules" / "pkg"
    ignored.mkdir(parents=True)
    (ignored / "lib.js").write_text("hello unique_token_xyz\n", encoding="utf-8")
    git_obj = tmp_path / ".git" / "objects"
    git_obj.mkdir(parents=True)
    (git_obj / "ab").write_text("hello unique_token_xyz\n", encoding="utf-8")
    spa = tmp_path / "src" / "asc" / "web" / "static" / "spa"
    spa.mkdir(parents=True)
    (spa / "index.js").write_text("hello unique_token_xyz\n", encoding="utf-8")
    store = TaskStore(tmp_path / "tasks.db")
    result = execute_model_tool(_ctx(tmp_path, store), "grep", {"pattern": "unique_token_xyz"})
    assert result["ok"] is True
    blob = str(result)
    assert "src/app.py" in blob or "app.py" in blob
    assert "unique_token_xyz" in blob
    assert "node_modules" not in blob
    assert ".git" not in blob
    assert "static/spa" not in blob
    store.close()


def test_search_files_is_grep_alias(tmp_path):
    (tmp_path / "note.txt").write_text("alias_hit_abc\n", encoding="utf-8")
    store = TaskStore(tmp_path / "tasks.db")
    result = execute_model_tool(_ctx(tmp_path, store), "search_files", {"pattern": "alias_hit_abc"})
    assert result["ok"] is True
    assert "alias_hit_abc" in str(result)
    store.close()


def test_grep_rejects_path_escape(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    result = execute_model_tool(
        _ctx(tmp_path, store),
        "grep",
        {"pattern": "secret", "path": "../"},
    )
    assert result["ok"] is False
    assert "node_modules" not in str(result).lower()
    store.close()


def test_read_file_offset_limit_and_truncation(tmp_path):
    lines = [f"line-{i:03d}" for i in range(1, 81)]
    (tmp_path / "notes.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    store = TaskStore(tmp_path / "tasks.db")
    ctx = _ctx(tmp_path, store)
    window = execute_model_tool(
        ctx,
        "read_file",
        {"path": "notes.txt", "offset": 10, "limit": 5},
    )
    assert window["ok"] is True
    content = window.get("content") or ""
    assert "line-010" in content
    assert "line-014" in content
    assert "line-001" not in content
    assert "line-020" not in content
    assert window.get("truncated") is True or window.get("offset") == 10

    capped = execute_model_tool(ctx, "read_file", {"path": "notes.txt", "limit": 3})
    assert capped["ok"] is True
    assert "line-001" in str(capped)
    assert "line-010" not in str(capped)
    store.close()


def test_read_file_rejects_secret_and_escape(tmp_path):
    (tmp_path / ".env").write_text("API_KEY=super-secret\n", encoding="utf-8")
    keys = tmp_path / "keys"
    keys.mkdir()
    p8 = keys / "AuthKey_X.p8"
    p8.write_text("-----BEGIN PRIVATE KEY-----\nNOPE\n-----END PRIVATE KEY-----\n", encoding="utf-8")
    (tmp_path / "ok.py").write_text("print('hi')\n", encoding="utf-8")
    store = TaskStore(tmp_path / "tasks.db")
    ctx = _ctx(tmp_path, store)
    env = execute_model_tool(ctx, "read_file", {"path": ".env"})
    assert env["ok"] is False
    assert "super-secret" not in str(env)
    denied = execute_model_tool(ctx, "read_file", {"path": "keys/AuthKey_X.p8"})
    assert denied["ok"] is False
    assert "NOPE" not in str(denied)
    escape = execute_model_tool(ctx, "read_file", {"path": "../outside.txt"})
    assert escape["ok"] is False
    allowed = execute_model_tool(ctx, "read_file", {"path": "ok.py"})
    assert allowed["ok"] is True
    assert "print" in str(allowed)
    store.close()


def test_write_create_delete_only_insert_plan(tmp_path):
    target = tmp_path / "src"
    target.mkdir()
    existing = target / "app.py"
    existing.write_text("old\n", encoding="utf-8")
    before = existing.read_bytes()
    tasks, agents, ctx = _session_ctx(tmp_path)

    written = execute_model_tool(
        ctx,
        "write_file",
        {"path": "src/app.py", "content": "new\n"},
    )
    created = execute_model_tool(
        ctx,
        "create_file",
        {"path": "src/new.py", "content": "created\n"},
    )
    deleted = execute_model_tool(ctx, "delete_file", {"path": "src/app.py"})

    assert written["ok"] is True
    assert created["ok"] is True
    assert deleted["ok"] is True
    for result in (written, created, deleted):
        assert result.get("status") == "draft"
        assert result.get("plan_id")
        plan = agents.get_plan(result["plan_id"])
        assert plan["status"] == "draft"
        assert plan["mutations"]
    assert existing.read_bytes() == before
    assert not (tmp_path / "src" / "new.py").exists()
    assert "将写入" in str(written.get("summary") or "") or "src/app.py" in str(written)
    assert "将删除" in str(deleted.get("summary") or "") or "src/app.py" in str(deleted)
    tasks.close()
    agents.close()


def test_apply_file_mutations_then_reject_does_not_write(tmp_path):
    (tmp_path / "keep.txt").write_text("keep\n", encoding="utf-8")
    (tmp_path / "gone.txt").write_text("gone\n", encoding="utf-8")
    tasks, agents, ctx = _session_ctx(tmp_path)

    write = execute_model_tool(
        ctx, "write_file", {"path": "keep.txt", "content": "changed\n"}
    )
    create = execute_model_tool(
        ctx, "create_file", {"path": "fresh.txt", "content": "fresh\n"}
    )
    delete = execute_model_tool(ctx, "delete_file", {"path": "gone.txt"})
    assert write["ok"] and create["ok"] and delete["ok"]
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    assert not (tmp_path / "fresh.txt").exists()
    assert (tmp_path / "gone.txt").exists()

    agents.promote_drafts(ctx.session_id, 1)
    assert apply_fix(ctx, write["plan_id"])["ok"] is True
    assert apply_fix(ctx, create["plan_id"])["ok"] is True
    assert apply_fix(ctx, delete["plan_id"])["ok"] is True
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "changed\n"
    assert (tmp_path / "fresh.txt").read_text(encoding="utf-8") == "fresh\n"
    assert not (tmp_path / "gone.txt").exists()
    tasks.close()
    agents.close()


def test_reject_file_plan_does_not_change_disk(tmp_path):
    path = tmp_path / "stay.txt"
    path.write_text("original\n", encoding="utf-8")
    tasks, agents, ctx = _session_ctx(tmp_path)
    result = execute_model_tool(
        ctx, "write_file", {"path": "stay.txt", "content": "nope\n"}
    )
    assert result["ok"] is True
    agents.promote_drafts(ctx.session_id, 1)
    assert agents.reject_pending(result["plan_id"]) is True
    assert path.read_text(encoding="utf-8") == "original\n"
    assert agents.get_plan(result["plan_id"])["status"] == "rejected"
    tasks.close()
    agents.close()


def test_file_tools_reject_dotdot_and_secrets(tmp_path):
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    tasks, agents, ctx = _session_ctx(tmp_path)
    escape = execute_model_tool(
        ctx, "write_file", {"path": "../evil.py", "content": "x\n"}
    )
    secret = execute_model_tool(
        ctx, "delete_file", {"path": ".env"}
    )
    root = execute_model_tool(ctx, "delete_file", {"path": "."})
    assert escape["ok"] is False
    assert secret["ok"] is False
    assert root["ok"] is False
    assert not (tmp_path.parent / "evil.py").exists()
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    tasks.close()
    agents.close()


def test_write_file_without_session_does_not_touch_disk(tmp_path):
    path = tmp_path / "a.py"
    path.write_text("old\n", encoding="utf-8")
    store = TaskStore(tmp_path / "tasks.db")
    result = execute_model_tool(
        _ctx(tmp_path, store),
        "write_file",
        {"path": "a.py", "content": "new\n"},
    )
    assert result["ok"] is False
    assert path.read_text(encoding="utf-8") == "old\n"
    store.close()


def test_form_path_outside_project_is_readable_and_outside_still_denied(tmp_path):
    project = tmp_path / "project"
    extra = tmp_path / "listing-data"
    other = tmp_path / "unrelated"
    project.mkdir()
    extra.mkdir()
    other.mkdir()
    (extra / "appstore_info.csv").write_text("locale,name\nen-US,FormApp\n", encoding="utf-8")
    (other / "secret.txt").write_text("nope\n", encoding="utf-8")
    (extra / ".env").write_text("API_KEY=hidden\n", encoding="utf-8")
    store = TaskStore(project / "tasks.db")
    ctx = _ctx(project, store, form_paths=[str(extra)])

    denied = execute_model_tool(ctx, "read_file", {"path": str(other / "secret.txt")})
    assert denied["ok"] is False
    assert "nope" not in str(denied)

    allowed = execute_model_tool(ctx, "read_file", {"path": str(extra / "appstore_info.csv")})
    assert allowed["ok"] is True
    assert "FormApp" in str(allowed)

    hits = execute_model_tool(ctx, "grep", {"pattern": "FormApp", "path": str(extra)})
    assert hits["ok"] is True
    assert "FormApp" in str(hits)

    secret = execute_model_tool(ctx, "read_file", {"path": str(extra / ".env")})
    assert secret["ok"] is False
    assert "hidden" not in str(secret)
    store.close()


def test_form_path_write_is_plan_only_then_apply(tmp_path):
    project = tmp_path / "project"
    extra = tmp_path / "shots"
    project.mkdir()
    extra.mkdir()
    target = extra / "note.txt"
    target.write_text("old\n", encoding="utf-8")
    tasks = TaskStore(project / "tasks.db")
    agents = AgentStore(project / "agent.db")
    session = agents.get_or_create_session(None, "myapp")
    ctx = _ctx(
        project,
        tasks,
        agent_store=agents,
        session_id=session["id"],
        form_paths=[str(extra)],
    )
    planned = execute_model_tool(
        ctx, "write_file", {"path": str(target), "content": "new\n"}
    )
    assert planned["ok"] is True
    assert target.read_text(encoding="utf-8") == "old\n"
    agents.promote_drafts(ctx.session_id, 1)
    assert apply_fix(ctx, planned["plan_id"])["ok"] is True
    assert target.read_text(encoding="utf-8") == "new\n"
    tasks.close()
    agents.close()


def test_replay_form_paths_become_allow_roots(tmp_path):
    project = tmp_path / "project"
    extra = tmp_path / "csv-home"
    project.mkdir()
    extra.mkdir()
    csv_path = extra / "app.csv"
    csv_path.write_text("locale,name\nzh-Hans,ReplayApp\n", encoding="utf-8")
    store = TaskStore(project / "tasks.db")
    replay = {
        "kind": "metadata",
        "profile": "myapp",
        "verbose": False,
        "params": {"csv_path": str(csv_path), "screenshots_dir": str(extra)},
    }
    task_id = store.create("metadata", profile="myapp", replay=replay)
    ctx = _ctx(project, store, task_id=task_id)
    out = execute_model_tool(ctx, "read_file", {"path": str(csv_path)})
    assert out["ok"] is True
    assert "ReplayApp" in str(out)
    store.close()


def test_only_project_root_still_rejects_outside(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (outside / "x.py").write_text("print(1)\n", encoding="utf-8")
    store = TaskStore(project / "tasks.db")
    ctx = _ctx(project, store)
    out = execute_model_tool(ctx, "read_file", {"path": str(outside / "x.py")})
    assert out["ok"] is False
    store.close()
