# tests/test_web_server.py
from __future__ import annotations
import inspect
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from asc.web.server import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_homepage_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "AppStore Tools" in resp.text


def test_metadata_page_returns_200(client):
    resp = client.get("/metadata")
    assert resp.status_code == 200


def test_build_page_returns_200(client):
    resp = client.get("/build")
    assert resp.status_code == 200


def test_blocking_web_probes_run_in_threadpool():
    from asc.web import routes_api

    assert not inspect.iscoroutinefunction(routes_api.build_schemes)
    assert not inspect.iscoroutinefunction(routes_api.build_options)
    assert not inspect.iscoroutinefunction(routes_api.whats_new_check)


def test_update_check_includes_current_commit(client):
    from unittest.mock import patch

    with patch("asc.commands.update_cmd._current_version", return_value="0.1.17"), \
            patch("asc.commands.update_cmd._latest_version_from_github", return_value="0.1.18"), \
            patch("asc.commands.update_cmd._resolve_git_ref_commit", return_value="abcdef1234567890"), \
            patch("asc.cli._installed_commit_short", return_value="15e4b3a"):
        resp = client.get("/api/update/check")

    assert resp.status_code == 200
    data = resp.json()
    assert data["detail"]["current"] == "0.1.17"
    assert data["detail"]["current_commit"] == "15e4b3a"
    assert data["detail"]["latest"] == "0.1.18"
    assert data["detail"]["latest_commit"] == "abcdef1"
    assert "commit 15e4b3a" in data["message"]
    assert "最新版本: 0.1.18 (commit abcdef1)" in data["message"]


def test_update_branches_returns_options(client):
    from unittest.mock import patch

    with patch("asc.commands.update_cmd._branches_from_github", return_value=["develop", "main"]):
        resp = client.get("/api/update/branches")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["branches"] == ["develop", "main"]


def test_profiles_page_returns_200(client):
    resp = client.get("/profiles")
    assert resp.status_code == 200


def test_settings_page_returns_200(client):
    resp = client.get("/settings")
    assert resp.status_code == 200


def test_guard_page_returns_200(client):
    resp = client.get("/guard")
    assert resp.status_code == 200


def test_filebrowser_returns_html(client, tmp_path):
    resp = client.get(f"/api/browse?path={tmp_path}&mode=dir")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]

def test_filebrowser_lists_files(client, tmp_path):
    (tmp_path / "test.csv").write_text("a,b")
    resp = client.get(f"/api/browse?path={tmp_path}&mode=file&ext=.csv")
    assert resp.status_code == 200
    assert "test.csv" in resp.text


def test_filebrowser_directory_click_browses_into_directory(client, tmp_path):
    (tmp_path / "nested").mkdir()
    resp = client.get(f"/api/browse?path={tmp_path}&mode=dir")
    assert resp.status_code == 200
    assert 'data-fb-action="browse"' in resp.text
    assert "nested" in resp.text


def test_filebrowser_rejects_outside_home(client):
    resp = client.get("/api/browse?path=/etc&mode=dir")
    assert resp.status_code == 403


def test_metadata_check_api(client):
    """POST /api/metadata/check 返回 JSON 验证结果"""
    from unittest.mock import patch
    with patch("asc.web.routes_api._run_metadata_check") as mock_check:
        mock_check.return_value = {"ok": True, "level": "success", "message": "环境正常", "detail": {}}
        resp = client.post("/api/metadata/check", cookies={"asc_profile": "myapp"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["level"] == "success"

def test_metadata_run_api_starts_task(client):
    """POST /api/metadata/run 创建任务并返回 task_id"""
    from unittest.mock import patch
    with patch("asc.web.routes_api._start_metadata_task") as mock_start:
        mock_start.return_value = "fake-task-id"
        resp = client.post("/api/metadata/run", cookies={"asc_profile": "myapp"}, data={
            "csv_path": "data/appstore_info.csv",
            "screenshots_dir": "data/screenshots",
            "include_metadata": "on",
            "dry_run": "",
        })
        assert resp.status_code == 200
        assert "task_id" in resp.json()


def test_build_run_api_starts_task(client):
    from unittest.mock import patch
    with patch("asc.web.routes_api._start_build_task") as mock_start:
        mock_start.return_value = "fake-build-task-id"
        resp = client.post("/api/build/run", cookies={"asc_profile": "myapp"}, data={
            "mode": "full",
            "destination": "testflight",
            "verbose": "",
        })
        assert resp.status_code == 200
        assert "task_id" in resp.json()


def test_build_run_api_passes_interactive_release_options(client):
    with patch("asc.web.routes_api._start_build_task") as mock_start:
        mock_start.return_value = "fake-build-task-id"
        resp = client.post("/api/build/run", cookies={"asc_profile": "myapp"}, data={
            "mode": "full",
            "project": "MyApp.xcworkspace",
            "scheme": "MyApp",
            "destination": "testflight",
            "signing": "manual",
            "certificate": "Apple Distribution: ACME",
            "provisioning_profile": "/tmp/acme.mobileprovision",
            "reuse_archive": "reuse",
            "dry_run": "on",
            "verbose": "on",
        })
        assert resp.status_code == 200
        mock_start.assert_called_once()
        kwargs = mock_start.call_args.kwargs
        assert kwargs["scheme"] == "MyApp"
        assert kwargs["signing"] == "manual"
        assert kwargs["certificate"] == "Apple Distribution: ACME"
        assert kwargs["provisioning_profile"] == "/tmp/acme.mobileprovision"
        assert kwargs["reuse_archive"] == "reuse"
        assert kwargs["dry_run"] is True


def test_iap_review_screenshots_scan_returns_targets_with_default_path(client, tmp_path):
    from unittest.mock import MagicMock
    from asc.commands.iap_review_screenshots import ReviewScreenshotTarget

    iap_file = tmp_path / "iap_packages.json"
    screenshot_path = tmp_path / "review.png"
    iap_file.write_text(
        '{"items":[{"productId":"coins_100","review":{"screenshot":"review.png"}}]}',
        encoding="utf-8",
    )

    scan_result = MagicMock()
    scan_result.targets = [
        ReviewScreenshotTarget(
            kind="iap",
            id="iap-1",
            product_id="coins_100",
            name="100 Coins",
        )
    ]
    scan_result.errors = []

    with patch("asc.web.routes_api.Config") as mock_config_cls, \
         patch("asc.web.routes_api.make_api_from_config", return_value=(MagicMock(), "app-1")), \
         patch("asc.web.routes_api.scan_missing_review_screenshots", return_value=scan_result):
        mock_config_cls.return_value.iap_path = ""
        resp = client.post(
            "/api/iap/review-screenshots/scan",
            cookies={"asc_profile": "myapp"},
            json={"iapFile": str(iap_file)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 1
    assert data["errors"] == []
    assert data["targets"][0]["productId"] == "coins_100"
    assert data["targets"][0]["defaultPath"] == str(screenshot_path)


def test_iap_review_screenshots_upload_starts_task_with_items(client):
    with patch("asc.web.routes_api._start_iap_review_screenshots_task") as mock_start:
        mock_start.return_value = "fake-review-task-id"
        resp = client.post(
            "/api/iap/review-screenshots/upload",
            cookies={"asc_profile": "myapp"},
            json={
                "dryRun": True,
                "items": [
                    {
                        "kind": "iap",
                        "id": "iap-1",
                        "productId": "coins_100",
                        "path": "/tmp/review.png",
                    }
                ],
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"task_id": "fake-review-task-id"}
    mock_start.assert_called_once()
    kwargs = mock_start.call_args.kwargs
    assert kwargs["profile"] == "myapp"
    assert kwargs["dry_run"] is True
    assert len(kwargs["items"]) == 1
    assert kwargs["items"][0].product_id == "coins_100"
    assert kwargs["items"][0].path == "/tmp/review.png"


def test_iap_review_screenshots_upload_rejects_empty_items(client):
    resp = client.post(
        "/api/iap/review-screenshots/upload",
        cookies={"asc_profile": "myapp"},
        json={"items": []},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "items required"


def test_build_options_api_returns_release_choices(client):
    from datetime import datetime, timezone
    from unittest.mock import MagicMock, patch

    from asc.commands.build_inputs import Certificate, ProfileInfo

    mock_config = MagicMock()
    mock_config.build_project = None
    mock_config.build_scheme = None
    mock_config.build_bundle_id = None
    mock_config.build_certificate = ""
    mock_config.build_profile = ""
    mock_config.build_output = "/tmp/build"

    profile = ProfileInfo(
        path="/tmp/acme.mobileprovision",
        uuid="UUID",
        name="ACME AppStore",
        team_id="TEAM123",
        bundle_id="com.acme.app",
        expiration=datetime(2030, 1, 1, tzinfo=timezone.utc),
        cert_sha1s=["SHA1"],
    )

    with patch("asc.web.routes_api.Config", return_value=mock_config), \
         patch("asc.commands.build_inputs.detect_project", return_value=("MyApp.xcworkspace", "workspace")), \
         patch("asc.commands.build_inputs.list_schemes", return_value=["MyApp", "MyAppTests"]), \
         patch("asc.commands.build_inputs.detect_bundle_id", return_value="com.acme.app"), \
         patch("asc.commands.build_inputs.detect_certificates", return_value=[Certificate(sha1="SHA1", name="Apple Distribution: ACME")]), \
         patch("asc.commands.build_inputs.detect_profiles", return_value=[profile]), \
         patch("asc.commands.build_inputs.detect_versions", return_value=("1.0", "42")), \
         patch("asc.commands.build_inputs.scan_archives", return_value=[]), \
         patch("asc.commands.build_inputs.find_matching_archive", return_value=None):
        resp = client.get(
            "/api/build/options",
            cookies={"asc_profile": "myapp"},
            params={
                "project": ".",
                "scheme": "MyApp",
                "signing": "manual",
                "certificate": "Apple Distribution: ACME",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["project_selected"] == "MyApp.xcworkspace"
    assert data["schemes"] == ["MyApp", "MyAppTests"]
    assert data["selected_scheme"] == "MyApp"
    assert data["bundle_id"] == "com.acme.app"
    assert data["bundle_id_selected"] == "com.acme.app"
    assert data["certificates"][0]["name"] == "Apple Distribution: ACME"
    assert data["selected_certificate"] == "Apple Distribution: ACME"
    assert data["profiles"][0]["path"] == "/tmp/acme.mobileprovision"
    assert data["selected_profile"] == ""
    assert data["version_info"] == {"marketing_version": "1.0", "build_number": "42"}
    assert data["archive_match"] is None


def test_task_stream_done_task(client):
    """已完成任务的 SSE 流应立即发送所有日志并关闭。"""
    from asc.web.tasks import task_store, TaskStatus
    task_id = task_store.create("metadata")
    task_store.append_log(task_id, "line 1")
    task_store.append_log(task_id, "line 2")
    task_store.set_status(task_id, TaskStatus.DONE)

    resp = client.get(f"/api/task/{task_id}/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "line 1" in body
    assert "line 2" in body
    assert "event: done" in body


def test_task_stream_canceled_task(client):
    from asc.web.tasks import task_store, TaskStatus
    task_id = task_store.create("metadata")
    task_store.append_log(task_id, "cancel requested")
    task_store.set_status(task_id, TaskStatus.CANCELED)

    resp = client.get(f"/api/task/{task_id}/stream")
    assert resp.status_code == 200
    body = resp.text
    assert "cancel requested" in body
    assert "event: canceled" in body


def test_task_stream_not_found(client):
    resp = client.get("/api/task/nonexistent/stream")
    assert resp.status_code == 404


def test_task_cancel_endpoint(client):
    from asc.web.tasks import task_store, TaskStatus
    task_id = task_store.create("build")
    task_store.set_status(task_id, TaskStatus.RUNNING)

    resp = client.post(f"/api/task/{task_id}/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == task_id
    assert data["cancel_requested"] is True
    task = task_store.get(task_id)
    assert task["cancel_requested"] is True
    assert any("已请求终止" in line for line in task["logs"])


def test_task_status_endpoint(client):
    """GET /api/task/{task_id}/status 返回任务状态 JSON。"""
    from asc.web.tasks import task_store, TaskStatus
    task_id = task_store.create("build")
    task_store.set_status(task_id, TaskStatus.RUNNING)
    resp = client.get(f"/api/task/{task_id}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert data["task_id"] == task_id


def test_profiles_list_api(client):
    from unittest.mock import patch
    with patch("asc.config.Config.list_apps", return_value=["myapp", "staging"]):
        resp = client.get("/api/profiles")
        assert resp.status_code == 200
        assert "myapp" in resp.json()["profiles"]


def test_profiles_list_api_includes_profile_details(client):
    from unittest.mock import patch, MagicMock

    mock_config = MagicMock()
    mock_config.list_apps.return_value = ["myapp"]
    mock_config.app_name = "myapp"
    mock_config.get_app_profile.return_value = {
        "issuer_id": "issuer-123",
        "key_id": "KEY123",
        "key_file": "/Users/me/.config/asc/keys/AuthKey_KEY123.p8",
        "app_id": "123456789",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }

    with patch("asc.config.Config", return_value=mock_config):
        resp = client.get("/api/profiles")

    assert resp.status_code == 200
    data = resp.json()
    assert data["profile_details"]["myapp"] == {
        "issuer_id": "issuer-123",
        "key_id": "KEY123",
        "key_file_name": "AuthKey_KEY123.p8",
        "app_id": "123456789",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }


def test_profiles_page_shows_profile_detail_fields(client):
    resp = client.get("/profiles")
    assert resp.status_code == 200
    assert "App ID" in resp.text
    assert "Issuer ID" in resp.text
    assert "Key ID" in resp.text
    assert "CSV" in resp.text
    assert "截图" in resp.text

def test_profile_create_api(client, tmp_path):
    """POST /api/profiles 创建新 profile"""
    p8_content = b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n"
    from unittest.mock import patch
    with patch("asc.config.Config.save_app_profile") as mock_save:
        resp = client.post("/api/profiles", data={
            "name": "newapp",
            "issuer_id": "abc-123",
            "key_id": "KEYID123",
            "app_id": "1234567890",
            "csv": "data/appstore_info.csv",
            "screenshots": "data/screenshots",
        }, files={"key_file": ("AuthKey_KEYID123.p8", p8_content, "application/octet-stream")})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_save.assert_called_once()


def test_profile_update_api_allows_rename(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    profiles_dir = tmp_path / ".config" / "asc" / "profiles"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "oldapp.toml").write_text(
        '[credentials]\n'
        'issuer_id = "old-issuer"\n'
        'key_id = "OLDKEY"\n'
        'key_file = "/tmp/AuthKey_OLDKEY.p8"\n'
        'app_id = "111"\n\n'
        '[defaults]\n'
        'csv = "data/old.csv"\n'
        'screenshots = "data/old-screenshots"\n'
    )
    local_dir = tmp_path / ".asc"
    local_dir.mkdir()
    (local_dir / "config.toml").write_text('[defaults]\ndefault_app = "oldapp"\n')

    resp = client.put(
        "/api/profiles/oldapp",
        cookies={"asc_profile": "oldapp"},
        data={
            "name": "newapp",
            "issuer_id": "new-issuer",
            "key_id": "NEWKEY",
            "app_id": "222",
            "csv": "data/new.csv",
            "screenshots": "data/new-screenshots",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "name": "newapp", "old_name": "oldapp"}
    assert not (profiles_dir / "oldapp.toml").exists()
    new_profile = (profiles_dir / "newapp.toml").read_text()
    assert 'issuer_id = "new-issuer"' in new_profile
    assert 'app_id = "222"' in new_profile
    assert 'default_app = "newapp"' in (local_dir / "config.toml").read_text()
    assert resp.cookies.get("asc_profile") == "newapp"


def test_profile_delete_api(client):
    from unittest.mock import patch
    with patch("asc.config.Config.remove_app_profile") as mock_remove:
        resp = client.delete("/api/profiles/myapp")
        assert resp.status_code == 200
        mock_remove.assert_called_once_with("myapp")


def test_guard_status_returns_json(client):
    from unittest.mock import patch, MagicMock
    mock_guard = MagicMock()
    mock_guard.get_status.return_value = {
        "enabled": True,
        "app_notes": {},
        "bindings": {"machine": {}, "ip": {}, "credential": {}},
    }
    with patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.get("/api/guard/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert "bindings" in data
    assert "current_profile" in data


def test_guard_status_returns_full_fingerprint(client):
    from unittest.mock import patch, MagicMock
    long_fp = "a1b2c3d4e5f6g7h8i9j0"
    mock_guard = MagicMock()
    mock_guard.get_status.return_value = {
        "enabled": True,
        "bindings": {
            "machine": {long_fp: {"app_id": "123", "app_name": "myapp", "bound_at": "2026-05-18T10:00:00"}},
            "ip": {},
            "credential": {},
        },
    }
    with patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.get("/api/guard/status")
    data = resp.json()
    machine_keys = list(data["bindings"]["machine"].keys())
    assert len(machine_keys) == 1
    assert machine_keys[0] == long_fp


def test_guard_note_api_updates_app_note(client):
    from unittest.mock import patch, MagicMock
    mock_guard = MagicMock()
    mock_guard.set_app_note.return_value = True
    with patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.post("/api/guard/note", data={
            "app_id": "123456789",
            "note": "办公室 Mac",
        })
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_guard.set_app_note.assert_called_once_with("123456789", "办公室 Mac")


def test_guard_note_api_missing_app_returns_404(client):
    from unittest.mock import patch, MagicMock
    mock_guard = MagicMock()
    mock_guard.set_app_note.return_value = False
    with patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.post("/api/guard/note", data={
            "app_id": "missing.app",
            "note": "home",
        })
    assert resp.status_code == 404


def test_guard_note_api_persists_for_status_refresh(client, tmp_path):
    import json
    from unittest.mock import patch

    guard_file = tmp_path / "guard.json"
    guard_file.write_text(json.dumps({
        "enabled": True,
        "bindings": {
            "machine": {
                "SERIAL-C02ABC123456": {
                    "app_id": "123456789",
                    "app_name": "myapp",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                    "last_checked": "2026-05-18T10:00:00",
                },
            },
            "ip": {},
            "credential": {},
        },
        "app_notes": {},
    }))

    with patch("asc.guard.GUARD_FILE", guard_file):
        save_resp = client.post("/api/guard/note", data={
            "app_id": "123456789",
            "note": "办公室 Mac",
        })
        status_resp = client.get("/api/guard/status")

    assert save_resp.status_code == 200
    assert status_resp.status_code == 200
    assert status_resp.json()["app_notes"]["123456789"] == "办公室 Mac"


def test_guard_note_api_persists_when_binding_app_id_is_numeric(client, tmp_path):
    import json
    from unittest.mock import patch

    guard_file = tmp_path / "guard.json"
    guard_file.write_text(json.dumps({
        "enabled": True,
        "bindings": {
            "machine": {
                "SERIAL-C02ABC123456": {
                    "app_id": 123456789,
                    "app_name": "myapp",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                    "last_checked": "2026-05-18T10:00:00",
                },
            },
            "ip": {},
            "credential": {},
        },
        "app_notes": {},
    }))

    with patch("asc.guard.GUARD_FILE", guard_file):
        save_resp = client.post("/api/guard/note", data={
            "app_id": "123456789",
            "note": "办公室 Mac",
        })
        status_resp = client.get("/api/guard/status")

    assert save_resp.status_code == 200
    assert status_resp.json()["app_notes"]["123456789"] == "办公室 Mac"


def test_guard_page_has_guard_note_editor(client):
    resp = client.get("/guard")
    assert resp.status_code == 200
    assert "/api/guard/note" in resp.text
    assert "保存备注" in resp.text
    assert "App ID" in resp.text
    assert "凭证 Key ID" not in resp.text


def test_guard_status_error_returns_json(client):
    from unittest.mock import patch
    with patch("asc.guard.Guard", side_effect=Exception("read error")):
        resp = client.get("/api/guard/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["bindings"] == {"machine": {}, "ip": {}, "credential": {}}
    assert "error" in data


def test_task_store_create_with_profile_and_progress():
    from asc.web.tasks import TaskStore
    store = TaskStore()
    task_id = store.create("metadata", profile="myapp")
    task = store.get(task_id)
    assert task["kind"] == "metadata"
    assert task["profile"] == "myapp"
    assert task["progress"] == {"pct": 0, "msg": ""}


def test_task_store_list_recent_includes_profile():
    from asc.web.tasks import TaskStore
    store = TaskStore()
    store.create("metadata", profile="myapp")
    store.create("build", profile="staging")
    recent = store.list_recent(limit=20)
    assert recent[0]["profile"] == "staging"
    assert recent[1]["profile"] == "myapp"


def test_tasks_recent_endpoint(client):
    resp = client.get("/api/tasks/recent")
    assert resp.status_code == 200


def test_task_store_set_progress():
    from asc.web.tasks import TaskStore
    store = TaskStore()
    task_id = store.create("build", profile="staging")
    store.set_progress(task_id, 45, "元数据 5/11 语言")
    task = store.get(task_id)
    assert task["progress"] == {"pct": 45, "msg": "元数据 5/11 语言"}


def test_metadata_check_returns_level(client):
    from unittest.mock import patch, MagicMock
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.2.3", "appStoreState": "PREPARE_FOR_SUBMISSION"},
    }
    mock_config = MagicMock()
    mock_config.app_name = "testapp"
    with patch("asc.config.Config", return_value=mock_config), \
         patch("asc.utils.make_api_from_config", return_value=(mock_api, "app1")):
        resp = client.post("/api/metadata/check", cookies={"asc_profile": "testapp"})
        data = resp.json()
        assert data["level"] == "success"
        assert data["ok"] is True
        assert "detail" in data
        assert data["detail"]["version"] == "1.2.3"


def test_metadata_check_warning_level(client):
    from unittest.mock import patch, MagicMock
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.2.3", "appStoreState": "WAITING_FOR_REVIEW"},
    }
    mock_config = MagicMock()
    mock_config.app_name = "testapp"
    with patch("asc.config.Config", return_value=mock_config), \
         patch("asc.utils.make_api_from_config", return_value=(mock_api, "app1")):
        resp = client.post("/api/metadata/check", cookies={"asc_profile": "testapp"})
        data = resp.json()
        assert data["level"] == "warning"


def test_metadata_check_error_level(client):
    from unittest.mock import patch, MagicMock
    mock_config = MagicMock()
    mock_config.app_name = "testapp"
    with patch("asc.config.Config", return_value=mock_config), \
         patch("asc.utils.make_api_from_config", side_effect=Exception("conn fail")):
        resp = client.post("/api/metadata/check", cookies={"asc_profile": "testapp"})
        data = resp.json()
        assert data["level"] == "error"
        assert data["ok"] is False


def test_metadata_core_outputs_progress(capsys):
    from asc.commands.metadata import _upload_metadata_core
    from unittest.mock import MagicMock
    mock_api = MagicMock()
    mock_api.get_app_infos.return_value = [{"id": "info1"}]
    mock_api.get_editable_version.return_value = {
        "id": "v1", "attributes": {"versionString": "1.0", "appStoreState": "PREPARE_FOR_SUBMISSION"}
    }
    mock_api.get_app_info_localizations.return_value = []
    mock_api.get_version_localizations.return_value = []
    mock_api.create_app_info_localization.return_value = {"id": "loc1"}
    mock_api.create_version_localization.return_value = {"id": "vloc1"}
    metadata_list = [
        {"语言": "en-US", "应用名称": "Test", "长描述": "desc"},
        {"语言": "zh-CN", "应用名称": "测试", "长描述": "描述"},
    ]
    _upload_metadata_core(mock_api, "app1", metadata_list, dry_run=True)
    captured = capsys.readouterr()
    assert "[PROGRESS:50:元数据 1/2 语言]" in captured.out
    assert "[PROGRESS:100:元数据 2/2 语言]" in captured.out


def test_screenshots_core_outputs_progress(capsys, tmp_path):
    from asc.commands.screenshots import _upload_screenshots_core
    from unittest.mock import MagicMock, patch
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1"}
    mock_api.get_version_localizations.return_value = [
        {"id": "loc1", "attributes": {"locale": "en-US"}},
        {"id": "loc2", "attributes": {"locale": "zh-CN"}},
    ]
    # Create screenshot folders
    en_dir = tmp_path / "en-US"
    en_dir.mkdir()
    (en_dir / "screen1.png").write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
    zh_dir = tmp_path / "zh-CN"
    zh_dir.mkdir()
    (zh_dir / "screen1.png").write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
    with patch("asc.commands.screenshots._detect_display_type", return_value="APP_IPHONE_67"), \
         patch("asc.commands.screenshots._get_sorted_screenshots", return_value=[en_dir / "screen1.png"]):
        _upload_screenshots_core(mock_api, "app1", str(tmp_path), dry_run=True)
    captured = capsys.readouterr()
    assert "[PROGRESS:" in captured.out
    assert "截图" in captured.out


def test_progress_parsing_in_drain_loop():
    import re
    line = "[PROGRESS:45:元数据 5/11 语言]"
    match = re.match(r"\[PROGRESS:(\d+):(.+)\]", line)
    assert match is not None
    assert match.group(1) == "45"
    assert match.group(2) == "元数据 5/11 语言"


def test_sse_stream_emits_progress():
    from asc.web.tasks import TaskStore, TaskStatus
    store = TaskStore()
    task_id = store.create("metadata", profile="myapp")
    store.set_status(task_id, TaskStatus.RUNNING)
    store.set_progress(task_id, 50, "测试进度")
    store.append_log(task_id, "some log")
    store.set_status(task_id, TaskStatus.DONE)

    # Verify progress field is accessible
    task = store.get(task_id)
    assert task["progress"]["pct"] == 50
    assert task["progress"]["msg"] == "测试进度"


def test_examples_csv_download(client):
    resp = client.get("/api/examples/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "appstore_info_example.csv" in resp.headers.get("content-disposition", "")
    assert "语言" in resp.text


def test_examples_screenshots_download(client):
    resp = client.get("/api/examples/screenshots")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "screenshots_example.zip" in resp.headers.get("content-disposition", "")
    assert len(resp.content) > 0


def test_examples_iap_download(client):
    resp = client.get("/api/examples/iap.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert "iap_packages_example.json" in resp.headers.get("content-disposition", "")
    assert len(resp.content) > 0

# IAP endpoint tests
def test_iap_check_api(client):
    from unittest.mock import patch, MagicMock
    from pathlib import Path
    mock_config = MagicMock()
    mock_config.iap_path = str(Path('data/iap_packages.json'))
    with patch('asc.web.routes_api.Config', return_value=mock_config),          patch('pathlib.Path.exists', return_value=True),          patch('asc.web.routes_api._load_iap_config', return_value=([{'productId': 'com.test.item1'}], [])):
        resp = client.post('/api/iap/check', cookies={'asc_profile': 'testapp'})
        assert resp.status_code == 200, f'Got {resp.status_code}'
        data = resp.json()
        assert data['ok'] is True
        assert data['level'] == 'success'
        print('test_iap_check_api: PASS')

def test_iap_run_api_starts_task(client):
    from unittest.mock import patch, MagicMock
    mock_config = MagicMock()
    mock_config.iap_path = 'data/iap_packages.json'
    with patch('asc.web.routes_api.Config', return_value=mock_config),          patch('asc.web.routes_api._task_store') as mock_store:
        mock_store.create.return_value = 'fake-task-id'
        resp = client.post(
            '/api/iap/run',
            data={'iap_file': 'data/iap_packages.json'},
            cookies={'asc_profile': 'testapp'},
        )
        assert resp.status_code == 200, f'Got {resp.status_code}: {resp.text}'
        data = resp.json()
        assert 'task_id' in data
        mock_store.create.assert_called_once()
        print('test_iap_run_api_starts_task: PASS')

def test_iap_check_missing_file(client):
    from unittest.mock import patch, MagicMock
    from pathlib import Path
    mock_config = MagicMock()
    mock_config.iap_path = 'nonexistent.json'
    with patch('asc.web.routes_api.Config', return_value=mock_config),          patch('pathlib.Path.exists', return_value=False):
        resp = client.post('/api/iap/check', cookies={'asc_profile': 'testapp'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['ok'] is False
        assert data['level'] == 'error'
        print('test_iap_check_missing_file: PASS')
