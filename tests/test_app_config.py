"""Tests for app_config commands (show, edit, and Config.get_app_profile)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from asc.cli import app
from asc.config import Config

runner = CliRunner()


def _write_profile(profiles_dir: Path, name: str) -> None:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / f"{name}.toml").write_text(
        '[credentials]\n'
        'issuer_id = "ISS-1"\n'
        'key_id = "KID-1"\n'
        'key_file = "/keys/AuthKey.p8"\n'
        'app_id = "12345"\n'
        '\n'
        '[defaults]\n'
        'csv = "data/appstore_info.csv"\n'
        'screenshots = "data/screenshots"\n'
    )


def test_get_app_profile_returns_dict(tmp_path):
    profiles_dir = tmp_path / "profiles"
    _write_profile(profiles_dir, "myapp")

    config = Config.__new__(Config)
    config._global_dir = tmp_path
    config._data = {}
    config.app_name = None

    result = config.get_app_profile("myapp")

    assert result == {
        "issuer_id": "ISS-1",
        "key_id": "KID-1",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }


def test_get_app_profile_missing_returns_none(tmp_path):
    config = Config.__new__(Config)
    config._global_dir = tmp_path
    config._data = {}
    config.app_name = None

    result = config.get_app_profile("nonexistent")
    assert result is None


def test_get_app_profile_malformed_toml_returns_none(tmp_path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "bad.toml").write_text("this is not valid toml ][[[")

    config = Config.__new__(Config)
    config._global_dir = tmp_path
    config._data = {}
    config.app_name = None

    result = config.get_app_profile("bad")
    assert result is None


def test_cmd_app_show_prints_all_fields(tmp_path):
    profile_data = {
        "issuer_id": "ISS-1",
        "key_id": "KID-1",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }
    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = profile_data
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "show", "myapp"])

    assert result.exit_code == 0
    assert "myapp" in result.output
    assert "ISS-1" in result.output
    assert "KID-1" in result.output
    assert "/keys/AuthKey.p8" in result.output
    assert "12345" in result.output
    assert "data/appstore_info.csv" in result.output
    assert "data/screenshots" in result.output


def test_cmd_app_show_missing_profile_exits_1():
    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = None
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "show", "ghost"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_cmd_app_edit_missing_profile_exits_1():
    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = None
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "edit", "ghost"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_cmd_app_edit_keeps_existing_values_on_enter(tmp_path):
    """Pressing Enter for all fields keeps original values and calls save_app_profile."""
    profile_data = {
        "issuer_id": "ISS-1",
        "key_id": "KID-1",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }
    # Simulate user pressing Enter for every field (keep defaults)
    user_input = "\n\n\n\n\n\n"  # 6 fields: issuer_id, key_id, key_file, app_id, csv, screenshots

    with patch("asc.commands.app_config.Config") as MockConfig, \
         patch("asc.commands.app_config.shutil") as mock_shutil:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = profile_data
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "edit", "myapp"], input=user_input)

    assert result.exit_code == 0
    mock_cfg.save_app_profile.assert_called_once_with(
        "myapp", "ISS-1", "KID-1", "/keys/AuthKey.p8", "12345",
        "data/appstore_info.csv", "data/screenshots",
    )
    # No file copy when key_file unchanged
    mock_shutil.copy2.assert_not_called()


def test_cmd_app_edit_new_key_file_is_copied(tmp_path):
    """When user provides a new key file path, it is copied to the keys dir."""
    profile_data = {
        "issuer_id": "ISS-1",
        "key_id": "KID-1",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }
    new_key = tmp_path / "NewKey.p8"
    new_key.write_text("fake key content")

    # Enter new key path, keep everything else
    user_input = f"\n\n{new_key}\n\n\n\n"

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = profile_data
        mock_cfg._global_dir = tmp_path
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "edit", "myapp"], input=user_input)

    assert result.exit_code == 0
    expected_dest = tmp_path / "keys" / new_key.name
    mock_cfg.save_app_profile.assert_called_once()
    call_args = mock_cfg.save_app_profile.call_args[0]
    assert call_args[3] == str(expected_dest)
    assert expected_dest.exists()
    assert expected_dest.read_text() == "fake key content"


def test_cmd_app_edit_new_key_file_not_found_exits_1(tmp_path):
    """When user provides a non-existent key file path, exit with code 1."""
    profile_data = {
        "issuer_id": "ISS-1",
        "key_id": "KID-1",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }
    user_input = "\n\n/nonexistent/key.p8\n\n\n\n"

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = profile_data
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "edit", "myapp"], input=user_input)

    assert result.exit_code == 1
