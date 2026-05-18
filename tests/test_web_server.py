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
