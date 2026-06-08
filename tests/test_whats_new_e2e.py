"""End-to-end integration tests for whats-new translate feature."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from fastapi.testclient import TestClient

from asc.cli import app
from asc.web.server import create_app


@pytest.fixture
def runner():
    return CliRunner()


class TestFullTranslateUploadFlow:
    """Test 1: Full CLI translate + upload flow."""

    def test_full_translate_upload_flow(self, runner):
        """Full CLI flow with mocked LLM and App Store Connect API.

        Verifies that update_version_localization is called exactly 2 times
        (for zh-CN and ja-JP, excluding en-US which is the source locale).
        """
        mock_api = MagicMock()
        mock_api.get_editable_version.return_value = {
            "id": "v1",
            "attributes": {"versionString": "1.0.0"}
        }
        mock_api.get_version_localizations.return_value = [
            {"id": "l1", "attributes": {"locale": "en-US"}},
            {"id": "l2", "attributes": {"locale": "zh-CN"}},
            {"id": "l3", "attributes": {"locale": "ja-JP"}},
        ]
        # update_version_localization returns None, just track calls

        mock_config = MagicMock()
        mock_config.llm_api_key = "test-api-key"
        mock_config.llm_base_url = "https://api.openai.com/v1"
        mock_config.llm_model = "gpt-4o"
        mock_config.app_id = "app123"
        mock_config.app_name = "test"
        mock_config.key_id = "key123"
        mock_config.issuer_id = "issuer123"
        mock_config.key_file = "/path/to/key.p8"

        with patch("asc.commands.whats_new.Config") as MockConfig, \
             patch("asc.commands.whats_new.resolve_app_profile") as mock_resolve, \
             patch("asc.commands.whats_new.Guard") as MockGuard, \
             patch("asc.commands.whats_new.make_api_from_config") as mock_make_api, \
             patch("asc.services.translator.OpenAITranslator") as MockTranslator:

            MockConfig.return_value = mock_config
            mock_resolve.return_value = "test"
            mock_make_api.return_value = (mock_api, "app123")

            # Mock guard disabled
            guard_instance = MockGuard.return_value
            guard_instance.is_enabled.return_value = False

            # Mock translator returns "翻译结果" for all calls
            translator_instance = MockTranslator.return_value
            translator_instance.translate.return_value = "翻译结果"

            result = runner.invoke(
                app,
                ["--app", "test", "whats-new", "--text", "Bug fixes.", "--translate", "--source-locale", "en-US"],
                catch_exceptions=False
            )

            # Verify update_version_localization was called 2 times (zh-CN, ja-JP)
            assert mock_api.update_version_localization.call_count == 2


class TestWebWhatsNewTranslatePreviewFlow:
    """Test 2: Web UI translate preview flow."""

    def test_web_whats_new_translate_preview_flow(self):
        """Web UI translate preview flow: translate -> run -> check status."""
        app_instance = create_app()
        client = TestClient(app_instance)

        mock_api = MagicMock()
        mock_api.get_editable_version.return_value = {
            "id": "v1",
            "attributes": {"versionString": "1.0.0"}
        }
        mock_api.get_version_localizations.return_value = [
            {"id": "l1", "attributes": {"locale": "en-US"}},
            {"id": "l2", "attributes": {"locale": "zh-CN"}},
        ]

        mock_config = MagicMock()
        mock_config.llm_api_key = "test-api-key"
        mock_config.llm_base_url = "https://api.openai.com/v1"
        mock_config.llm_model = "gpt-4o"

        mock_translator = MagicMock()
        mock_translator.translate.side_effect = lambda text, locale, source: f"translated_{locale}"

        with patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
            with patch("asc.web.routes_api.Config", return_value=mock_config):
                with patch("asc.llm.LLMClient", return_value=MagicMock()):
                    with patch("asc.services.translator.OpenAITranslator", return_value=mock_translator):
                        # Step 1: POST /api/whats-new/translate
                        translate_resp = client.post(
                            "/api/whats-new/translate",
                            cookies={"asc_profile": "test"},
                            data={"text": "Bug fixes.", "source_locale": "en-US"},
                        )

        assert translate_resp.status_code == 200
        translate_data = translate_resp.json()
        assert "translations" in translate_data
        assert "source_locale" in translate_data
        assert translate_data["source_locale"] == "en-US"

        # Step 2: POST /api/whats-new/run with translations
        with patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
            with patch("asc.web.routes_api.Config", return_value=mock_config):
                run_resp = client.post(
                    "/api/whats-new/run",
                    cookies={"asc_profile": "test"},
                    data={"translations_json": '{"zh-CN": "你好世界"}', "dry_run": "1"},
                )

        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert "task_id" in run_data
        task_id = run_data["task_id"]

        # Step 3: GET /api/task/{task_id}/status
        status_resp = client.get(f"/api/task/{task_id}/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert "status" in status_data


class TestWhatsNewPageLoads:
    """Test 3: Simple page load test."""

    def test_whats_new_page_loads(self):
        """GET /whats-new returns 200 with '更新说明' or 'What's New' in response."""
        app_instance = create_app()
        client = TestClient(app_instance)

        response = client.get("/whats-new")

        assert response.status_code == 200
        assert "更新说明" in response.text or "What's New" in response.text
