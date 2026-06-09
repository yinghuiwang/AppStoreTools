"""Tests for update_cmd module."""

from unittest.mock import patch


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


def test_branches_from_github_parses_remote_heads():
    from asc.commands.update_cmd import _branches_from_github

    output = (
        "a" * 40 + "\trefs/heads/main\n"
        + "b" * 40 + "\trefs/heads/develop\n"
        + "c" * 40 + "\trefs/tags/v0.1.0\n"
    )
    with patch("asc.commands.update_cmd.subprocess.check_output", return_value=output):
        assert _branches_from_github() == ["develop", "main"]


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

    def test_branch_install_prints_and_installs_resolved_commit(self):
        """Should print the resolved commit and install that exact commit."""
        from typer.testing import CliRunner
        from asc.cli import app

        commit = "a" * 40
        runner = CliRunner()
        with patch("asc.commands.update_cmd._resolve_git_ref_commit", return_value=commit), \
                patch("asc.commands.update_cmd.subprocess.check_call") as check_call:
            result = runner.invoke(app, ["update", "--branch", "main"])

        assert result.exit_code == 0
        assert f"Install commit : {commit}" in result.output
        assert f"commit {commit}" in result.output
        install_args = check_call.call_args.args[0]
        assert install_args[-1].endswith(f"@{commit}")

    def test_version_install_prints_and_installs_resolved_commit(self):
        """Should print the resolved commit when installing a specific version."""
        from typer.testing import CliRunner
        from asc.cli import app

        commit = "b" * 40
        runner = CliRunner()
        with patch("asc.commands.update_cmd._all_versions_from_github", return_value=["0.1.5"]), \
                patch("asc.commands.update_cmd._resolve_git_ref_commit", return_value=commit), \
                patch("asc.commands.update_cmd.subprocess.check_call") as check_call:
            result = runner.invoke(app, ["update", "--version", "0.1.5"])

        assert result.exit_code == 0
        assert f"Install commit : {commit}" in result.output
        assert f"Done. asc updated to v0.1.5 (commit {commit})." in result.output
        install_args = check_call.call_args.args[0]
        assert install_args[-1].endswith(f"@{commit}")


class TestResolveGitRefCommit:
    """Tests for resolving git refs to commit hashes."""

    def test_resolve_prefers_peeled_tag_commit(self):
        """Annotated tags should resolve to the peeled commit, not the tag object."""
        from asc.commands.update_cmd import _resolve_git_ref_commit

        tag_object = "c" * 40
        peeled_commit = "d" * 40
        output = (
            f"{tag_object}\trefs/tags/v0.1.5\n"
            f"{peeled_commit}\trefs/tags/v0.1.5^{{}}\n"
        )
        with patch("asc.commands.update_cmd.subprocess.check_output", return_value=output):
            assert _resolve_git_ref_commit("v0.1.5") == peeled_commit
