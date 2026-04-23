"""Tests for cmd_app_show and cmd_app_edit."""
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
