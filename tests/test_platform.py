"""Windows capability gates shared by the CLI and the Web UI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from asc.cli import app
from asc.i18n import LANG
from asc.platform import (
    cli_allows,
    feature_supported,
    platform_status,
    web_unsupported_features,
)
from asc.schedule import ScheduleError, heartbeat_status, install_heartbeat
from asc.web.server import create_app

runner = CliRunner()

_UNSUPPORTED = "Not supported on this operating system" if LANG == "en" else "当前系统不支持"


def _client() -> TestClient:
    client = TestClient(create_app())
    assert client.get("/").status_code in {200, 404}
    return client


def test_windows_disables_toolchain_only():
    assert web_unsupported_features("win32") == ["build", "deploy", "release"]
    assert feature_supported("build", "Windows") is False
    assert feature_supported("deploy", "win32") is False
    assert feature_supported("release", "windows") is False
    assert feature_supported("schedule", "win32") is True
    assert cli_allows("schedule", "win32") is True
    for feature in ("metadata", "screenshots", "iap", "whats-new", "urls", "guard", "web"):
        assert feature_supported(feature, "win32") is True
        assert cli_allows(feature, "win32") is True


def test_non_windows_web_stays_enabled():
    assert platform_status("Darwin")["windows"] is False
    assert platform_status("Darwin")["unsupported"] == []
    assert platform_status("Linux")["unsupported"] == []
    assert feature_supported("build", "linux") is True
    assert feature_supported("schedule", "darwin") is True


def test_cli_toolchain_stays_macos_only_and_schedule_allows_hosts():
    assert cli_allows("build", "darwin") is True
    assert cli_allows("deploy", "linux") is False
    assert cli_allows("release", "win32") is False
    assert cli_allows("schedule", "darwin") is True
    assert cli_allows("schedule", "linux") is True
    assert cli_allows("schedule", "win32") is True


def test_build_help_notes_macos_only():
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0
    note = "macOS only" if LANG == "en" else "仅 macOS"
    assert note in result.output


@pytest.mark.parametrize("command", [
    ["build", "--scheme", "MyApp"],
    ["deploy", "--ipa", "MyApp.ipa"],
    ["release", "--scheme", "MyApp"],
])
def test_cli_windows_rejects_toolchain_before_subprocess(command):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("subprocess should not run")

    with patch("asc.commands.build.sys.platform", "win32"), \
         patch("asc.commands.build.subprocess.run", side_effect=_forbidden), \
         patch("asc.commands.build_inputs.subprocess.run", side_effect=_forbidden):
        result = runner.invoke(app, command)
    assert result.exit_code != 0
    assert _UNSUPPORTED in result.output


def test_cli_linux_still_rejects_build():
    with patch("asc.commands.build.sys.platform", "linux"):
        result = runner.invoke(app, ["build", "--scheme", "MyApp"])
    assert result.exit_code == 2
    assert _UNSUPPORTED in result.output


def test_cli_darwin_build_is_not_rejected_as_unsupported(monkeypatch):
    monkeypatch.setattr("asc.commands.build.sys.platform", "darwin")
    monkeypatch.setattr("asc.commands.build._require_macos", lambda: None)
    monkeypatch.setattr("asc.commands.build.resolve_app_profile", lambda app, config: "test-app")
    monkeypatch.setattr("asc.commands.build.prepare_build_inputs", lambda *a, **k: None)
    result = runner.invoke(app, ["build", "--no-interactive", "--app", "test-app"])
    assert _UNSUPPORTED not in result.output


def test_schedule_help_still_lists_commands():
    result = runner.invoke(app, ["schedule", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "install" in result.output


def test_schedule_windows_lists_instead_of_platform_refusal():
    with patch("asc.commands.schedule_cmd.sys.platform", "win32"), \
         patch("asc.schedule.list_tasks", return_value=[]):
        result = runner.invoke(app, ["schedule", "list"])
    assert result.exit_code == 0
    assert _UNSUPPORTED not in result.output


def test_heartbeat_windows_backend_does_not_call_crontab(tmp_path):
    backend = MagicMock()
    backend.system.return_value = "windows"
    backend.read_task_xml.return_value = None
    assert heartbeat_status(backend=backend) == {"installed": False, "path": ""}
    backend.read_crontab.assert_not_called()
    backend.read_plist.assert_not_called()
    backend.uid.assert_not_called()
    backend.ensure_user_agent.assert_not_called()
    backend.write_task_xml.side_effect = AssertionError("schtasks")
    with pytest.raises(ScheduleError) as exc:
        install_heartbeat(asc_path=tmp_path / "missing.exe", backend=backend)
    assert exc.value.code == "not_executable"
    backend.write_task_xml.assert_not_called()
    backend.read_crontab.assert_not_called()


def test_guard_windows_fingerprint_skips_ioreg(tmp_path):
    from asc.guard import Guard, _clear_machine_fingerprint_cache

    _clear_machine_fingerprint_cache()
    with patch("asc.guard.GUARD_FILE", tmp_path / "guard.json"), \
         patch("asc.guard.sys.platform", "win32"), \
         patch("asc.guard.subprocess.run") as run, \
         patch("asc.guard.platform.node", return_value="win-host"), \
         patch("asc.guard.uuid.getnode", return_value=99):
        fp = Guard()._get_machine_fingerprint()
    assert fp == "win-host-99"
    run.assert_not_called()
    _clear_machine_fingerprint_cache()


def test_bootstrap_reports_server_os_not_user_agent():
    client = _client()
    darwin = client.get("/api/bootstrap", headers={"User-Agent": "Windows NT 10.0"}).json()
    assert darwin["platform"]["windows"] is False
    assert darwin["platform"]["unsupported"] == []

    with patch("asc.platform.sys.platform", "win32"):
        windows = client.get(
            "/api/bootstrap",
            headers={"User-Agent": "Macintosh", "Accept-Language": "zh"},
        ).json()
    assert windows["platform"]["system"] == "Windows"
    assert windows["platform"]["windows"] is True
    assert windows["platform"]["unsupported"] == ["build", "deploy", "release"]


def test_web_windows_rejects_build_but_allows_schedule():
    client = _client()
    with patch("asc.platform.sys.platform", "win32"), \
         patch("asc.web.routes_api._start_build_task", side_effect=AssertionError("build")), \
         patch("asc.commands.build_inputs.list_schemes", side_effect=AssertionError("xcodebuild")), \
         patch("asc.schedule.list_tasks", return_value=[]), \
         patch("asc.schedule.heartbeat_status", return_value={"installed": False, "path": ""}):
        build = client.post(
            "/api/build/run",
            data={"mode": "full"},
            headers={"Accept-Language": "en"},
        )
        schemes = client.get("/api/build/schemes", headers={"Accept-Language": "en"})
        options = client.get("/api/build/options", headers={"Accept-Language": "en"})
        schedules = client.get("/api/schedules", headers={"Accept-Language": "zh"})
    assert build.status_code == 400
    assert build.json()["error"] == "Not supported on this operating system"
    assert schemes.status_code == 400
    assert options.status_code == 400
    assert schedules.status_code == 200
    assert schedules.json()["tasks"] == []
    assert schedules.json()["heartbeat"] == {"installed": False, "path": ""}
    assert "error" not in schedules.json()


def test_web_darwin_build_is_not_marked_unsupported():
    client = _client()
    with patch("asc.platform.sys.platform", "darwin"):
        resp = client.post(
            "/api/build/run",
            data={"mode": "build"},
            headers={"Accept-Language": "en"},
        )
    assert resp.status_code == 400
    assert resp.json()["error"] != "Not supported on this operating system"
