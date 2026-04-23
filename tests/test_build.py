"""Tests for build/deploy/release commands."""
from __future__ import annotations

import sys
import plistlib
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import pytest
from typer.testing import CliRunner

from asc.cli import app
from asc.config import Config

runner = CliRunner()


# ── Config tests ──

def test_config_build_project(tmp_path, monkeypatch):
    """Config reads build.project from local config.toml."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".asc").mkdir()
    (tmp_path / ".asc" / "config.toml").write_text(
        '[build]\nproject = "MyApp.xcworkspace"\n'
    )
    cfg = Config()
    assert cfg.build_project == "MyApp.xcworkspace"


def test_config_build_defaults(tmp_path, monkeypatch):
    """Config returns None for build fields when not configured."""
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    assert cfg.build_project is None
    assert cfg.build_scheme is None
    assert cfg.build_output == "build"
    assert cfg.build_signing == "auto"
