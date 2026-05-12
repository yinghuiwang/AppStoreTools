"""Tests for build/deploy/release commands."""
from __future__ import annotations

import subprocess
import sys
import plistlib
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import pytest
from typer.testing import CliRunner

from asc.cli import app
from asc.config import Config
from asc.commands.build_inputs import ResolvedInputs

runner = CliRunner()


class _FakeSpinner:
    """Fake Spinner for tests. Configure via class attrs before use."""
    returncode: int = 0
    stderr: str = ""

    def __init__(self, label, *, log_path, verbose=False, tty=None):
        self.label = label
        self.log_path = log_path

    def run(self, cmd):
        # Write a minimal log file so helpers that read it don't error
        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.log_path).write_text(self.__class__.stderr or "")
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=self.__class__.returncode,
            stdout="",
            stderr=self.__class__.stderr,
        )


def _resolved(**overrides):
    base = dict(
        project_path="/tmp/x.xcodeproj", project_kind="project",
        scheme="X", bundle_id="com.x", signing="auto",
        certificate=None, profile=None, destination="appstore",
    )
    base.update(overrides)
    return ResolvedInputs(**base)


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


def test_generate_export_options_manual(tmp_path, monkeypatch):
    """Manual signing generates provisioningProfiles (bundle_id → UUID) and signingCertificate."""
    from asc.commands.build import generate_export_options
    from asc.commands.build_inputs import ProfileInfo
    from datetime import datetime, timezone, timedelta

    fake_info = ProfileInfo(
        path="/path/to/profile.mobileprovision",
        uuid="ABC-123-UUID",
        name="AppStore_ACME",
        team_id="TEAM",
        bundle_id="com.acme.app",
        expiration=datetime.now(timezone.utc) + timedelta(days=30),
        cert_sha1s=[],
    )
    monkeypatch.setattr(
        "asc.commands.build_inputs.parse_mobileprovision",
        lambda _: fake_info,
    )

    plist_path = generate_export_options(
        signing="manual",
        destination="testflight",
        profile="/path/to/profile.mobileprovision",
        certificate="iPhone Distribution: ACME Corp",
        output_dir=str(tmp_path),
        bundle_id="com.acme.app",
    )
    with open(plist_path, "rb") as f:
        opts = plistlib.load(f)
    assert opts["method"] == "app-store-connect"
    assert opts["signingStyle"] == "manual"
    assert opts["signingCertificate"] == "iPhone Distribution: ACME Corp"
    # Critical: value must be UUID (or Name), NOT the file path.
    assert opts["provisioningProfiles"] == {"com.acme.app": "ABC-123-UUID"}


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


# ── run_xcodebuild_archive / export tests ──

def test_run_xcodebuild_archive_calls_correct_command(tmp_path, monkeypatch):
    """Calls xcodebuild archive with correct flags."""
    from asc.commands.build import run_xcodebuild_archive
    archive_path = tmp_path / "MyApp.xcarchive"
    archive_path.mkdir()

    captured_cmd = {}

    class _TrackingSpinner(_FakeSpinner):
        def run(self, cmd):
            captured_cmd["cmd"] = cmd
            return super().run(cmd)

    _TrackingSpinner.returncode = 0
    _TrackingSpinner.stderr = ""
    monkeypatch.setattr("asc.commands.build.Spinner", _TrackingSpinner)

    result = run_xcodebuild_archive(
        project="/path/MyApp.xcworkspace",
        kind="workspace",
        scheme="MyApp",
        configuration="Release",
        archive_path=str(archive_path),
    )

    cmd = captured_cmd["cmd"]
    assert "xcodebuild" in cmd
    assert "archive" in cmd
    assert "-workspace" in cmd
    assert "-scheme" in cmd
    assert "MyApp" in cmd


def test_run_xcodebuild_archive_raises_on_failure(tmp_path, monkeypatch):
    """Raises RuntimeError when xcodebuild returns non-zero."""
    from asc.commands.build import run_xcodebuild_archive

    _FakeSpinner.returncode = 1
    _FakeSpinner.stderr = "Build FAILED"
    monkeypatch.setattr("asc.commands.build.Spinner", _FakeSpinner)

    with pytest.raises(RuntimeError, match="xcodebuild archive failed"):
        run_xcodebuild_archive(
            project="/path/MyApp.xcworkspace",
            kind="workspace",
            scheme="MyApp",
            configuration="Release",
            archive_path=str(tmp_path / "MyApp.xcarchive"),
        )

    _FakeSpinner.returncode = 0
    _FakeSpinner.stderr = ""


def test_run_xcodebuild_export_calls_correct_command(tmp_path, monkeypatch):
    """Calls xcodebuild -exportArchive with correct flags."""
    from asc.commands.build import run_xcodebuild_export
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    ipa = export_dir / "MyApp.ipa"
    ipa.write_bytes(b"fake")

    captured_cmd = {}

    class _TrackingSpinner(_FakeSpinner):
        def run(self, cmd):
            captured_cmd["cmd"] = cmd
            return super().run(cmd)

    _TrackingSpinner.returncode = 0
    _TrackingSpinner.stderr = ""
    monkeypatch.setattr("asc.commands.build.Spinner", _TrackingSpinner)

    result = run_xcodebuild_export(
        archive_path=str(tmp_path / "MyApp.xcarchive"),
        export_options_path="/tmp/ExportOptions.plist",
        output_dir=str(export_dir),
    )

    cmd = captured_cmd["cmd"]
    assert "-exportArchive" in cmd
    assert "-exportOptionsPlist" in cmd
    assert result == str(ipa)


# ── build_core / cmd_build tests ──

def test_build_core_dry_run(tmp_path, monkeypatch, capsys):
    """build_core with dry_run=True prints command info without running."""
    from asc.commands.build import build_core
    monkeypatch.chdir(tmp_path)
    ws = tmp_path / "MyApp.xcworkspace"
    ws.mkdir()

    resolved = _resolved(
        project_path=str(ws), project_kind="workspace",
        scheme="MyApp", signing="auto", destination="appstore",
    )
    ipa_path = build_core(
        resolved,
        str(tmp_path / "build"),
        dry_run=True,
    )
    assert ipa_path is None
    captured = capsys.readouterr()
    assert "MyApp" in captured.out
    assert "[预览]" in captured.out or "dry" in captured.out.lower()


def test_cmd_build_non_macos():
    """asc build on non-macOS exits with code 2."""
    with patch("asc.commands.build.sys") as mock_sys:
        mock_sys.platform = "linux"
        result = runner.invoke(app, ["build", "--scheme", "MyApp"])
    assert result.exit_code == 2


# ── upload_ipa / deploy_core / cmd_deploy tests ──

def test_upload_ipa_uses_altool(tmp_path, monkeypatch):
    """upload_ipa calls xcrun altool for iOS uploads."""
    from asc.commands.build import upload_ipa
    ipa = tmp_path / "MyApp.ipa"
    ipa.write_bytes(b"fake")

    captured_cmd = {}

    class _TrackingSpinner(_FakeSpinner):
        def run(self, cmd):
            captured_cmd["cmd"] = cmd
            return super().run(cmd)

    _TrackingSpinner.returncode = 0
    _TrackingSpinner.stderr = ""
    monkeypatch.setattr("asc.commands.build.Spinner", _TrackingSpinner)

    upload_ipa(
        ipa_path=str(ipa),
        issuer_id="issuer-123",
        key_id="key-456",
        key_file="/path/to/key.p8",
        destination="testflight",
    )

    cmd = captured_cmd["cmd"]
    assert "xcrun" in cmd
    assert "altool" in cmd
    assert "--upload-app" in cmd


def test_upload_ipa_raises_on_failure(tmp_path, monkeypatch):
    """upload_ipa raises RuntimeError on non-zero returncode."""
    from asc.commands.build import upload_ipa
    ipa = tmp_path / "MyApp.ipa"
    ipa.write_bytes(b"fake")

    _FakeSpinner.returncode = 1
    _FakeSpinner.stderr = "Upload failed"
    monkeypatch.setattr("asc.commands.build.Spinner", _FakeSpinner)

    with pytest.raises(RuntimeError, match="Upload failed"):
        upload_ipa(
            ipa_path=str(ipa),
            issuer_id="issuer-123",
            key_id="key-456",
            key_file="/path/to/key.p8",
            destination="testflight",
        )

    _FakeSpinner.returncode = 0
    _FakeSpinner.stderr = ""


def test_cmd_deploy_non_macos():
    """asc deploy on non-macOS exits with code 2."""
    with patch("asc.commands.build.sys") as mock_sys:
        mock_sys.platform = "linux"
        result = runner.invoke(app, ["deploy", "--ipa", "MyApp.ipa"])
    assert result.exit_code == 2


def test_deploy_core_dry_run(tmp_path, capsys):
    """deploy_core with dry_run=True prints info without uploading."""
    from asc.commands.build import deploy_core
    ipa = tmp_path / "MyApp.ipa"
    ipa.write_bytes(b"fake")

    deploy_core(
        ipa_path=str(ipa),
        issuer_id="issuer-123",
        key_id="key-456",
        key_file="/path/to/key.p8",
        destination="testflight",
        dry_run=True,
    )
    captured = capsys.readouterr()
    assert "MyApp.ipa" in captured.out
    assert "[预览]" in captured.out or "dry" in captured.out.lower()


# ── cmd_release tests ──

def test_cmd_release_non_macos():
    """asc release on non-macOS exits with code 2."""
    with patch("asc.commands.build.sys") as mock_sys:
        mock_sys.platform = "linux"
        result = runner.invoke(app, ["release", "--scheme", "MyApp"])
    assert result.exit_code == 2


def test_release_calls_build_and_deploy(tmp_path, monkeypatch):
    """asc release calls build_core then deploy_core."""
    from asc.commands import build as build_mod
    from asc.commands.build_inputs import ResolvedInputs
    monkeypatch.chdir(tmp_path)
    ws = tmp_path / "MyApp.xcworkspace"
    ws.mkdir()

    fake_resolved = _resolved(
        project_path=str(ws), project_kind="workspace",
        scheme="MyApp", destination="testflight",
    )

    with patch.object(build_mod, "prepare_build_inputs", return_value=fake_resolved), \
         patch.object(build_mod, "build_core", return_value="/tmp/MyApp.ipa") as mock_build, \
         patch.object(build_mod, "deploy_core") as mock_deploy, \
         patch.object(build_mod, "sys") as mock_sys, \
         patch.object(build_mod, "resolve_app_profile", return_value="test-app"):
        mock_sys.platform = "darwin"
        result = runner.invoke(app, [
            "release",
            "--project", str(ws),
            "--scheme", "MyApp",
            "--destination", "testflight",
            "--no-interactive",
            "--app", "test-app",
        ])

    assert mock_build.called
    assert mock_deploy.called


def test_asc_help_shows_build_deploy_release():
    """asc --help lists build, deploy, release commands."""
    result = runner.invoke(app, ["--help"])
    assert "build" in result.output
    assert "deploy" in result.output
    assert "release" in result.output


def test_cmd_build_calls_prepare_build_inputs(monkeypatch, tmp_path):
    """Verifies cmd_build goes through prepare_build_inputs and passes --no-interactive."""
    captured = {}
    from asc.commands.build_inputs import ResolvedInputs

    def fake_prepare(cli, config, *, interactive):
        captured["interactive"] = interactive
        captured["cli"] = cli
        return ResolvedInputs(
            project_path=str(tmp_path / "x.xcodeproj"), project_kind="project",
            scheme="X", bundle_id="com.x", signing="auto",
            certificate=None, profile=None, destination="appstore",
        )

    monkeypatch.setattr("asc.commands.build.prepare_build_inputs", fake_prepare)
    monkeypatch.setattr("asc.commands.build.build_core", lambda *a, **kw: None)
    # Bypass macOS gate for test
    monkeypatch.setattr("asc.commands.build._require_macos", lambda: None)
    # Mock resolve_app_profile so --app test-app works without global config
    monkeypatch.setattr("asc.commands.build.resolve_app_profile", lambda app, config: "test-app")

    runner = CliRunner()
    result = runner.invoke(app, ["build", "--no-interactive", "--dry-run", "--app", "test-app"])
    assert result.exit_code == 0, result.output
    assert captured["interactive"] is False


def test_cmd_build_passes_cli_signing_and_profile(monkeypatch, tmp_path):
    """Verifies CLI flags flow into BuildInputsCLI correctly."""
    captured = {}
    from asc.commands.build_inputs import ResolvedInputs

    def fake_prepare(cli, config, *, interactive):
        captured["cli"] = cli
        return ResolvedInputs(
            project_path=str(tmp_path / "x.xcodeproj"), project_kind="project",
            scheme="X", bundle_id="com.x", signing="manual",
            certificate="C", profile="/p", destination="appstore",
        )

    monkeypatch.setattr("asc.commands.build.prepare_build_inputs", fake_prepare)
    monkeypatch.setattr("asc.commands.build.build_core", lambda *a, **kw: None)
    monkeypatch.setattr("asc.commands.build._require_macos", lambda: None)
    # Mock resolve_app_profile so --app test-app works without global config
    monkeypatch.setattr("asc.commands.build.resolve_app_profile", lambda app, config: "test-app")

    runner = CliRunner()
    result = runner.invoke(app, [
        "build", "--no-interactive", "--dry-run", "--app", "test-app",
        "--signing", "manual",
        "--profile", "/some/path.mobileprovision",
        "--certificate", "Apple Distribution: foo",
    ])
    assert result.exit_code == 0, result.output
    assert captured["cli"].signing == "manual"
    assert captured["cli"].profile == "/some/path.mobileprovision"
    assert captured["cli"].certificate == "Apple Distribution: foo"


def test_cmd_build_passes_verbose_flag(monkeypatch, tmp_path):
    """--verbose flag flows from CLI through build_core to subprocess wrappers."""
    captured = {}
    from asc.commands.build_inputs import ResolvedInputs

    def fake_prepare(cli, config, *, interactive):
        return ResolvedInputs(
            project_path=str(tmp_path / "x.xcodeproj"), project_kind="project",
            scheme="X", bundle_id="com.x", signing="auto",
            certificate=None, profile=None, destination="appstore",
        )

    def fake_build_core(*args, **kwargs):
        captured["verbose"] = kwargs.get("verbose")
        return None

    monkeypatch.setattr("asc.commands.build.prepare_build_inputs", fake_prepare)
    monkeypatch.setattr("asc.commands.build.build_core", fake_build_core)
    monkeypatch.setattr("asc.commands.build._require_macos", lambda: None)
    # Mock resolve_app_profile so --app test-app works without global config
    monkeypatch.setattr("asc.commands.build.resolve_app_profile", lambda app, config: "test-app")

    from typer.testing import CliRunner
    from asc.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["build", "--verbose", "--no-interactive", "--dry-run", "--app", "test-app"])
    assert result.exit_code == 0, result.output
    assert captured["verbose"] is True


# ── A4: archive reuse step-0 tests ──

from asc.commands.build_inputs import (
    ArchiveInfo as _ArchiveInfo,
    ResolvedInputs as _ResolvedInputs,
)
from datetime import datetime, timezone


def _make_resolved(**overrides):
    base = dict(
        project_path="/tmp/x.xcodeproj", project_kind="project",
        scheme="X", bundle_id="com.x", signing="auto",
        certificate=None, profile=None, destination="appstore",
    )
    base.update(overrides)
    return _ResolvedInputs(**base)


def test_build_core_reuses_matching_archive_when_reuse_true(monkeypatch, tmp_path):
    """When a matching archive exists and reuse=True, archive step is skipped."""
    from asc.commands.build import build_core
    arc_info = _ArchiveInfo(
        path=str(tmp_path / "X.xcarchive"),
        bundle_id="com.x", marketing_version="1.0", build_number="1",
        created=datetime.now(timezone.utc),
    )
    archive_called = {"called": False}
    export_called = {"called": False}

    monkeypatch.setattr("asc.commands.build.detect_versions",
                        lambda *a, **kw: ("1.0", "1"))
    monkeypatch.setattr("asc.commands.build.scan_archives",
                        lambda *a, **kw: [arc_info])
    monkeypatch.setattr("asc.commands.build.find_matching_archive",
                        lambda *a, **kw: arc_info)

    def fake_archive(*a, **kw):
        archive_called["called"] = True
        return a[-1]
    def fake_export(archive_path, opts, out, **kw):
        export_called["called"] = True
        return str(tmp_path / "X.ipa")

    monkeypatch.setattr("asc.commands.build.run_xcodebuild_archive", fake_archive)
    monkeypatch.setattr("asc.commands.build.run_xcodebuild_export", fake_export)
    monkeypatch.setattr("asc.commands.build.generate_export_options",
                        lambda **kw: str(tmp_path / "ExportOptions.plist"))

    resolved = _make_resolved()
    ipa = build_core(resolved, output=str(tmp_path), reuse_archive=True, dry_run=False)

    assert archive_called["called"] is False, "archive step should be skipped"
    assert export_called["called"] is True


def test_build_core_runs_archive_when_reuse_false(monkeypatch, tmp_path):
    """Even with a matching archive present, reuse=False forces re-archive."""
    from asc.commands.build import build_core
    arc_info = _ArchiveInfo(
        path=str(tmp_path / "X.xcarchive"),
        bundle_id="com.x", marketing_version="1.0", build_number="1",
        created=datetime.now(timezone.utc),
    )
    archive_called = {"called": False}

    monkeypatch.setattr("asc.commands.build.detect_versions",
                        lambda *a, **kw: ("1.0", "1"))
    monkeypatch.setattr("asc.commands.build.scan_archives",
                        lambda *a, **kw: [arc_info])
    monkeypatch.setattr("asc.commands.build.find_matching_archive",
                        lambda *a, **kw: arc_info)

    def fake_archive(*a, **kw):
        archive_called["called"] = True
        return a[-1]
    monkeypatch.setattr("asc.commands.build.run_xcodebuild_archive", fake_archive)
    monkeypatch.setattr("asc.commands.build.run_xcodebuild_export",
                        lambda *a, **kw: str(tmp_path / "X.ipa"))
    monkeypatch.setattr("asc.commands.build.generate_export_options",
                        lambda **kw: str(tmp_path / "ExportOptions.plist"))

    resolved = _make_resolved()
    build_core(resolved, output=str(tmp_path), reuse_archive=False, dry_run=False)
    assert archive_called["called"] is True


def test_build_core_no_matching_archive_runs_archive(monkeypatch, tmp_path):
    """No matching archive → always archives."""
    from asc.commands.build import build_core
    archive_called = {"called": False}

    monkeypatch.setattr("asc.commands.build.detect_versions",
                        lambda *a, **kw: ("1.0", "1"))
    monkeypatch.setattr("asc.commands.build.scan_archives",
                        lambda *a, **kw: [])
    monkeypatch.setattr("asc.commands.build.find_matching_archive",
                        lambda *a, **kw: None)

    def fake_archive(*a, **kw):
        archive_called["called"] = True
        return a[-1]
    monkeypatch.setattr("asc.commands.build.run_xcodebuild_archive", fake_archive)
    monkeypatch.setattr("asc.commands.build.run_xcodebuild_export",
                        lambda *a, **kw: str(tmp_path / "X.ipa"))
    monkeypatch.setattr("asc.commands.build.generate_export_options",
                        lambda **kw: str(tmp_path / "ExportOptions.plist"))

    resolved = _make_resolved()
    build_core(resolved, output=str(tmp_path), reuse_archive=None, dry_run=False)
    assert archive_called["called"] is True


def test_build_core_versions_unavailable_skips_reuse_check(monkeypatch, tmp_path):
    """If detect_versions returns None, scan_archives is not even called."""
    from asc.commands.build import build_core
    scan_called = {"called": False}

    monkeypatch.setattr("asc.commands.build.detect_versions",
                        lambda *a, **kw: None)

    def fake_scan(*a, **kw):
        scan_called["called"] = True
        return []
    monkeypatch.setattr("asc.commands.build.scan_archives", fake_scan)
    monkeypatch.setattr("asc.commands.build.run_xcodebuild_archive",
                        lambda *a, **kw: a[-1])
    monkeypatch.setattr("asc.commands.build.run_xcodebuild_export",
                        lambda *a, **kw: str(tmp_path / "X.ipa"))
    monkeypatch.setattr("asc.commands.build.generate_export_options",
                        lambda **kw: str(tmp_path / "ExportOptions.plist"))

    resolved = _make_resolved()
    build_core(resolved, output=str(tmp_path), reuse_archive=None, dry_run=False)
    assert scan_called["called"] is False
