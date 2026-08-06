# tests/test_web_listing.py
"""Unit tests for metadata upload locale/field filtering via /api/metadata/run."""
from __future__ import annotations

import json
import time

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from asc.web.server import create_app
from asc.web.tasks import TaskStatus


@pytest.fixture(autouse=True)
def isolated_web_task_guard(monkeypatch):
    monkeypatch.setattr(
        "asc.web.routes_api.enforce_config_guard",
        MagicMock(),
    )


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def _wait_for_task(routes_api, task_id, timeout_iters=100):
    task = None
    for _ in range(timeout_iters):
        task = routes_api._task_store.get(task_id)
        if task and task["status"] in {TaskStatus.DONE, TaskStatus.ERROR, TaskStatus.CANCELED}:
            break
        time.sleep(0.02)
    return task


def test_metadata_run_filters_by_locale_and_fields(client, tmp_path):
    """POST /api/metadata/run with locales_json/fields_by_locale_json filters rows before upload."""
    from asc.web import routes_api

    csv_path = tmp_path / "appstore_info.csv"
    csv_path.write_text(
        "locale,name,keywords,description\n"
        "en-US,A,k,d\n"
        "zh-Hans,中,词,描述\n",
        encoding="utf-8",
    )

    mock_config = MagicMock()
    mock_api = MagicMock()

    captured = {}

    def fake_upload_metadata_core(api, app_id, metadata_list, **kwargs):
        captured["metadata_list"] = metadata_list
        return {"success": True}

    with patch("asc.web.routes_api.Config", return_value=mock_config), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")), \
         patch("asc.commands.metadata._upload_metadata_core", side_effect=fake_upload_metadata_core):
        response = client.post(
            "/api/metadata/run",
            cookies={"asc_profile": "test"},
            data={
                "csv_path": str(csv_path),
                "include_metadata": "1",
                "include_screenshots": "",
                "dry_run": "1",
                "locales_json": json.dumps(["en-US"]),
                "fields_by_locale_json": json.dumps({"en-US": ["name", "keywords"]}),
            },
        )
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        task = _wait_for_task(routes_api, task_id)

    assert task is not None
    assert task["status"] == TaskStatus.DONE
    assert captured["metadata_list"] == [{"locale": "en-US", "name": "A", "keywords": "k"}]


def test_metadata_run_empty_filters_uploads_all_rows(client, tmp_path):
    """Empty locales_json/fields_by_locale_json means no filtering (all rows uploaded as-is)."""
    from asc.web import routes_api

    csv_path = tmp_path / "appstore_info.csv"
    csv_path.write_text(
        "locale,name,keywords\n"
        "en-US,A,k\n"
        "zh-Hans,中,词\n",
        encoding="utf-8",
    )

    mock_config = MagicMock()
    mock_api = MagicMock()

    captured = {}

    def fake_upload_metadata_core(api, app_id, metadata_list, **kwargs):
        captured["metadata_list"] = metadata_list
        return {"success": True}

    with patch("asc.web.routes_api.Config", return_value=mock_config), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")), \
         patch("asc.commands.metadata._upload_metadata_core", side_effect=fake_upload_metadata_core):
        response = client.post(
            "/api/metadata/run",
            cookies={"asc_profile": "test"},
            data={
                "csv_path": str(csv_path),
                "include_metadata": "1",
                "include_screenshots": "",
                "dry_run": "1",
                "locales_json": "",
                "fields_by_locale_json": "",
            },
        )
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        task = _wait_for_task(routes_api, task_id)

    assert task is not None
    assert task["status"] == TaskStatus.DONE
    assert captured["metadata_list"] == [
        {"locale": "en-US", "name": "A", "keywords": "k"},
        {"locale": "zh-Hans", "name": "中", "keywords": "词"},
    ]


def test_metadata_run_filter_yields_empty_returns_400(client, tmp_path):
    """When include_metadata is set, screenshots are not included, and filtering yields
    zero rows, the endpoint returns HTTP 400 before starting a task."""
    csv_path = tmp_path / "appstore_info.csv"
    csv_path.write_text(
        "locale,name\n"
        "en-US,A\n",
        encoding="utf-8",
    )

    mock_config = MagicMock()

    with patch("asc.web.routes_api.Config", return_value=mock_config):
        response = client.post(
            "/api/metadata/run",
            cookies={"asc_profile": "test"},
            data={
                "csv_path": str(csv_path),
                "include_metadata": "1",
                "include_screenshots": "",
                "dry_run": "1",
                "locales_json": json.dumps(["ja"]),
                "fields_by_locale_json": "",
            },
        )

    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_metadata_run_invalid_locales_json_returns_400(client):
    """Malformed locales_json returns 400."""
    response = client.post(
        "/api/metadata/run",
        cookies={"asc_profile": "test"},
        data={
            "include_metadata": "1",
            "locales_json": "not valid json {",
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_metadata_run_invalid_fields_by_locale_json_returns_400(client):
    """Malformed fields_by_locale_json returns 400."""
    response = client.post(
        "/api/metadata/run",
        cookies={"asc_profile": "test"},
        data={
            "include_metadata": "1",
            "fields_by_locale_json": "not valid json {",
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data
