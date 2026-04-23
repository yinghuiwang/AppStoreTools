"""Tests for cmd_install."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from asc.cli import app

runner = CliRunner()


def test_install_already_configured(tmp_path, monkeypatch):
    """When .asc/config.toml exists with default_app, print ready message and exit 0."""
    monkeypatch.chdir(tmp_path)
    asc_dir = tmp_path / ".asc"
    asc_dir.mkdir()
    (asc_dir / "config.toml").write_text('[defaults]\ndefault_app = "myapp"\n')

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.list_apps.return_value = ["myapp"]
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["install"])

    assert result.exit_code == 0
    assert "已就绪" in result.output


def test_install_no_profiles_user_skips(tmp_path, monkeypatch):
    """When no profiles exist and user says no, print next steps and exit 0."""
    monkeypatch.chdir(tmp_path)

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.list_apps.return_value = []
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["install"], input="n\n")

    assert result.exit_code == 0
    assert "asc app add" in result.output


def test_install_has_profiles_user_sets_default(tmp_path, monkeypatch):
    """When profiles exist and user sets one as default, cheatsheet is printed."""
    monkeypatch.chdir(tmp_path)

    with patch("asc.commands.app_config.Config") as MockConfig, \
         patch("asc.commands.app_config.cmd_app_default") as mock_default:
        mock_cfg = MagicMock()
        mock_cfg.list_apps.return_value = ["myapp"]
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["install"], input="y\n")

    assert result.exit_code == 0
    mock_default.assert_called_once_with("myapp")
    assert "asc upload" in result.output


def test_install_has_profiles_user_declines_default(tmp_path, monkeypatch):
    """When profiles exist but user declines setting default, show hint and cheatsheet."""
    monkeypatch.chdir(tmp_path)

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.list_apps.return_value = ["myapp"]
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["install"], input="n\n")

    assert result.exit_code == 0
    assert "asc app default" in result.output
    assert "asc upload" in result.output
    # Should NOT print misleading "尚未配置" message
    assert "尚未配置" not in result.output


def test_install_has_profiles_invalid_name_shows_cheatsheet(tmp_path, monkeypatch):
    """When user enters invalid profile name, show cheatsheet and return."""
    monkeypatch.chdir(tmp_path)

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.list_apps.return_value = ["myapp", "otherapp"]
        MockConfig.return_value = mock_cfg

        # User says yes to set default, but enters invalid name
        result = runner.invoke(app, ["install"], input="y\nbadname\n")

    assert result.exit_code == 0
    assert "不在列表中" in result.output
    assert "asc upload" in result.output
    assert "尚未配置" not in result.output
