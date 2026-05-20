# tests/test_web_whats_new.py
"""Unit tests for /api/whats-new/* and /api/settings/llm routes."""
from __future__ import annotations

import sys
import types
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from asc.web.server import create_app


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


def test_whats_new_translate_returns_translations(client):
    """POST /api/whats-new/translate with text+source_locale returns translations dict (excluding source locale from results)."""
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {"versionString": "2.0.0"}}
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

    with patch("asc.config.Config", return_value=mock_config):
        with patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
            with patch("asc.llm.LLMClient", return_value=MagicMock()):
                with patch("asc.services.translator.OpenAITranslator", return_value=mock_translator):
                    response = client.post(
                        "/api/whats-new/translate",
                        cookies={"asc_profile": "test"},
                        json={"text": "Hello world", "source_locale": "en-US"},
                    )

    assert response.status_code == 200
    data = response.json()
    assert "translations" in data
    # en-US should be excluded since it's the source locale
    assert "en-US" not in data["translations"]
    assert "zh-CN" in data["translations"]
    assert data["translations"]["zh-CN"] == "translated_zh-CN"


def test_whats_new_translate_no_api_key_returns_400(client):
    """POST /api/whats-new/translate when no LLM API key returns 400 with error about api_key."""
    mock_config = MagicMock()
    mock_config.llm_api_key = None
    mock_config.llm_base_url = "https://api.openai.com/v1"
    mock_config.llm_model = "gpt-4o"

    with patch("asc.config.Config", return_value=mock_config):
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


def test_settings_llm_get_returns_config(client):
    """GET /api/settings/llm returns configs dict and default name."""
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
    assert data["configs"]["openai"]["api_key"] == "secret-key-123"
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
    mock_config.save_llm_config.assert_called_once_with("openai", "https://api.new.com/v1", "new-key", "gpt-4o", set_default=True)
