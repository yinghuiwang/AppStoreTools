"""Tests for app_config commands (show, edit, and Config.get_app_profile)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from asc.cli import app
from asc.config import Config
from asc.guard import GuardViolationError

runner = CliRunner()


@pytest.fixture(autouse=True)
def profile_guard():
    with patch("asc.guard.Guard") as guard_cls:
        guard_cls.return_value.is_enabled.return_value = False
        yield guard_cls.return_value


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


def test_get_app_profile_missing_data_paths_are_empty(tmp_path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "myapp.toml").write_text(
        '[credentials]\n'
        'issuer_id = "ISS-1"\n'
        'key_id = "KID-1"\n'
        'key_file = "/keys/AuthKey.p8"\n'
        'app_id = "12345"\n'
    )

    config = Config.__new__(Config)
    config._global_dir = tmp_path
    config._data = {}
    config.app_name = None

    result = config.get_app_profile("myapp")
    assert result["csv"] == ""
    assert result["screenshots"] == ""


def test_save_app_profile_omits_blank_data_paths(tmp_path):
    config = Config.__new__(Config)
    config._global_dir = tmp_path
    config._data = {}
    config.app_name = None

    config.save_app_profile("myapp", "ISS-1", "KID-1", "/keys/AuthKey.p8", "12345")

    text = (tmp_path / "profiles" / "myapp.toml").read_text()
    assert "csv" not in text
    assert "screenshots" not in text
    assert "[defaults]" not in text


def test_save_app_profile_writes_provided_data_paths(tmp_path):
    config = Config.__new__(Config)
    config._global_dir = tmp_path
    config._data = {}
    config.app_name = None

    config.save_app_profile(
        "myapp", "ISS-1", "KID-1", "/keys/AuthKey.p8", "12345",
        "custom.csv", "custom/shots",
    )

    text = (tmp_path / "profiles" / "myapp.toml").read_text()
    assert 'csv = "custom.csv"' in text
    assert 'screenshots = "custom/shots"' in text


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
    user_input = "\n\n\n\n\n\n\n"  # 7 fields: name, issuer_id, key_id, key_file, app_id, csv, screenshots

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
    user_input = f"\n\n\n{new_key}\n\n\n\n"

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


def test_cmd_app_edit_new_key_file_not_found_reprompts(tmp_path):
    """When user provides a non-existent key file path, re-prompt until valid input is given."""
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

    # First enter invalid path, then valid key path, then rest of defaults
    user_input = f"\n\n\n/nonexistent/key.p8\n{new_key}\n\n\n\n"

    with patch("asc.commands.app_config.Config") as MockConfig:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.return_value = profile_data
        mock_cfg._global_dir = tmp_path
        MockConfig.return_value = mock_cfg

        with patch("asc.i18n.LANG", "zh"):
            result = runner.invoke(app, ["app", "edit", "myapp"], input=user_input)

    assert result.exit_code == 0
    # Verify re-prompt error message appeared
    assert "文件不存在" in result.output


def test_cmd_app_edit_can_rename_profile(tmp_path, monkeypatch):
    profile_data = {
        "issuer_id": "ISS-1",
        "key_id": "KID-1",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }
    local_dir = tmp_path / ".asc"
    local_dir.mkdir()
    (local_dir / "config.toml").write_text('[defaults]\ndefault_app = "myapp"\n')
    monkeypatch.chdir(tmp_path)

    def get_profile(profile_name):
        if profile_name == "myapp":
            return profile_data
        return None

    user_input = "newapp\n\n\n\n\n\n\n"
    with patch("asc.commands.app_config.Config") as MockConfig, \
         patch("asc.commands.app_config.shutil") as mock_shutil:
        mock_cfg = MagicMock()
        mock_cfg.get_app_profile.side_effect = get_profile
        MockConfig.return_value = mock_cfg

        result = runner.invoke(app, ["app", "edit", "myapp"], input=user_input)

    assert result.exit_code == 0
    mock_cfg.save_app_profile.assert_called_once_with(
        "newapp", "ISS-1", "KID-1", "/keys/AuthKey.p8", "12345",
        "data/appstore_info.csv", "data/screenshots",
    )
    mock_cfg.remove_app_profile.assert_called_once_with("myapp")
    mock_shutil.copy2.assert_not_called()
    assert 'default_app = "newapp"' in (local_dir / "config.toml").read_text()


def test_cmd_app_add_does_not_prompt_for_data_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    key_file = tmp_path / "AuthKey.p8"
    key_file.write_text("key")
    user_input = f"ISS-1\nKID-1\n{key_file}\n12345\n"

    with patch("asc.commands.app_config.Config") as config_cls:
        mock_cfg = MagicMock()
        config_cls.return_value = mock_cfg
        result = runner.invoke(app, ["app", "add", "newapp"], input=user_input)

    assert result.exit_code == 0, result.output
    assert "CSV" not in result.output
    assert "Screenshots" not in result.output
    mock_cfg.save_app_profile.assert_called_once()
    args = mock_cfg.save_app_profile.call_args[0]
    assert args[0] == "newapp"
    assert args[1] == "ISS-1"
    assert args[2] == "KID-1"
    assert args[4] == "12345"
    assert len(args) == 5


def test_cmd_app_add_guard_violation_stops_before_copy_or_save(
    tmp_path, profile_guard
):
    key_file = tmp_path / "AuthKey_TEST.p8"
    key_file.write_text("key")
    profile_guard.is_enabled.return_value = True
    profile_guard.check_and_enforce.side_effect = GuardViolationError("绑定冲突")
    user_input = f"ISS-NEW\nKEY-NEW\n{key_file}\n12345\n"

    with patch("asc.commands.app_config.Config") as config_cls, \
         patch("asc.commands.app_config.shutil.copy2") as copy_key:
        result = runner.invoke(app, ["app", "add", "newapp"], input=user_input)

    assert result.exit_code == 1
    assert "绑定冲突" in result.output
    profile_guard.check_and_enforce.assert_called_once_with(
        app_id="12345",
        app_name="newapp",
        key_id="KEY-NEW",
        issuer_id="ISS-NEW",
    )
    copy_key.assert_not_called()
    config_cls.return_value.save_app_profile.assert_not_called()


def test_cmd_app_edit_guard_violation_stops_before_save(profile_guard):
    profile_data = {
        "issuer_id": "ISS-OLD",
        "key_id": "KEY-OLD",
        "key_file": "/keys/AuthKey.p8",
        "app_id": "12345",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }
    profile_guard.is_enabled.return_value = True
    profile_guard.check_and_enforce.side_effect = GuardViolationError("绑定冲突")

    with patch("asc.commands.app_config.Config") as config_cls:
        config_cls.return_value.get_app_profile.return_value = profile_data
        result = runner.invoke(
            app,
            ["app", "edit", "myapp"],
            input="\nISS-NEW\nKEY-NEW\n\n67890\n\n\n",
        )

    assert result.exit_code == 1
    assert "绑定冲突" in result.output
    profile_guard.check_and_enforce.assert_called_once_with(
        app_id="67890",
        app_name="myapp",
        key_id="KEY-NEW",
        issuer_id="ISS-NEW",
    )
    config_cls.return_value.save_app_profile.assert_not_called()
