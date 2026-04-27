# tests/test_app_import.py
"""Tests for asc app import command"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from asc.cli import app


@pytest.fixture()
def project_root(tmp_path):
    """Create a minimal project with AppStore/Config/.env"""
    config_dir = tmp_path / "AppStore" / "Config"
    config_dir.mkdir(parents=True)
    data_dir = tmp_path / "AppStore" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "screenshots").mkdir()
    (data_dir / "appstore_info.csv").touch()

    key_file = config_dir / "AuthKey_TESTKEY123.p8"
    key_file.write_text("fake-key-content")

    env_content = (
        "ISSUER_ID=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n"
        "KEY_ID=TESTKEY123\n"
        "KEY_FILE=AuthKey_TESTKEY123.p8\n"
        "APP_ID=9876543210\n"
    )
    (config_dir / ".env").write_text(env_content)
    return tmp_path


@pytest.fixture(autouse=True)
def isolated_global_dir(tmp_path, monkeypatch):
    """Redirect ~/.config/asc to a temp dir so tests don't pollute real config."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # Also patch Path.home() for code that calls it directly
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    return fake_home


runner = CliRunner()


def test_import_creates_profile(project_root, isolated_global_dir):
    """import command reads .env and creates a global profile"""
    result = runner.invoke(
        app,
        ["app", "import", "--path", str(project_root), "--name", "testapp"],
        input="n\n",  # decline set-as-default
    )
    assert result.exit_code == 0, result.output
    profile_path = isolated_global_dir / ".config" / "asc" / "profiles" / "testapp.toml"
    assert profile_path.exists()
    content = profile_path.read_text()
    assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in content
    assert "TESTKEY123" in content
    assert "9876543210" in content


def test_import_default_name_is_dirname(project_root, isolated_global_dir):
    """When --name omitted, profile name defaults to project directory name"""
    result = runner.invoke(
        app,
        ["app", "import", "--path", str(project_root)],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    expected_name = project_root.name
    profile_path = isolated_global_dir / ".config" / "asc" / "profiles" / f"{expected_name}.toml"
    assert profile_path.exists()


def test_import_copies_key_file(project_root, isolated_global_dir):
    """.p8 key file is copied to ~/.config/asc/keys/"""
    runner.invoke(
        app,
        ["app", "import", "--path", str(project_root), "--name", "testapp"],
        input="n\n",
    )
    dest = isolated_global_dir / ".config" / "asc" / "keys" / "AuthKey_TESTKEY123.p8"
    assert dest.exists()
    assert dest.read_text() == "fake-key-content"


def test_import_skips_existing_key_file(project_root, isolated_global_dir):
    """If key already exists in ~/.config/asc/keys/, it is NOT overwritten"""
    keys_dir = isolated_global_dir / ".config" / "asc" / "keys"
    keys_dir.mkdir(parents=True)
    dest = keys_dir / "AuthKey_TESTKEY123.p8"
    dest.write_text("original-content")

    runner.invoke(
        app,
        ["app", "import", "--path", str(project_root), "--name", "testapp"],
        input="n\n",
    )
    assert dest.read_text() == "original-content"  # not overwritten


def test_import_infers_csv_and_screenshots(project_root, isolated_global_dir):
    """csv and screenshots paths are inferred from AppStore/data/"""
    runner.invoke(
        app,
        ["app", "import", "--path", str(project_root), "--name", "testapp"],
        input="n\n",
    )
    profile_path = isolated_global_dir / ".config" / "asc" / "profiles" / "testapp.toml"
    content = profile_path.read_text()
    assert "AppStore/data/appstore_info.csv" in content
    assert "AppStore/data/screenshots" in content


def test_import_set_as_default(project_root, isolated_global_dir, tmp_path):
    """When user answers 'y', local .asc/config.toml is written with default_app"""
    result = runner.invoke(
        app,
        ["app", "import", "--path", str(project_root), "--name", "testapp"],
        input="y\n",  # accept set-as-default
    )
    assert result.exit_code == 0, result.output
    local_config = project_root / ".asc" / "config.toml"
    assert local_config.exists()
    assert "testapp" in local_config.read_text()


def test_import_missing_env_exits_nonzero(tmp_path, isolated_global_dir):
    """.env missing → exit code 1 with error message"""
    result = runner.invoke(
        app,
        ["app", "import", "--path", str(tmp_path), "--name", "testapp"],
    )
    assert result.exit_code == 1
    assert ".env" in result.output


def test_import_missing_field_exits_nonzero(tmp_path, isolated_global_dir):
    """Incomplete .env (missing APP_ID) → exit code 1"""
    config_dir = tmp_path / "AppStore" / "Config"
    config_dir.mkdir(parents=True)
    (config_dir / ".env").write_text("ISSUER_ID=x\nKEY_ID=y\nKEY_FILE=z.p8\n")
    (config_dir / "z.p8").write_text("k")
    result = runner.invoke(
        app,
        ["app", "import", "--path", str(tmp_path), "--name", "testapp"],
    )
    assert result.exit_code == 1
    assert "APP_ID" in result.output
