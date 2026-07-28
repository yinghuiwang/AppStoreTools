"""Tests for top-level CLI version output."""

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import pytest


def test_version_flag_prints_short_commit():
    """-v should include the short installed commit hash."""
    from typer.testing import CliRunner
    from asc.cli import app

    runner = CliRunner()
    with patch("asc.cli._installed_commit_short", return_value="15e4b3a"):
        result = runner.invoke(app, ["-v"])

    assert result.exit_code == 0
    assert "asc version" in result.output
    assert "(commit 15e4b3a)" in result.output


def test_installed_commit_short_reads_direct_url_metadata():
    """Installed git packages should report the commit from direct_url.json."""
    from asc.cli import _installed_commit_short

    dist = Mock()
    dist.read_text.return_value = (
        '{"vcs_info": {"commit_id": "15e4b3a8d9f0123456789abcdef0123456789abc"}}'
    )
    with patch("importlib.metadata.distribution", return_value=dist):
        assert _installed_commit_short() == "15e4b3a"


def test_run_app_no_args_shows_help_without_cross_mark(monkeypatch):
    """Bare `asc` should show help and not print a trailing ❌."""
    from asc.cli import run_app

    monkeypatch.setattr("sys.argv", ["asc"])
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = run_app()

    out = stdout.getvalue()
    err = stderr.getvalue()
    assert code == 0
    assert "Usage:" in out or "Commands" in out
    assert "❌" not in out
    assert "❌" not in err


def test_run_app_help_flag_shows_help_without_cross_mark(monkeypatch):
    """`asc --help` should show help without ❌."""
    from asc.cli import run_app

    monkeypatch.setattr("sys.argv", ["asc", "--help"])
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = run_app()

    out = stdout.getvalue()
    err = stderr.getvalue()
    assert code == 0
    assert "Usage:" in out or "Commands" in out
    assert "❌" not in out
    assert "❌" not in err


def test_run_app_unknown_command_still_prints_cross_mark(monkeypatch):
    """Unknown commands should still surface ❌ on stderr."""
    from asc.cli import run_app

    monkeypatch.setattr("sys.argv", ["asc", "nosuchcmd"])
    stderr = io.StringIO()
    with redirect_stderr(stderr), pytest.raises(SystemExit) as exc_info:
        run_app()

    assert exc_info.value.code == 1
    assert "❌" in stderr.getvalue()
    assert "nosuchcmd" in stderr.getvalue()
