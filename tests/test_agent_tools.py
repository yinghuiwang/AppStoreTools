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


def test_openai_tools_are_exactly_six_readonly_or_propose():
    names = {t["function"]["name"] for t in OPENAI_TOOLS}
    assert names == set(MODEL_TOOL_NAMES)
    assert "apply_fix" not in names
    assert "rerun_task" not in names


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
