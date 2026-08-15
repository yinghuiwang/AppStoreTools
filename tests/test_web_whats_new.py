# tests/test_web_whats_new.py
"""Unit tests for /api/whats-new/* and /api/settings/llm routes."""
from __future__ import annotations

import sys
import types
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from asc.web.server import create_app


@pytest.fixture(autouse=True)
def isolated_web_task_guard(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr(
        "asc.web.routes_api.enforce_config_guard",
        MagicMock(),
    )


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_whats_new_check_returns_locales(client):
    """GET /api/whats-new/check with valid editable version returns ok=True, version string, and locales list."""
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {"versionString": "2.0.0"}}
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "en-US"}},
        {"id": "l2", "attributes": {"locale": "zh-CN"}},
    ]
    mock_config = MagicMock()
    mock_config.llm_api_key = None
    mock_config.llm_base_url = "https://api.openai.com/v1"
    mock_config.llm_model = "gpt-4o"

    with patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        with patch("asc.config.Config", return_value=mock_config):
            response = client.get("/api/whats-new/check", cookies={"asc_profile": "test"})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["level"] == "success"
    assert data["detail"]["version"] == "2.0.0"
    assert data["detail"]["locales"] == ["en-US", "zh-CN"]


def test_whats_new_check_no_editable_version(client):
    """GET /api/whats-new/check when no editable version returns ok=False with error message."""
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = None
    mock_config = MagicMock()
    mock_config.llm_api_key = None
    mock_config.llm_base_url = "https://api.openai.com/v1"
    mock_config.llm_model = "gpt-4o"

    with patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        with patch("asc.config.Config", return_value=mock_config):
            response = client.get("/api/whats-new/check", cookies={"asc_profile": "test"})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["level"] == "warning"
    assert "message" in data


def test_whats_new_translate_returns_task_id(client):
    """POST /api/whats-new/translate returns {task_id}; translations live on task result."""
    import time
    from asc.web.tasks import TaskStatus
    from asc.web import routes_api

    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "2.0.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
    }
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "en-US"}},
        {"id": "l2", "attributes": {"locale": "zh-CN"}},
    ]
    mock_config = MagicMock()
    mock_config.llm_api_key = "fake-api-key"
    mock_config.llm_base_url = "https://api.openai.com/v1"
    mock_config.llm_model = "gpt-4o"

    mock_translator = MagicMock()
    mock_translator.translate.side_effect = lambda text, locale, source: f"translated_{locale}"

    with patch("asc.web.routes_api.Config", return_value=mock_config), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")), \
         patch("asc.llm.LLMClient", return_value=MagicMock()), \
         patch("asc.services.translator.OpenAITranslator", return_value=mock_translator):
        response = client.post(
            "/api/whats-new/translate",
            cookies={"asc_profile": "test"},
            json={"text": "Hello world", "source_locale": "en-US"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert "translations" not in data

        task_id = data["task_id"]
        task = None
        for _ in range(100):
            task = routes_api._task_store.get(task_id)
            if task and task["status"] in {TaskStatus.DONE, TaskStatus.ERROR, TaskStatus.CANCELED}:
                break
            time.sleep(0.02)

    assert task is not None
    assert task["status"] == TaskStatus.DONE
    assert "en-US" not in task["result"]["translations"]
    assert task["result"]["translations"]["zh-CN"] == "translated_zh-CN"


def test_whats_new_translate_no_api_key_returns_400(client):
    """POST /api/whats-new/translate when no LLM API key returns 400 with error about api_key."""
    mock_config = MagicMock()
    mock_config.llm_api_key = None
    mock_config.llm_base_url = "https://api.openai.com/v1"
    mock_config.llm_model = "gpt-4o"

    with patch("asc.web.routes_api.Config", return_value=mock_config):
        response = client.post(
            "/api/whats-new/translate",
            cookies={"asc_profile": "test"},
            json={"text": "Hello world", "source_locale": "en-US"},
        )

    assert response.status_code == 400
    data = response.json()
    assert "api_key" in data.get("error", "").lower() or "api key" in data.get("error", "").lower()


def test_whats_new_run_returns_task_id(client):
    """POST /api/whats-new/run with valid JSON returns a task_id."""
    mock_api = MagicMock()
    mock_config = MagicMock()
    mock_config.llm_api_key = None

    with patch("asc.config.Config", return_value=mock_config):
        with patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
            response = client.post(
                "/api/whats-new/run",
                cookies={"asc_profile": "test"},
                data={"translations_json": '{"zh-CN": "你好世界"}', "dry_run": ""},
            )

    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data


def test_whats_new_run_invalid_json_returns_400(client):
    """POST /api/whats-new/run with malformed JSON returns 400."""
    mock_config = MagicMock()
    mock_config.llm_api_key = None

    with patch("asc.config.Config", return_value=mock_config):
        response = client.post(
            "/api/whats-new/run",
            cookies={"asc_profile": "test"},
            data={"translations_json": "not valid json {", "dry_run": ""},
        )

    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_whats_new_run_accepts_json_translations_payload(client):
    """POST /api/whats-new/run accepts JSON payload from the Web UI translation preview."""
    with patch("asc.web.routes_api._start_whats_new_task", return_value="task-123") as mock_start:
        response = client.post(
            "/api/whats-new/run",
            cookies={"asc_profile": "test"},
            json={
                "translations": {"zh-CN": "你好世界"},
                "text": "Hello world",
                "dry_run": 0,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "task-123"
    mock_start.assert_called_once()
    kwargs = mock_start.call_args.kwargs
    assert kwargs["dry_run"] is False
    assert kwargs["translations"] == {"zh-CN": "你好世界"}
    assert kwargs["text"] == "Hello world"


def test_whats_new_run_accepts_json_direct_payload(client):
    """POST /api/whats-new/run accepts JSON payload from the Web UI direct upload button."""
    with patch("asc.web.routes_api._start_whats_new_task", return_value="task-456") as mock_start:
        response = client.post(
            "/api/whats-new/run",
            cookies={"asc_profile": "test"},
            json={
                "text": "Bug fixes.",
                "source_locale": "en-US",
                "locales": "en-US,zh-CN",
                "dry_run": 1,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["task_id"] == "task-456"
    mock_start.assert_called_once()
    kwargs = mock_start.call_args.kwargs
    assert kwargs["dry_run"] is True
    assert kwargs["translations"] is None
    assert kwargs["text"] == "Bug fixes."
    assert kwargs["locales"] == ["en-US", "zh-CN"]


def test_whats_new_run_translates_inside_worker_not_request_thread(client):
    """POST /api/whats-new/run with translate=true defers LLM to the background worker."""
    mock_translator = MagicMock()
    mock_translator.translate.side_effect = lambda text, locale, source: f"translated_{locale}"

    with patch("asc.web.routes_api._start_whats_new_task", return_value="task-789") as mock_start:
        with patch("asc.services.translator.OpenAITranslator", return_value=mock_translator):
            response = client.post(
                "/api/whats-new/run",
                cookies={"asc_profile": "test"},
                json={
                    "text": "Bug fixes.",
                    "source_locale": "en-US",
                    "translate": True,
                    "dry_run": 0,
                },
            )

    assert response.status_code == 200
    assert response.json()["task_id"] == "task-789"
    mock_translator.translate.assert_not_called()
    kwargs = mock_start.call_args.kwargs
    assert kwargs["translate"] is True
    assert kwargs["text"] == "Bug fixes."
    assert kwargs["source_locale"] == "en-US"
    assert kwargs["translations"] is None
    assert kwargs["locales"] is None


def test_whats_new_run_worker_translate_uses_60_40_phases(monkeypatch):
    """translate=true run: worker LLM + phases translate 60% / upload 40%."""
    import time
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore()
    monkeypatch.setattr(routes_api, "_task_store", store)

    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "2.0.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
    }
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "en-US"}},
        {"id": "l2", "attributes": {"locale": "zh-CN"}},
        {"id": "l3", "attributes": {"locale": "ja-JP"}},
    ]
    mock_config = MagicMock()
    mock_config.llm_api_key = "fake-api-key"
    mock_config.llm_base_url = "https://api.openai.com/v1"
    mock_config.llm_model = "gpt-4o"

    mock_translator = MagicMock()
    mock_translator.translate.side_effect = lambda text, locale, source: f"translated_{locale}"

    with patch("asc.web.routes_api.Config", return_value=mock_config), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")), \
         patch("asc.llm.LLMClient", return_value=MagicMock()), \
         patch("asc.services.translator.OpenAITranslator", return_value=mock_translator):
        task_id = routes_api._start_whats_new_task(
            profile="test",
            dry_run=False,
            text="Bug fixes.",
            translate=True,
            source_locale="en-US",
        )
        task = None
        for _ in range(100):
            task = store.get(task_id)
            if task and task["status"] in {TaskStatus.DONE, TaskStatus.ERROR, TaskStatus.CANCELED}:
                break
            time.sleep(0.02)

    assert task is not None
    assert task["status"] == TaskStatus.DONE
    mock_translator.translate.assert_called()
    assert mock_api.update_version_localization.call_count == 2
    assert task["result"]["translations"]["zh-CN"] == "translated_zh-CN"
    assert task["result"]["translations"]["ja-JP"] == "translated_ja-JP"
    assert task["progress"]["pct"] == 100
    # Logs should mention both phases via reporter
    joined = "\n".join(task["logs"])
    assert "翻译" in joined or "翻译模式" in joined
    assert "已上传" in joined


def test_whats_new_web_starter_uses_start_background_task():
    import inspect
    from asc.web import routes_api

    starter = inspect.getsource(routes_api._start_whats_new_task)
    assert "start_background_task" in starter
    assert "_PROGRESS_RE" not in starter

    translate_starter = inspect.getsource(routes_api._start_whats_new_translate_task)
    assert "start_background_task" in translate_starter


def test_settings_llm_get_redacts_api_key(client):
    """GET /api/settings/llm exposes config metadata, never the secret."""
    mock_config = MagicMock()
    mock_config.llm_configs = {
        "openai": {"base_url": "https://api.openai.com/v1", "api_key": "secret-key-123", "model": "gpt-4o-mini"}
    }
    mock_config.llm_default = "openai"

    with patch("asc.config.Config", return_value=mock_config):
        response = client.get("/api/settings/llm", cookies={"asc_profile": "test"})

    assert response.status_code == 200
    data = response.json()
    assert data["configs"]["openai"]["base_url"] == "https://api.openai.com/v1"
    assert "api_key" not in data["configs"]["openai"]
    assert data["configs"]["openai"]["has_api_key"] is True
    assert data["configs"]["openai"]["model"] == "gpt-4o-mini"
    assert data["default"] == "openai"


def test_settings_llm_post_saves_config(client):
    """POST /api/settings/llm with JSON body returns ok=True."""
    mock_config = MagicMock()

    with patch("asc.config.Config", return_value=mock_config):
        response = client.post(
            "/api/settings/llm",
            cookies={"asc_profile": "test"},
            json={"name": "openai", "base_url": "https://api.new.com/v1", "model": "gpt-4o", "api_key": "new-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    mock_config.save_llm_config.assert_called_once_with(
        "openai", "https://api.new.com/v1", "new-key", "gpt-4o",
        set_default=True, preserve_blank_api_key=True,
    )
