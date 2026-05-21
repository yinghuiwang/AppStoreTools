"""Tests for --translate CLI behavior in whats_new command."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from asc.cli import app


@pytest.fixture
def mock_config():
    """Create a mock Config object with LLM settings."""
    config = MagicMock()
    config.llm_api_key = "test-api-key"
    config.llm_base_url = "https://api.openai.com/v1"
    config.llm_model = "gpt-4o"
    config.app_id = "app123"
    config.app_name = "test"
    config.key_id = "key123"
    config.issuer_id = "issuer123"
    config.key_file = "/path/to/key.p8"
    return config


@pytest.fixture
def mock_api():
    """Create a mock API object."""
    api = MagicMock()
    api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.0"}
    }
    api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "en-US"}},
        {"id": "l2", "attributes": {"locale": "zh-CN"}},
        {"id": "l3", "attributes": {"locale": "ja-JP"}},
    ]
    return api


@pytest.fixture
def runner():
    return CliRunner()


class TestTranslateFlagRequiresText:
    """Test that --translate without --text exits with error."""

    def test_translate_flag_requires_text(self, runner, mock_config, mock_api):
        """--translate without --text exits with error message containing 'text'."""
        with patch("asc.commands.whats_new.Config") as MockConfig, \
             patch("asc.commands.whats_new.resolve_app_profile") as mock_resolve, \
             patch("asc.commands.whats_new.Guard") as MockGuard, \
             patch("asc.commands.whats_new.make_api_from_config") as mock_make_api:

            MockConfig.return_value = mock_config
            mock_resolve.return_value = "test"
            mock_make_api.return_value = (mock_api, "app123")

            # Mock guard disabled
            guard_instance = MockGuard.return_value
            guard_instance.is_enabled.return_value = False

            result = runner.invoke(
                app,
                ["--app", "test", "whats-new", "--translate"],
                catch_exceptions=False
            )

            assert result.exit_code != 0
            assert "text" in result.output.lower()


class TestTranslateExitsIfNoLLMApiKey:
    """Test that --translate exits if no LLM API key is configured."""

    def test_translate_exits_if_no_llm_api_key(self, runner, mock_api):
        """--translate with no LLM API key configured exits with error about 'api_key' or 'configured'."""
        # Create config without LLM API key
        config_no_key = MagicMock()
        config_no_key.llm_api_key = None  # No API key
        config_no_key.llm_base_url = "https://api.openai.com/v1"
        config_no_key.llm_model = "gpt-4o"
        config_no_key.app_id = "app123"
        config_no_key.app_name = "test"
        config_no_key.key_id = "key123"
        config_no_key.issuer_id = "issuer123"
        config_no_key.key_file = "/path/to/key.p8"

        with patch("asc.commands.whats_new.Config") as MockConfig, \
             patch("asc.commands.whats_new.resolve_app_profile") as mock_resolve, \
             patch("asc.commands.whats_new.Guard") as MockGuard, \
             patch("asc.commands.whats_new.make_api_from_config") as mock_make_api:

            MockConfig.return_value = config_no_key
            mock_resolve.return_value = "test"
            mock_make_api.return_value = (mock_api, "app123")

            # Mock guard disabled
            guard_instance = MockGuard.return_value
            guard_instance.is_enabled.return_value = False

            result = runner.invoke(
                app,
                ["--app", "test", "whats-new", "--translate", "--text", "Bug fixes."],
                catch_exceptions=False
            )

            assert result.exit_code != 0
            assert "api_key" in result.output.lower() or "configured" in result.output.lower()


class TestTranslateCallsTranslatorForEachLocale:
    """Test that translator is called for each non-source locale."""

    def test_translate_calls_translator_for_each_locale(self, runner, mock_config, mock_api):
        """--translate calls translator.translate() for each non-source locale (>= 2 for 3 locales)."""
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

            # Mock translator instance and translate method
            translator_instance = MockTranslator.return_value
            translator_instance.translate.return_value = "Translated text"

            result = runner.invoke(
                app,
                ["--app", "test", "whats-new", "--translate", "--text", "Bug fixes.", "--source-locale", "en-US"],
                catch_exceptions=False
            )

            # Should be called at least 2 times (for zh-CN and ja-JP, excluding en-US as source)
            assert translator_instance.translate.call_count >= 2


class TestDryRunDoesNotUpload:
    """Test that --translate --dry-run does NOT upload."""

    def test_dry_run_does_not_upload(self, runner, mock_config, mock_api):
        """--translate --dry-run does NOT call api.update_version_localization()."""
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

            # Mock translator instance and translate method
            translator_instance = MockTranslator.return_value
            translator_instance.translate.return_value = "Translated text"

            result = runner.invoke(
                app,
                ["--app", "test", "whats-new", "--translate", "--text", "Bug fixes.", "--dry-run"],
                catch_exceptions=False
            )

            # update_version_localization should NOT be called in dry-run mode
            mock_api.update_version_localization.assert_not_called()


class TestTranslateNonDryRunCallsApi:
    """Test that --translate without --dry-run DOES call API."""

    def test_translate_non_dry_run_calls_api(self, runner, mock_config, mock_api):
        """--translate without --dry-run DOES call api.update_version_localization() once per locale."""
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

            # Mock translator instance and translate method
            translator_instance = MockTranslator.return_value
            translator_instance.translate.return_value = "Translated text"

            result = runner.invoke(
                app,
                ["--app", "test", "whats-new", "--translate", "--text", "Bug fixes.", "--source-locale", "en-US"],
                catch_exceptions=False
            )

            # update_version_localization should be called once per locale (2 times for zh-CN and ja-JP)
            assert mock_api.update_version_localization.call_count == 2


class TestTranslateSkipsFailedLocale:
    """Test that when one locale fails to translate, others still work."""

    def test_translate_skips_failed_locale_and_continues(self, runner, mock_config, mock_api):
        """When one locale fails to translate, it's skipped and other locale's translation is uploaded."""
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

            # Mock translator that fails for zh-CN but succeeds for ja-JP
            translator_instance = MockTranslator.return_value

            def translate_side_effect(text, target_locale, source_locale):
                if target_locale == "zh-CN":
                    raise Exception("Translation failed for zh-CN")
                return f"Translated: {target_locale}"

            translator_instance.translate.side_effect = translate_side_effect

            result = runner.invoke(
                app,
                ["--app", "test", "whats-new", "--translate", "--text", "Bug fixes.", "--source-locale", "en-US"],
                catch_exceptions=False
            )

            # ja-JP translation should be uploaded (call count should be 1 for the successful locale)
            assert mock_api.update_version_localization.call_count == 1
            # The successful upload should be for ja-JP
            call_args = mock_api.update_version_localization.call_args
            # The locale id should be "l3" (ja-JP) since zh-CN failed
            assert call_args[0][0] == "l3"  # First arg is loc_id