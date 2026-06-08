"""Tests for top-level CLI version output."""

from unittest.mock import Mock, patch


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
