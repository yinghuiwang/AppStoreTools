from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from asc.cli import app
from asc.commands import uninstall_cmd

runner = CliRunner()


def test_uninstall_yes_calls_pip(monkeypatch):
    calls = []

    def fake_check_call(cmd):
        calls.append(cmd)
        return 0

    monkeypatch.setattr(uninstall_cmd.subprocess, "check_call", fake_check_call)
    result = runner.invoke(app, ["uninstall", "--yes"])
    assert result.exit_code == 0
    assert calls
    assert calls[0][-2:] == ["uninstall", "-y"] or "asc-appstore-tools" in calls[0]
    assert "asc-appstore-tools" in calls[0]
    assert "Done" in result.output


def test_uninstall_cancel_does_not_call_pip(monkeypatch):
    called = []
    monkeypatch.setattr(
        uninstall_cmd.subprocess,
        "check_call",
        lambda cmd: called.append(cmd),
    )
    result = runner.invoke(app, ["uninstall"], input="n\n")
    assert result.exit_code == 0
    assert called == []
    assert "Cancelled" in result.output


def test_uninstall_pip_failure_exits(monkeypatch):
    def boom(cmd):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(uninstall_cmd.subprocess, "check_call", boom)
    result = runner.invoke(app, ["uninstall", "--yes"])
    assert result.exit_code == 1
    assert "Failed to uninstall" in result.output or "Failed to uninstall" in (result.stderr or "")
