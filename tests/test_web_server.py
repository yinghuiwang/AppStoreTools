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
        mock_check.return_value = {"ok": True, "message": "环境正常"}
        resp = client.post("/api/metadata/check", data={"profile": "myapp"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

def test_metadata_run_api_starts_task(client):
    """POST /api/metadata/run 创建任务并返回 task_id"""
    from unittest.mock import patch
    with patch("asc.web.routes_api._start_metadata_task") as mock_start:
        mock_start.return_value = "fake-task-id"
        resp = client.post("/api/metadata/run", data={
            "profile": "myapp",
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
        resp = client.post("/api/build/run", data={
            "profile": "myapp",
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
    mock_guard.is_enabled.return_value = True
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


def test_task_store_create_with_profile_and_progress():
    from asc.web.tasks import TaskStore
    store = TaskStore()
    task_id = store.create("metadata", profile="myapp")
    task = store.get(task_id)
    assert task["kind"] == "metadata"
    assert task["profile"] == "myapp"
    assert task["progress"] == {"pct": 0, "msg": ""}


def test_task_store_set_progress():
    from asc.web.tasks import TaskStore
    store = TaskStore()
    task_id = store.create("build", profile="staging")
    store.set_progress(task_id, 45, "元数据 5/11 语言")
    task = store.get(task_id)
    assert task["progress"] == {"pct": 45, "msg": "元数据 5/11 语言"}
