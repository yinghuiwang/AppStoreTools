from __future__ import annotations

from asc.web.agent_tools import AgentToolContext, execute_model_tool, OPENAI_TOOLS, MODEL_TOOL_NAMES
from asc.web.tasks import TaskStatus, TaskStore


def _ctx(tmp_path, store, task_id=None, agent_store=None, session_id=""):
    return AgentToolContext(
        task_store=store,
        agent_store=agent_store,
        bound_task_id=task_id,
        project_root=tmp_path,
        turn_seq=1,
        session_id=session_id,
    )


def test_openai_tools_match_model_names_and_keep_writes_gated():
    names = {t["function"]["name"] for t in OPENAI_TOOLS}
    assert names == set(MODEL_TOOL_NAMES)
    assert "apply_fix" not in names
    assert "rerun_task" not in names
    assert {"grep", "read_file", "write_file", "create_file", "delete_file"} <= names


def test_hallucinated_apply_fix_does_not_write(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,old\n", encoding="utf-8")
    before = csv_path.read_bytes()
    out = execute_model_tool(_ctx(tmp_path, store), "apply_fix", {"plan_id": "x"})
    assert out["ok"] is False
    assert "gated" in out["error"]
    assert csv_path.read_bytes() == before
    assert store.list_recent_states(limit=10) == []
    store.close()


def test_get_task_log_redacts_pem_and_caps_error_lines(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata", profile="myapp")
    store.append_log(task_id, "-----BEGIN PRIVATE KEY-----\\nMIISECRET\\n-----END PRIVATE KEY-----")
    store.append_log(task_id, "Traceback (most recent call last):")
    store.append_log(task_id, "ok line")
    store.set_status(task_id, TaskStatus.ERROR)
    result = execute_model_tool(_ctx(tmp_path, store, task_id), "get_task_log", {"task_id": task_id})
    blob = str(result)
    assert "MIISECRET" not in blob
    assert "BEGIN PRIVATE KEY" not in blob
    assert result["ok"] is True
    messages = [line["message"] for line in result["lines"]]
    assert any("Traceback" in message for message in messages)
    store.close()


def test_inspect_local_rejects_key_file_and_allows_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "appstore_info.csv"
    csv_path.write_text("locale,name\nen-US,App\n", encoding="utf-8")
    keys = tmp_path / "keys"
    keys.mkdir()
    p8 = keys / "AuthKey_X.p8"
    p8.write_text("-----BEGIN PRIVATE KEY-----\\nNOPE\\n-----END PRIVATE KEY-----", encoding="utf-8")
    store = TaskStore(tmp_path / "tasks.db")
    replay = {"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}}
    task_id = store.create("metadata", profile="myapp", replay=replay)
    monkeypatch.chdir(tmp_path)
    ctx = _ctx(tmp_path, store, task_id)
    denied = execute_model_tool(ctx, "inspect_local", {"path": str(p8)})
    assert denied["ok"] is False
    allowed = execute_model_tool(ctx, "inspect_local", {"path": str(csv_path)})
    assert allowed["ok"] is True
    assert "App" in str(allowed)
    store.close()


def test_get_task_reads_replay_via_get_replay_not_public_state(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    replay = {
        "kind": "metadata",
        "profile": "myapp",
        "verbose": False,
        "params": {
            "csv_path": "data/appstore_info.csv",
            "issuer_id": "SECRET-ISSUER",
        },
    }
    task_id = store.create("metadata", profile="myapp", replay=replay)
    store.set_result(task_id, {"error": "api_key=sk-live failed"})
    public = store.get_state(task_id)
    assert "params" not in public
    assert "replay" not in public
    result = execute_model_tool(_ctx(tmp_path, store, task_id), "get_task", {"task_id": task_id})
    assert result["ok"] is True
    assert result["has_replay"] is True
    assert result["params"]["csv_path"] == "data/appstore_info.csv"
    assert "SECRET-ISSUER" not in str(result)
    assert "sk-live" not in str(result)
    assert "logs" not in result
    store.close()


def test_inspect_local_lists_screenshots_without_png_bytes(tmp_path, monkeypatch):
    shots = tmp_path / "screenshots"
    shots.mkdir()
    png = shots / "01.png"
    png.write_bytes(b"\x89PNG\r\nSECRETBYTES")
    store = TaskStore(tmp_path / "tasks.db")
    replay = {
        "kind": "metadata",
        "profile": "myapp",
        "verbose": False,
        "params": {"screenshots_dir": str(shots)},
    }
    task_id = store.create("metadata", profile="myapp", replay=replay)
    monkeypatch.chdir(tmp_path)
    ctx = _ctx(tmp_path, store, task_id)
    listing = execute_model_tool(ctx, "inspect_local", {"path": str(shots)})
    assert listing["ok"] is True
    assert listing["directory"] is True
    assert "SECRETBYTES" not in str(listing)
    assert any(entry["name"] == "01.png" for entry in listing["entries"])
    binary = execute_model_tool(ctx, "inspect_local", {"path": str(png)})
    assert binary["ok"] is True
    assert binary["binary"] is True
    assert "SECRETBYTES" not in str(binary)
    store.close()


def test_inspect_local_strips_credentials_from_config_toml(tmp_path):
    cfg_dir = tmp_path / ".asc"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "config.toml"
    cfg_path.write_text(
        "[credentials]\nissuer_id = \"keep-me-secret\"\nkey_file = \"/tmp/AuthKey_X.p8\"\n"
        "[build]\nscheme = \"App\"\n",
        encoding="utf-8",
    )
    store = TaskStore(tmp_path / "tasks.db")
    ctx = _ctx(tmp_path, store)
    out = execute_model_tool(ctx, "inspect_local", {"path": str(cfg_path)})
    blob = str(out)
    assert out["ok"] is True
    assert "keep-me-secret" not in blob
    assert "AuthKey_X.p8" not in blob
    assert "App" in blob
    store.close()


def test_list_failed_tasks_omits_log_bodies(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    failed = store.create("iap", profile="myapp")
    done = store.create("iap", profile="myapp")
    store.append_log(failed, "secret failure body")
    store.set_status(failed, TaskStatus.ERROR)
    store.set_status(done, TaskStatus.DONE)
    result = execute_model_tool(_ctx(tmp_path, store), "list_failed_tasks", {"limit": 20})
    assert result["ok"] is True
    ids = [row["id"] for row in result["tasks"]]
    assert failed in ids
    assert done not in ids
    assert all("logs" not in row for row in result["tasks"])
    assert "secret failure body" not in str(result)
    store.close()


def test_get_profile_context_uses_bound_profile_and_strips_secrets(tmp_path):
    cfg_dir = tmp_path / ".asc"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text(
        "[credentials]\nissuer_id = \"leak-me\"\n[defaults]\ncsv = \"data/app.csv\"\n"
        "[build]\nscheme = \"App\"\nsigning = \"manual\"\n",
        encoding="utf-8",
    )
    store = TaskStore(tmp_path / "tasks.db")
    replay = {
        "kind": "build",
        "profile": "myapp",
        "verbose": False,
        "params": {"signing": "manual"},
    }
    task_id = store.create("build", profile="myapp", replay=replay)
    result = execute_model_tool(_ctx(tmp_path, store, task_id), "get_profile_context", {})
    blob = str(result)
    assert result["ok"] is True
    assert result["name"] == "myapp"
    assert result["build"]["scheme"] == "App"
    assert "leak-me" not in blob
    assert "issuer_id" not in blob
    store.close()


def test_propose_fix_inserts_draft_without_touching_csv(tmp_path, monkeypatch):
    from asc.web.agent_store import AgentStore
    from asc.web.agent_tools import AgentToolContext, execute_model_tool
    from asc.web.tasks import TaskStore

    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    before = csv_path.read_bytes()
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}}
    task_id = tasks.create("metadata", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    monkeypatch.chdir(tmp_path)
    result = execute_model_tool(ctx, "propose_fix", {
        "summary": "truncate keywords",
        "plan_id": "model-supplied-id",
        "mutations": [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "zh-Hans",
            "fields": {"keywords": "new"},
            "before": {"keywords": "oldkeywords"},
        }],
        "rerun": {"task_id": task_id, "kind": "metadata"},
        "manual_steps": [],
    })
    assert result["ok"] is True
    assert result["status"] == "draft"
    assert result["plan_id"] != "model-supplied-id"
    plan = agents.get_plan(result["plan_id"])
    assert plan["status"] == "draft"
    assert csv_path.read_bytes() == before
    assert tasks.get_state(task_id)["has_replay"] is True
    tasks.close()
    agents.close()


def test_propose_fix_rejects_credentials_toml_and_empty_rerun(tmp_path):
    from asc.web.agent_store import AgentStore
    from asc.web.agent_tools import AgentToolContext, execute_model_tool
    from asc.web.tasks import TaskStore

    cfg_dir = tmp_path / ".asc"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "config.toml"
    cfg_path.write_text("[credentials]\nissuer_id = \"keep-me\"\n[build]\nscheme = \"App\"\n", encoding="utf-8")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {"kind": "build", "profile": "myapp", "verbose": False, "params": {}}
    task_id = tasks.create("build", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    cred = execute_model_tool(ctx, "propose_fix", {
        "summary": "steal creds",
        "mutations": [{
            "op": "toml_set",
            "path": str(cfg_path),
            "key": "credentials.issuer_id",
            "value": "hacked",
        }],
        "manual_steps": [],
    })
    assert cred["ok"] is False
    assert "credential" in cred["error"].lower()
    empty_rerun = execute_model_tool(ctx, "propose_fix", {
        "summary": "manual only",
        "mutations": [],
        "rerun": {"task_id": task_id, "kind": "build"},
        "manual_steps": ["fix in Xcode"],
    })
    assert empty_rerun["ok"] is False
    assert "rerun" in empty_rerun["error"].lower()
    unknown = execute_model_tool(ctx, "propose_fix", {
        "summary": "nope",
        "mutations": [{"op": "shell", "path": "/tmp/x"}],
        "manual_steps": [],
    })
    assert unknown["ok"] is False
    assert agents.list_plans(session["id"]) == []
    assert "keep-me" in cfg_path.read_text(encoding="utf-8")
    tasks.close()
    agents.close()


def test_propose_fix_manual_steps_only_inserts_draft(tmp_path):
    from asc.web.agent_store import AgentStore
    from asc.web.agent_tools import AgentToolContext, execute_model_tool
    from asc.web.tasks import TaskStore

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    task_id = tasks.create("update", profile="system")
    session = agents.get_or_create_session(task_id, "system")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    result = execute_model_tool(ctx, "propose_fix", {
        "summary": "update from GitHub",
        "mutations": [],
        "manual_steps": ["check network and retry from the form"],
    })
    assert result["ok"] is True
    assert result["status"] == "draft"
    plan = agents.get_plan(result["plan_id"])
    assert plan["status"] == "draft"
    assert plan["mutations"] == []
    assert plan["rerun"] is None
    tasks.close()
    agents.close()


def test_propose_fix_json_patch_and_toml_rules(tmp_path):
    from asc.web.agent_store import AgentStore
    from asc.web.agent_tools import AgentToolContext, execute_model_tool
    from asc.web.tasks import TaskStore

    iap_path = tmp_path / "iap_packages.json"
    iap_path.write_text('{"items":[{"name":"Old","sku":"sku1"}]}', encoding="utf-8")
    before_iap = iap_path.read_bytes()
    cfg_dir = tmp_path / ".asc"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "config.toml"
    cfg_path.write_text("[build]\nscheme = \"App\"\nsigning = \"auto\"\n", encoding="utf-8")
    before_toml = cfg_path.read_bytes()
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {
        "kind": "iap",
        "profile": "myapp",
        "verbose": False,
        "params": {"iap_file": str(iap_path)},
    }
    task_id = tasks.create("iap", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    ok_patch = execute_model_tool(ctx, "propose_fix", {
        "summary": "rename IAP",
        "mutations": [{
            "op": "json_patch",
            "path": str(iap_path),
            "patch": [{"op": "replace", "path": "/items/0/name", "value": "New"}],
        }],
        "manual_steps": [],
    })
    assert ok_patch["ok"] is True
    assert agents.get_plan(ok_patch["plan_id"])["status"] == "draft"
    bad_op = execute_model_tool(ctx, "propose_fix", {
        "summary": "copy",
        "mutations": [{
            "op": "json_patch",
            "path": str(iap_path),
            "patch": [{"op": "copy", "from": "/items/0/name", "path": "/items/0/description"}],
        }],
        "manual_steps": [],
    })
    assert bad_op["ok"] is False
    bad_ptr = execute_model_tool(ctx, "propose_fix", {
        "summary": "sku",
        "mutations": [{
            "op": "json_patch",
            "path": str(iap_path),
            "patch": [{"op": "replace", "path": "/items/0/sku", "value": "hack"}],
        }],
        "manual_steps": [],
    })
    assert bad_ptr["ok"] is False
    ok_toml = execute_model_tool(ctx, "propose_fix", {
        "summary": "scheme",
        "mutations": [{
            "op": "toml_set",
            "path": str(cfg_path),
            "key": "build.scheme",
            "value": "App2",
        }],
        "manual_steps": [],
    })
    assert ok_toml["ok"] is True
    bad_signing = execute_model_tool(ctx, "propose_fix", {
        "summary": "signing",
        "mutations": [{
            "op": "toml_set",
            "path": str(cfg_path),
            "key": "build.signing",
            "value": "adhoc",
        }],
        "manual_steps": [],
    })
    assert bad_signing["ok"] is False
    assert iap_path.read_bytes() == before_iap
    assert cfg_path.read_bytes() == before_toml
    tasks.close()
    agents.close()


def test_propose_fix_text_replace_and_screenshot_fs_guards(tmp_path):
    from asc.web.agent_store import AgentStore
    from asc.web.agent_tools import AgentToolContext, execute_model_tool
    from asc.web.tasks import TaskStore

    notes = tmp_path / "whats_new.txt"
    notes.write_text("Bug fixes.\n", encoding="utf-8")
    shots = tmp_path / "screenshots"
    shots.mkdir()
    shot = shots / "01.png"
    shot.write_bytes(b"png")
    review = tmp_path / "review.png"
    review.write_bytes(b"png")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")

    paste_id = tasks.create(
        "whats-new",
        profile="myapp",
        replay={"kind": "whats-new", "profile": "myapp", "verbose": False, "params": {"text": "Bug fixes."}},
    )
    paste_session = agents.get_or_create_session(paste_id, "myapp")
    paste_ctx = AgentToolContext(
        tasks, agents, paste_id, tmp_path, turn_seq=1, session_id=paste_session["id"],
    )
    paste = execute_model_tool(paste_ctx, "propose_fix", {
        "summary": "edit pasted text",
        "mutations": [{
            "op": "text_replace",
            "path": str(notes),
            "before": "Bug fixes.",
            "after": "New notes.",
            "count": 1,
        }],
        "manual_steps": [],
    })
    assert paste["ok"] is False

    file_id = tasks.create(
        "whats-new",
        profile="myapp",
        replay={
            "kind": "whats-new",
            "profile": "myapp",
            "verbose": False,
            "params": {"source_file": str(notes)},
        },
    )
    file_session = agents.get_or_create_session(file_id, "myapp")
    file_ctx = AgentToolContext(
        tasks, agents, file_id, tmp_path, turn_seq=1, session_id=file_session["id"],
    )
    file_ok = execute_model_tool(file_ctx, "propose_fix", {
        "summary": "edit file",
        "mutations": [{
            "op": "text_replace",
            "path": str(notes),
            "before": "Bug fixes.",
            "after": "New notes.",
            "count": 1,
        }],
        "manual_steps": [],
    })
    assert file_ok["ok"] is True
    assert notes.read_text(encoding="utf-8") == "Bug fixes.\n"

    review_id = tasks.create(
        "iap-review-screenshots",
        profile="myapp",
        replay={
            "kind": "iap-review-screenshots",
            "profile": "myapp",
            "verbose": False,
            "params": {
                "items": [{"kind": "iap", "id": "1", "productId": "p", "path": str(review)}],
                "screenshots_dir": str(shots),
            },
        },
    )
    review_session = agents.get_or_create_session(review_id, "myapp")
    review_ctx = AgentToolContext(
        tasks, agents, review_id, tmp_path, turn_seq=1, session_id=review_session["id"],
    )
    outside = execute_model_tool(review_ctx, "propose_fix", {
        "summary": "touch review item",
        "mutations": [{"op": "screenshot_fs", "path": str(review), "action": "delete"}],
        "manual_steps": [],
    })
    assert outside["ok"] is False
    inside = execute_model_tool(review_ctx, "propose_fix", {
        "summary": "rename shot",
        "mutations": [{"op": "screenshot_fs", "path": str(shot), "action": "rename", "new_name": "02.png"}],
        "manual_steps": [],
    })
    assert inside["ok"] is True
    assert shot.exists()
    tasks.close()
    agents.close()


def test_propose_fix_rejects_bad_csv_fields_and_missing_session(tmp_path):
    from asc.web.agent_store import AgentStore
    from asc.web.agent_tools import AgentToolContext, execute_model_tool
    from asc.web.tasks import TaskStore

    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,old\n", encoding="utf-8")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}}
    task_id = tasks.create("metadata", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    no_locale = execute_model_tool(ctx, "propose_fix", {
        "summary": "no locale",
        "mutations": [{"op": "csv_set_fields", "path": str(csv_path), "fields": {"keywords": "x"}}],
        "manual_steps": [],
    })
    assert no_locale["ok"] is False
    assert "locale" in no_locale["error"].lower()
    bad_field = execute_model_tool(ctx, "propose_fix", {
        "summary": "bad field",
        "mutations": [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "zh-Hans",
            "fields": {"issuer_id": "nope"},
        }],
        "manual_steps": [],
    })
    assert bad_field["ok"] is False
    assert "field" in bad_field["error"].lower()
    no_session = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id="")
    missing = execute_model_tool(no_session, "propose_fix", {
        "summary": "ok shape",
        "mutations": [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "zh-Hans",
            "fields": {"keywords": "new"},
        }],
        "manual_steps": [],
    })
    assert missing["ok"] is False
    assert "session" in missing["error"].lower()
    assert agents.list_plans(session["id"]) == []
    assert csv_path.read_text(encoding="utf-8") == "locale,keywords\nzh-Hans,old\n"
    tasks.close()
    agents.close()
