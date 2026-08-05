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
                patch("asc.commands.update_cmd._install_git_ref") as install:
            result = runner.invoke(app, ["update", "--branch", "main"])

        assert result.exit_code == 0
        assert f"Install commit : {commit}" in result.output
        assert f"commit {commit}" in result.output
        install.assert_called_once()
        assert install.call_args.args[0] == "main"
        assert install.call_args.args[1] == commit
        assert install.call_args.kwargs.get("reporter") is not None

    def test_version_install_prints_and_installs_resolved_commit(self):
        """Should print the resolved commit when installing a specific version."""
        from typer.testing import CliRunner
        from asc.cli import app

        commit = "b" * 40
        runner = CliRunner()
        with patch("asc.commands.update_cmd._all_versions_from_github", return_value=["0.1.5"]), \
                patch("asc.commands.update_cmd._resolve_git_ref_commit", return_value=commit), \
                patch("asc.commands.update_cmd._install_git_ref") as install:
            result = runner.invoke(app, ["update", "--version", "0.1.5"])

        assert result.exit_code == 0
        assert f"Install commit : {commit}" in result.output
        assert f"Done. asc updated to v0.1.5 (commit {commit})." in result.output
        install.assert_called_once()
        assert install.call_args.args[0] == "v0.1.5"
        assert install.call_args.args[1] == commit
        assert install.call_args.kwargs.get("reporter") is not None


class TestPipInstallStreaming:
    """Tests for pip command / progress parsing / streamed install."""

    def test_pip_install_cmd_has_progress_no_quiet(self):
        from asc.commands.update_cmd import _pip_install_cmd

        cmd = _pip_install_cmd("abc123")
        assert "--quiet" not in cmd
        assert "--progress-bar" in cmd
        assert "--force-reinstall" in cmd
        assert "--upgrade" in cmd
        assert "-u" in cmd
        assert "--no-deps" not in cmd
        assert cmd[-1].endswith("@abc123")

    def test_pip_install_cmd_no_deps(self):
        from asc.commands.update_cmd import _pip_install_cmd

        cmd = _pip_install_cmd("abc123", no_deps=True)
        assert "--no-deps" in cmd

    def test_pip_install_env_unbuffered(self):
        from asc.commands.update_cmd import _pip_install_env

        env = _pip_install_env()
        assert env["PYTHONUNBUFFERED"] == "1"

    def test_extract_pip_percent(self):
        from asc.commands.update_cmd import _extract_pip_percent

        assert _extract_pip_percent("Downloading foo (50%)") == 50
        assert _extract_pip_percent("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%") == 100
        assert _extract_pip_percent("no percent here") is None
        assert _extract_pip_percent("version 1.2.3%") is None  # guarded by lookbehind? 3% might match
        assert _extract_pip_percent("Collecting package") is None

    def test_install_git_ref_streams_output_and_progress(self):
        from unittest.mock import MagicMock, patch

        from asc.commands.update_cmd import _install_git_ref, _update_phase_plan
        from asc.reporting import TaskReporter

        class RecordingSink:
            def __init__(self):
                self.logs = []
                self.progress_events = []

            def on_log(self, message, *, level="info"):
                self.logs.append(message)

            def on_progress(self, *, pct, msg, phase, phase_label, phase_index, phase_total):
                self.progress_events.append({"pct": pct, "msg": msg, "phase": phase})

        sink = RecordingSink()
        reporter = TaskReporter(sinks=[sink])
        reporter.set_phases(_update_phase_plan())
        reporter.phase("download")

        lines = [
            "Collecting git+https://github.com/yinghuiwang/AppStoreTools.git@main\n",
            "  Cloning to /tmp/pip-req...\n",
            "  Downloading package (40%)\n",
            "  Downloading package (80%)\n",
            "Building wheels for collected packages: asc-appstore-tools\n",
            "Installing collected packages: asc-appstore-tools\n",
            "Successfully installed asc-appstore-tools-0.1.26\n",
        ]

        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0

        with patch("asc.commands.update_cmd.subprocess.Popen", return_value=mock_proc) as popen:
            _install_git_ref("main", "a" * 40, reporter=reporter)

        popen.assert_called_once()
        cmd = popen.call_args.args[0]
        assert "--quiet" not in cmd
        assert "--progress-bar" in cmd
        assert "-u" in cmd
        env = popen.call_args.kwargs.get("env") or {}
        assert env.get("PYTHONUNBUFFERED") == "1"
        joined = "\n".join(sink.logs)
        assert "Cloning" in joined
        assert "Successfully installed" in joined
        assert any(e["phase"] == "download" and e["pct"] > 0 for e in sink.progress_events)
        assert any(e["phase"] == "install" for e in sink.progress_events)
        assert sink.progress_events[-1]["pct"] == 100
        assert sink.progress_events[-1]["phase"] == "install"

    def test_update_core_defer_install_skips_pip(self):
        from unittest.mock import MagicMock, patch

        from asc.commands.update_cmd import _update_core
        from asc.reporting import TaskReporter

        class RecordingSink:
            def __init__(self):
                self.logs = []

            def on_log(self, message, *, level="info"):
                self.logs.append(message)

            def on_progress(self, **kwargs):
                pass

        sink = RecordingSink()
        reporter = TaskReporter(sinks=[sink])
        commit = "c" * 40
        with patch("asc.commands.update_cmd._resolve_git_ref_commit", return_value=commit), \
                patch("asc.commands.update_cmd._install_git_ref") as install:
            outcome = _update_core(
                branch="main",
                yes=True,
                reporter=reporter,
                defer_install=True,
            )

        install.assert_not_called()
        assert outcome.changed is True
        assert outcome.deferred is True
        assert outcome.install_ref == "main"
        assert outcome.commit == commit
        assert any("defer" in line.lower() for line in sink.logs)


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
