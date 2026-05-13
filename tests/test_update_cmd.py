"""Tests for update_cmd module."""

from unittest.mock import patch, MagicMock
import pytest


class TestSimilarVersions:
    """Tests for _similar_versions function."""

    def test_similar_versions_returns_closest(self):
        """Should return closest versions to target."""
        from asc.commands.update_cmd import _similar_versions
        all_versions = ["0.1.5", "0.1.6", "0.1.7", "0.1.8", "0.2.0"]
        result = _similar_versions("0.1.5", all_versions, limit=3)
        # 0.1.5 should be first (exact match), then 0.1.6, 0.1.7
        assert result[0] == "0.1.5"
        assert len(result) == 3

    def test_similar_versions_with_nonexistent(self):
        """Should return similar versions for nonexistent target."""
        from asc.commands.update_cmd import _similar_versions
        all_versions = ["0.1.6", "0.1.7", "0.1.8"]
        result = _similar_versions("0.1.5", all_versions, limit=2)
        assert "0.1.6" in result
        assert "0.1.7" in result


class TestCmdUpdateValidation:
    """Tests for cmd_update parameter validation."""

    def test_version_and_branch_mutual_exclusion(self):
        """Should error when both --version and --branch provided."""
        from typer.testing import CliRunner
        from asc.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["update", "--version", "0.1.5", "--branch", "main"])
        assert result.exit_code == 1
        assert "Cannot use --version and --branch" in result.output
