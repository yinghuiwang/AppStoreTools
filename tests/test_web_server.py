# tests/test_web_server.py
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
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


def test_profiles_page_returns_200(client):
    resp = client.get("/profiles")
    assert resp.status_code == 200


def test_settings_page_returns_200(client):
    resp = client.get("/settings")
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


def test_task_stream_not_found(client):
    resp = client.get("/api/task/nonexistent/stream")
    assert resp.status_code == 404


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
        "bindings": {"machine": {}, "ip": {}, "credential": {}},
    }
    with patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.get("/api/guard/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert "bindings" in data
    assert "current_profile" in data


def test_guard_status_truncates_fingerprint(client):
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
    assert machine_keys[0] == "a1b2c3d4..."


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
