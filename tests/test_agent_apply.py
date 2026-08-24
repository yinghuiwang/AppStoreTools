from __future__ import annotations

from asc.web.agent_store import AgentStore
from asc.web.agent_tools import AgentToolContext, apply_fix, execute_model_tool
from asc.web.tasks import TaskStore


def _pending_csv_plan(tmp_path):
    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}}
    task_id = tasks.create("metadata", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    proposed = execute_model_tool(ctx, "propose_fix", {
        "summary": "truncate keywords",
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
    return csv_path, tasks, agents, ctx, proposed["plan_id"]


def test_csv_set_fields_appends_missing_locale(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,name,keywords\nzh-Hans,旧名,oldkeywords\n", encoding="utf-8")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}}
    task_id = tasks.create("metadata", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    proposed = execute_model_tool(ctx, "propose_fix", {
        "summary": "add ja locale",
        "mutations": [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "ja",
            "fields": {"name": "アプリ"},
        }],
        "manual_steps": [],
    })
    assert proposed["ok"] is True
    agents.promote_drafts(ctx.session_id, 1)
    result = apply_fix(ctx, proposed["plan_id"])
    assert result["ok"] is True
    text = csv_path.read_text(encoding="utf-8")
    assert "ja" in text
    assert "アプリ" in text
    assert "zh-Hans" in text
    assert "oldkeywords" in text
    tasks.close()
    agents.close()


def test_apply_fix_updates_csv_when_pending(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    csv_path, tasks, agents, ctx, plan_id = _pending_csv_plan(tmp_path)
    agents.promote_drafts(ctx.session_id, 1)
    result = apply_fix(ctx, plan_id)
    assert result["ok"] is True
    assert agents.get_plan(plan_id)["status"] == "applied"
    assert "new" in csv_path.read_text(encoding="utf-8")
    tasks.close()
    agents.close()


def test_apply_fix_draft_is_conflict(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    csv_path, tasks, agents, ctx, plan_id = _pending_csv_plan(tmp_path)
    before = csv_path.read_bytes()
    result = apply_fix(ctx, plan_id)
    assert result["ok"] is False
    assert result.get("code") == "conflict"
    assert csv_path.read_bytes() == before
    assert agents.get_plan(plan_id)["status"] == "draft"
    tasks.close()
    agents.close()


def test_apply_fix_before_mismatch_sets_apply_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    csv_path, tasks, agents, ctx, plan_id = _pending_csv_plan(tmp_path)
    agents.promote_drafts(ctx.session_id, 1)
    csv_path.write_text("locale,keywords\nzh-Hans,hand-edited\n", encoding="utf-8")
    result = apply_fix(ctx, plan_id)
    assert result["ok"] is False
    assert agents.get_plan(plan_id)["status"] == "apply_failed"
    assert "hand-edited" in csv_path.read_text(encoding="utf-8")
    assert result.get("failed_step", {}).get("index") == 0
    assert result.get("failed_step", {}).get("op") == "csv_set_fields"
    tasks.close()
    agents.close()


def test_apply_fix_json_patch_and_toml_preserve_credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    iap_path = tmp_path / "iap_packages.json"
    iap_path.write_text(
        '{"items":[{"name":"Old","sku":"sku1","price":"0.99"}]}',
        encoding="utf-8",
    )
    cfg_dir = tmp_path / ".asc"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "config.toml"
    cfg_path.write_text(
        "[credentials]\nissuer_id = \"keep-me\"\nkey_id = \"ABCD\"\n"
        "[build]\nscheme = \"App\"\nsigning = \"auto\"\n",
        encoding="utf-8",
    )
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
    proposed = execute_model_tool(ctx, "propose_fix", {
        "summary": "rename IAP and scheme",
        "mutations": [
            {
                "op": "json_patch",
                "path": str(iap_path),
                "patch": [{"op": "replace", "path": "/items/0/name", "value": "New"}],
            },
            {
                "op": "toml_set",
                "path": str(cfg_path),
                "key": "build.scheme",
                "value": "App2",
            },
        ],
        "manual_steps": [],
    })
    assert proposed["ok"] is True
    agents.promote_drafts(ctx.session_id, 1)
    result = apply_fix(ctx, proposed["plan_id"])
    assert result["ok"] is True
    assert '"New"' in iap_path.read_text(encoding="utf-8")
    assert '"sku1"' in iap_path.read_text(encoding="utf-8")
    toml_text = cfg_path.read_text(encoding="utf-8")
    assert 'scheme = "App2"' in toml_text or "scheme = 'App2'" in toml_text
    assert "keep-me" in toml_text
    assert "issuer_id" in toml_text
    tasks.close()
    agents.close()


def test_apply_fix_text_replace_count_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "whats_new.txt"
    notes.write_text("Bug fixes.\nBug fixes.\n", encoding="utf-8")
    before = notes.read_bytes()
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {
        "kind": "whats-new",
        "profile": "myapp",
        "verbose": False,
        "params": {"source_file": str(notes)},
    }
    task_id = tasks.create("whats-new", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    proposed = execute_model_tool(ctx, "propose_fix", {
        "summary": "edit notes",
        "mutations": [{
            "op": "text_replace",
            "path": str(notes),
            "before": "Bug fixes.",
            "after": "New notes.",
            "count": 1,
        }],
        "manual_steps": [],
    })
    assert proposed["ok"] is True
    agents.promote_drafts(ctx.session_id, 1)
    result = apply_fix(ctx, proposed["plan_id"])
    assert result["ok"] is False
    assert agents.get_plan(proposed["plan_id"])["status"] == "apply_failed"
    assert notes.read_bytes() == before
    tasks.close()
    agents.close()


def test_apply_fix_screenshot_rename_blocks_escape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shots = tmp_path / "screenshots"
    shots.mkdir()
    shot = shots / "01.png"
    shot.write_bytes(b"png")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {
        "kind": "metadata",
        "profile": "myapp",
        "verbose": False,
        "params": {"screenshots_dir": str(shots)},
    }
    task_id = tasks.create("metadata", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    proposed = execute_model_tool(ctx, "propose_fix", {
        "summary": "rename shot",
        "mutations": [{
            "op": "screenshot_fs",
            "path": str(shot),
            "action": "rename",
            "new_name": "../escape.png",
        }],
        "manual_steps": [],
    })
    assert proposed["ok"] is True
    agents.promote_drafts(ctx.session_id, 1)
    result = apply_fix(ctx, proposed["plan_id"])
    assert result["ok"] is False
    assert agents.get_plan(proposed["plan_id"])["status"] == "apply_failed"
    assert shot.exists()
    assert not (tmp_path / "escape.png").exists()
    tasks.close()
    agents.close()


def test_apply_fix_text_replace_and_screenshot_rename_succeed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "whats_new.txt"
    notes.write_text("Bug fixes.\n", encoding="utf-8")
    shots = tmp_path / "screenshots"
    shots.mkdir()
    shot = shots / "01.png"
    shot.write_bytes(b"png")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {
        "kind": "whats-new",
        "profile": "myapp",
        "verbose": False,
        "params": {"source_file": str(notes), "screenshots_dir": str(shots)},
    }
    task_id = tasks.create("whats-new", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    proposed = execute_model_tool(ctx, "propose_fix", {
        "summary": "edit notes and rename shot",
        "mutations": [
            {
                "op": "text_replace",
                "path": str(notes),
                "before": "Bug fixes.",
                "after": "New notes.",
                "count": 1,
            },
            {
                "op": "screenshot_fs",
                "path": str(shot),
                "action": "rename",
                "new_name": "02.png",
            },
        ],
        "manual_steps": [],
    })
    assert proposed["ok"] is True
    agents.promote_drafts(ctx.session_id, 1)
    result = apply_fix(ctx, proposed["plan_id"])
    assert result["ok"] is True
    assert notes.read_text(encoding="utf-8") == "New notes.\n"
    assert not shot.exists()
    assert (shots / "02.png").read_bytes() == b"png"
    tasks.close()
    agents.close()


def test_apply_fix_rolls_back_previous_steps(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    csv_path = tmp_path / "app.csv"
    csv_original = "locale,keywords\nzh-Hans,oldkeywords\n"
    csv_path.write_text(csv_original, encoding="utf-8")
    notes = tmp_path / "whats_new.txt"
    notes.write_text("Bug fixes.\nBug fixes.\n", encoding="utf-8")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {
        "kind": "metadata",
        "profile": "myapp",
        "verbose": False,
        "params": {"csv_path": str(csv_path), "source_file": str(notes)},
    }
    task_id = tasks.create("metadata", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    proposed = execute_model_tool(ctx, "propose_fix", {
        "summary": "csv then bad replace",
        "mutations": [
            {
                "op": "csv_set_fields",
                "path": str(csv_path),
                "locale": "zh-Hans",
                "fields": {"keywords": "new"},
                "before": {"keywords": "oldkeywords"},
            },
            {
                "op": "text_replace",
                "path": str(notes),
                "before": "Bug fixes.",
                "after": "New notes.",
                "count": 1,
            },
        ],
        "manual_steps": [],
    })
    assert proposed["ok"] is True
    agents.promote_drafts(ctx.session_id, 1)
    result = apply_fix(ctx, proposed["plan_id"])
    assert result["ok"] is False
    assert agents.get_plan(proposed["plan_id"])["status"] == "apply_failed"
    assert result["failed_step"]["index"] == 1
    assert result["failed_step"]["op"] == "text_replace"
    assert csv_path.read_text(encoding="utf-8") == csv_original
    assert notes.read_text(encoding="utf-8") == "Bug fixes.\nBug fixes.\n"
    tasks.close()
    agents.close()


def test_apply_fix_rolls_back_created_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    notes = tmp_path / "whats_new.txt"
    notes.write_text("Bug fixes.\nBug fixes.\n", encoding="utf-8")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {
        "kind": "whats-new",
        "profile": "myapp",
        "verbose": False,
        "params": {"source_file": str(notes)},
    }
    task_id = tasks.create("whats-new", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    created = tmp_path / "fresh.txt"
    proposed = execute_model_tool(ctx, "propose_fix", {
        "summary": "create then bad replace",
        "mutations": [
            {"op": "file_create", "path": "fresh.txt", "content": "fresh\n"},
            {
                "op": "text_replace",
                "path": str(notes),
                "before": "Bug fixes.",
                "after": "New notes.",
                "count": 1,
            },
        ],
        "manual_steps": [],
    })
    assert proposed["ok"] is True
    agents.promote_drafts(ctx.session_id, 1)
    result = apply_fix(ctx, proposed["plan_id"])
    assert result["ok"] is False
    assert agents.get_plan(proposed["plan_id"])["status"] == "apply_failed"
    assert not created.exists()
    assert notes.read_text(encoding="utf-8") == "Bug fixes.\nBug fixes.\n"
    tasks.close()
    agents.close()


def test_apply_fix_is_not_a_model_tool():
    from asc.web.agent_tools import MODEL_TOOL_NAMES, OPENAI_TOOLS

    names = {item["function"]["name"] for item in OPENAI_TOOLS}
    assert "apply_fix" not in names
    assert "apply_fix" not in MODEL_TOOL_NAMES
    assert "rerun_task" not in names
    assert "rerun_task" not in MODEL_TOOL_NAMES


def test_rerun_task_creates_new_id_and_keeps_old_error(tmp_path, monkeypatch):
    from asc.web.agent_rerun import rerun_task
    from asc.web.task_runner import sanitize_replay
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    replay = sanitize_replay("update", "system", False, {"version": "0.1.26", "branch": ""})
    old = store.create("update", profile="system", replay=replay)
    store.set_status(old, TaskStatus.ERROR)
    created = []

    def fake_start(store_arg, *, kind, profile, verbose, run, task_id=None, **kwargs):
        created.append((kind, profile, task_id))
        return task_id

    monkeypatch.setattr("asc.web.task_runner.start_background_task", fake_start)
    monkeypatch.setattr("asc.web.routes_api.start_background_task", fake_start)
    new_id = rerun_task(old, task_store=store)
    assert new_id != old
    assert store.get_state(old)["status"] in (TaskStatus.ERROR, "error")
    assert store.get_state(new_id) is not None
    store.close()


def test_rerun_without_replay_does_not_create(tmp_path):
    from asc.web.agent_rerun import RerunError, rerun_task
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    old = store.create("metadata", profile="myapp")  # no replay
    try:
        rerun_task(old, task_store=store)
        assert False, "expected RerunError"
    except RerunError as exc:
        assert "no_replay" in str(exc)
    assert len(store.list_recent_states(limit=10)) == 1
    store.close()


def test_rerun_unknown_kind_does_not_create(tmp_path):
    from asc.web.agent_rerun import RerunError, rerun_task
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    replay = {"kind": "not-a-web-kind", "profile": "myapp", "verbose": False, "params": {}}
    old = store.create("metadata", profile="myapp", replay=replay)
    try:
        rerun_task(old, task_store=store)
        assert False, "expected RerunError"
    except RerunError as exc:
        assert "no_replay" in str(exc)
    assert len(store.list_recent_states(limit=10)) == 1
    store.close()


def test_hallucinated_rerun_task_does_not_create(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    out = execute_model_tool(
        AgentToolContext(store, None, None, tmp_path, turn_seq=1),
        "rerun_task",
        {"task_id": "x"},
    )
    assert out["ok"] is False
    assert "gated" in out["error"]
    assert store.list_recent_states(limit=10) == []
    store.close()


def test_apply_fix_does_not_create_or_rerun(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    csv_path, tasks, agents, ctx, plan_id = _pending_csv_plan(tmp_path)
    agents.promote_drafts(ctx.session_id, 1)
    before_ids = [row["id"] for row in tasks.list_recent_states(limit=20)]
    result = apply_fix(ctx, plan_id)
    assert result["ok"] is True
    after_ids = [row["id"] for row in tasks.list_recent_states(limit=20)]
    assert after_ids == before_ids
    tasks.close()
    agents.close()


def test_rerun_metadata_uses_replay_params_not_secrets(tmp_path, monkeypatch):
    from asc.web.agent_rerun import rerun_task
    from asc.web.task_runner import sanitize_replay
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    replay = sanitize_replay(
        "metadata",
        "myapp",
        True,
        {
            "csv_path": "data/appstore_info.csv",
            "screenshots_dir": "data/screenshots",
            "include_metadata": True,
            "include_screenshots": False,
            "dry_run": True,
            "locales": ["zh-Hans"],
            "issuer_id": "SECRET-ISSUER",
            "key_file": "/tmp/AuthKey_X.p8",
        },
    )
    old = store.create("metadata", profile="myapp", replay=replay)
    store.set_status(old, TaskStatus.ERROR)

    def fake_start(store_arg, *, kind, profile, verbose, run, task_id=None, **kwargs):
        return task_id

    monkeypatch.setattr("asc.web.task_runner.start_background_task", fake_start)
    monkeypatch.setattr("asc.web.routes_api.start_background_task", fake_start)
    new_id = rerun_task(old, task_store=store)
    stored = store.get_replay(new_id)
    assert stored["kind"] == "metadata"
    assert stored["profile"] == "myapp"
    assert stored["verbose"] is True
    assert stored["params"]["csv_path"] == "data/appstore_info.csv"
    assert stored["params"]["include_screenshots"] is False
    assert stored["params"]["locales"] == ["zh-Hans"]
    assert "issuer_id" not in stored["params"]
    assert "key_file" not in stored["params"]
    assert store.get_state(old)["status"] in (TaskStatus.ERROR, "error")
    store.close()


def test_rerun_build_omits_certificate_fields(tmp_path, monkeypatch):
    from asc.web.agent_rerun import rerun_task
    from asc.web.task_runner import sanitize_replay
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    replay = sanitize_replay(
        "build",
        "myapp",
        False,
        {
            "mode": "build",
            "project": "App.xcodeproj",
            "scheme": "App",
            "destination": "testflight",
            "ipa_path": "",
            "signing": "manual",
            "dry_run": True,
            "certificate": "iPhone Distribution: Secret",
            "provisioning_profile": "secret-profile",
        },
    )
    old = store.create("build", profile="myapp", replay=replay)
    store.set_status(old, TaskStatus.ERROR)

    def fake_start(store_arg, *, kind, profile, verbose, run, task_id=None, **kwargs):
        return task_id

    monkeypatch.setattr("asc.web.task_runner.start_background_task", fake_start)
    monkeypatch.setattr("asc.web.routes_api.start_background_task", fake_start)
    new_id = rerun_task(old, task_store=store)
    params = store.get_replay(new_id)["params"]
    assert params["signing"] == "manual"
    assert params["project"] == "App.xcodeproj"
    assert "certificate" not in params
    assert "provisioning_profile" not in params
    store.close()


def test_rerun_remaining_kinds_dispatch(tmp_path, monkeypatch):
    from asc.web.agent_rerun import rerun_task
    from asc.web.task_runner import sanitize_replay
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")

    def fake_start(store_arg, *, kind, profile, verbose, run, task_id=None, **kwargs):
        return task_id

    monkeypatch.setattr("asc.web.task_runner.start_background_task", fake_start)
    monkeypatch.setattr("asc.web.routes_api.start_background_task", fake_start)
    monkeypatch.setattr("asc.web.routes_listing.start_background_task", fake_start)

    cases = [
        ("iap", {"iap_file": "data/iap_packages.json", "dry_run": True, "update_existing": False}),
        (
            "urls",
            {
                "field": "supportUrl",
                "url": "https://example.com/s",
                "locales": ["en-US"],
                "dry_run": True,
            },
        ),
        ("whats-new", {"dry_run": True, "text": "hello", "locales": ["en-US"]}),
        ("whats-new-translate", {"text": "hello", "source_locale": "en-US"}),
        (
            "listing-pull-screenshots",
            {
                "screenshots_dir": "data/screenshots",
                "scopes": [{"locale": "en-US", "display_type": "APP_IPHONE_67"}],
            },
        ),
        (
            "iap-review-screenshots",
            {
                "dry_run": True,
                "items": [{"kind": "iap", "id": "x", "productId": "sku", "path": "shot.png"}],
            },
        ),
    ]
    for kind, params in cases:
        replay = sanitize_replay(kind, "myapp", False, params)
        old = store.create(kind, profile="myapp", replay=replay)
        store.set_status(old, TaskStatus.ERROR)
        new_id = rerun_task(old, task_store=store)
        assert new_id != old
        stored = store.get_replay(new_id)
        assert stored["kind"] == kind
        assert store.get_state(old)["status"] in (TaskStatus.ERROR, "error")
        for key, value in params.items():
            assert stored["params"][key] == value
    store.close()
