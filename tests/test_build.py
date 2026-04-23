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


# ── detect_project tests ──

def test_detect_project_workspace(tmp_path):
    """Prefers .xcworkspace over .xcodeproj."""
    from asc.commands.build import detect_project
    ws = tmp_path / "MyApp.xcworkspace"
    ws.mkdir()
    proj = tmp_path / "MyApp.xcodeproj"
    proj.mkdir()
    path, kind = detect_project(str(tmp_path))
    assert path == str(ws)
    assert kind == "workspace"


def test_detect_project_xcodeproj(tmp_path):
    """Falls back to .xcodeproj when no workspace."""
    from asc.commands.build import detect_project
    proj = tmp_path / "MyApp.xcodeproj"
    proj.mkdir()
    path, kind = detect_project(str(tmp_path))
    assert path == str(proj)
    assert kind == "project"


def test_detect_project_explicit_path(tmp_path):
    """Explicit path is returned as-is (workspace)."""
    from asc.commands.build import detect_project
    ws = tmp_path / "MyApp.xcworkspace"
    ws.mkdir()
    path, kind = detect_project(str(ws))
    assert path == str(ws)
    assert kind == "workspace"


def test_detect_project_not_found(tmp_path):
    """Raises ValueError when no Xcode project found."""
    from asc.commands.build import detect_project
    with pytest.raises(ValueError, match="No Xcode project"):
        detect_project(str(tmp_path))


# ── list_schemes tests ──

def test_list_schemes_parses_output():
    """Parses scheme names from xcodebuild -list output."""
    from asc.commands.build import list_schemes
    fake_output = """
Information about project "MyApp":
    Schemes:
        MyApp
        MyAppTests
        MyAppUITests
"""
    with patch("asc.commands.build.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=fake_output, returncode=0)
        schemes = list_schemes("/path/to/MyApp.xcworkspace", "workspace")
    assert schemes == ["MyApp", "MyAppTests", "MyAppUITests"]


def test_list_schemes_raises_on_failure():
    """Raises RuntimeError when xcodebuild fails."""
    from asc.commands.build import list_schemes
    with patch("asc.commands.build.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="error: invalid project", returncode=1)
        with pytest.raises(RuntimeError, match="xcodebuild -list failed"):
            list_schemes("/invalid/path", "workspace")


# ── generate_export_options tests ──

def test_generate_export_options_auto_appstore(tmp_path):
    """Auto signing, appstore destination generates correct plist."""
    from asc.commands.build import generate_export_options
    plist_path = generate_export_options(
        signing="auto",
        destination="appstore",
        profile=None,
        certificate=None,
        output_dir=str(tmp_path),
    )
    with open(plist_path, "rb") as f:
        opts = plistlib.load(f)
    assert opts["method"] == "app-store-connect"
    assert opts["signingStyle"] == "automatic"
    assert "provisioningProfiles" not in opts


def test_generate_export_options_manual(tmp_path):
    """Manual signing generates provisioningProfiles and signingCertificate."""
    from asc.commands.build import generate_export_options
    plist_path = generate_export_options(
        signing="manual",
        destination="testflight",
        profile="/path/to/profile.mobileprovision",
        certificate="iPhone Distribution: ACME Corp",
        output_dir=str(tmp_path),
    )
    with open(plist_path, "rb") as f:
        opts = plistlib.load(f)
    assert opts["method"] == "app-store-connect"
    assert opts["signingStyle"] == "manual"
    assert opts["signingCertificate"] == "iPhone Distribution: ACME Corp"


def test_generate_export_options_testflight(tmp_path):
    """testflight destination uses app-store-connect method."""
    from asc.commands.build import generate_export_options
    plist_path = generate_export_options(
        signing="auto",
        destination="testflight",
        profile=None,
        certificate=None,
        output_dir=str(tmp_path),
    )
    with open(plist_path, "rb") as f:
        opts = plistlib.load(f)
    assert opts["method"] == "app-store-connect"


def test_generate_export_options_manual_requires_profile(tmp_path):
    """Manual signing without profile raises ValueError."""
    from asc.commands.build import generate_export_options
    with pytest.raises(ValueError, match="Manual signing requires a provisioning profile"):
        generate_export_options(
            signing="manual",
            destination="appstore",
            profile=None,
            certificate="iPhone Distribution: ACME Corp",
            output_dir=str(tmp_path),
        )
