# tests/test_guard_integration.py
from __future__ import annotations
import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock


def _mock_guard(enabled=True, has_conflict=False):
    mock = MagicMock()
    mock.is_enabled.return_value = enabled
    if has_conflict:
        from asc.guard import GuardViolationError
        mock.check_and_enforce.side_effect = GuardViolationError("冲突")
    return mock


def test_upload_blocked_when_guard_conflict():
    from asc.cli import app
    runner = CliRunner()
    with patch("asc.commands.metadata.Guard", return_value=_mock_guard(has_conflict=True)):
        result = runner.invoke(app, ["--app", "myapp", "upload"])
    assert result.exit_code == 1


def test_deploy_blocked_when_guard_conflict():
    from asc.cli import app
    runner = CliRunner()
    with patch("asc.commands.build.Guard", return_value=_mock_guard(has_conflict=True)):
        result = runner.invoke(app, ["deploy", "--ipa", "fake.ipa"])
    assert result.exit_code == 1


def test_iap_blocked_when_guard_conflict():
    from asc.cli import app
    runner = CliRunner()
    with patch("asc.commands.iap.Guard", return_value=_mock_guard(has_conflict=True)):
        result = runner.invoke(app, ["iap", "--iap-file", "fake.json"])
    assert result.exit_code == 1


def test_screenshots_blocked_when_guard_conflict():
    from asc.cli import app
    runner = CliRunner()
    with patch("asc.commands.screenshots.Guard", return_value=_mock_guard(has_conflict=True)):
        result = runner.invoke(app, ["screenshots"])
    assert result.exit_code == 1


def test_whats_new_blocked_when_guard_conflict():
    from asc.cli import app
    runner = CliRunner()
    with patch("asc.commands.whats_new.Guard", return_value=_mock_guard(has_conflict=True)):
        result = runner.invoke(app, ["whats-new", "--text", "Bug fixes."])
    assert result.exit_code == 1
