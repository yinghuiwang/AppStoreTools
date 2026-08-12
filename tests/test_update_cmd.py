"""Tests for update_cmd module."""

import subprocess
from unittest.mock import patch

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

    def test_pip_stream_uses_semantic_raw_policy_and_quarter_milestones(self):
        from unittest.mock import MagicMock

        from asc.commands.update_cmd import _install_git_ref, _update_phase_plan
        from asc.reporting import TaskReporter, web_policy_for

        class RecordingSink:
            def __init__(self):
                self.events = []
                self.progress_events = []

            def on_event(self, event):
                self.events.append(event)

            def on_progress(self, **event):
                self.progress_events.append(event)

        lines = [
            "Collecting package-a\n",
            "Using cached package_a.whl\n",
            "Requirement already satisfied: requests\n",
            "Downloading package-a (1%)\n",
            "Downloading package-a (25%)\n",
            "Downloading package-a (25%)\n",
            "Downloading package-a (10%)\n",
            "Downloading package-a (50%)\n",
            "Downloading package-a (75%)\n",
            "Installing collected packages: package-a\n",
            "Successfully installed package-a\n",
        ]
        proc = MagicMock()
        proc.stdout = iter(lines)
        proc.poll.return_value = 0
        proc.wait.return_value = 0
        sink = RecordingSink()
        reporter = TaskReporter(
            sinks=[sink],
            task_kind="update",
            policy_factory=web_policy_for,
        )
        reporter.set_phases(_update_phase_plan())
        reporter.phase("download")

        with patch("asc.commands.update_cmd.subprocess.Popen", return_value=proc):
            _install_git_ref("main", "a" * 40, reporter=reporter)

        milestones = [
            event.message
            for event in sink.events
            if event.event_type == "milestone"
        ]
        assert milestones == [
            "Downloading 0%",
            "Downloading 25%",
            "Downloading 50%",
            "Downloading 75%",
            "Installing 100%",
        ]
        summaries = [
            event.message for event in sink.events if event.event_type == "summary"
        ]
        assert any("Collecting 1" in message for message in summaries)
        assert any("Using cached 1" in message for message in summaries)
        assert any(
            "Requirement already satisfied 1" in message for message in summaries
        )
        assert not any(
            event.event_type == "operation"
            and event.message.startswith(("Collecting ", "Using cached "))
            for event in sink.events
        )
        progress_messages = [
            event["msg"] for event in sink.progress_events if event["msg"]
        ]
        assert "Downloading 1%" in progress_messages
        assert progress_messages.count("Downloading 25%") == 2
        assert "Downloading 10%" in progress_messages

    def test_pip_failure_keeps_error_traceback_context_and_last_twenty(self):
        from unittest.mock import MagicMock

        from asc.commands.update_cmd import _install_git_ref, _update_phase_plan
        from asc.reporting import TaskReporter, web_policy_for

        class RecordingSink:
            def __init__(self):
                self.events = []

            def on_event(self, event):
                self.events.append(event)

            def on_progress(self, **kwargs):
                pass

        lines = [f"noise-{index}\n" for index in range(30)]
        lines[10] = "ERROR: Could not build wheels\n"
        lines[11] = "Traceback (most recent call last):\n"
        proc = MagicMock()
        proc.stdout = iter(lines)
        proc.poll.return_value = 1
        proc.wait.return_value = 1
        sink = RecordingSink()
        reporter = TaskReporter(
            sinks=[sink],
            task_kind="update",
            policy_factory=web_policy_for,
        )
        reporter.set_phases(_update_phase_plan())
        reporter.phase("download")

        with patch("asc.commands.update_cmd.subprocess.Popen", return_value=proc):
            with pytest.raises(subprocess.CalledProcessError):
                _install_git_ref("main", reporter=reporter)

        assert any(
            event.message == "ERROR: Could not build wheels" for event in sink.events
        )
        assert any(
            event.message == "Traceback (most recent call last):"
            for event in sink.events
        )
        assert any(event.message == "noise-29" for event in sink.events)
        raw_ids = [
            (event.source, event.raw_line_no)
            for event in sink.events
            if event.raw_line_no is not None
        ]
        assert len(raw_ids) == len(set(raw_ids))

    def test_pip_progress_parser_failure_does_not_stop_output_consumption(self):
        from unittest.mock import MagicMock

        from asc.commands.update_cmd import _install_git_ref
        from asc.reporting import TaskReporter, web_policy_for

        class RecordingSink:
            def __init__(self):
                self.events = []

            def on_event(self, event):
                self.events.append(event)

            def on_progress(self, **kwargs):
                pass

        proc = MagicMock()
        proc.stdout = iter(["Downloading package-a (50%)\n", "ERROR: later line\n"])
        proc.poll.return_value = 0
        proc.wait.return_value = 0
        sink = RecordingSink()
        reporter = TaskReporter(
            sinks=[sink],
            task_kind="update",
            policy_factory=web_policy_for,
        )

        with patch("asc.commands.update_cmd.subprocess.Popen", return_value=proc), patch(
            "asc.commands.update_cmd._extract_pip_percent",
            side_effect=ValueError("bad progress"),
        ):
            _install_git_ref("main", reporter=reporter)

        assert any(event.message == "ERROR: later line" for event in sink.events)

    def test_pip_timeout_finishes_raw_callback_as_failed(self):
        from unittest.mock import MagicMock

        from asc.commands.update_cmd import _install_git_ref
        from asc.reporting import TaskReporter

        finished = []

        class Callback:
            def __call__(self, message):
                pass

            def set_phase(self, phase):
                pass

            def finish(self, *, failed):
                finished.append(failed)

        reporter = MagicMock(spec=TaskReporter)
        reporter.make_raw_log_callback.return_value = Callback()
        proc = MagicMock()
        proc.stdout = iter(())
        proc.wait.return_value = -9
        with patch("asc.commands.update_cmd.subprocess.Popen", return_value=proc):
            with pytest.raises(TimeoutError):
                _install_git_ref("main", reporter=reporter, timeout=0)

        assert finished == [True]

    def test_pip_wait_timeout_kills_process_finishes_callback_and_keeps_tail(self):
        from unittest.mock import MagicMock

        from asc.commands.update_cmd import _install_git_ref
        from asc.reporting import TaskReporter, web_policy_for

        class RecordingSink:
            def __init__(self):
                self.events = []

            def on_event(self, event):
                self.events.append(event)

            def on_progress(self, **kwargs):
                pass

        proc = MagicMock()
        proc.stdout = iter(f"tail-{index}\n" for index in range(25))
        proc.poll.return_value = None
        original = subprocess.TimeoutExpired(["pip"], 30)
        proc.wait.side_effect = [original, -9]
        sink = RecordingSink()
        reporter = TaskReporter(
            sinks=[sink],
            task_kind="update",
            policy_factory=web_policy_for,
        )

        with patch("asc.commands.update_cmd.subprocess.Popen", return_value=proc):
            with pytest.raises(subprocess.TimeoutExpired) as caught:
                _install_git_ref("main", reporter=reporter)

        assert caught.value is original
        proc.kill.assert_called_once()
        assert proc.wait.call_count == 2
        assert any(
            event.event_type == "context" and event.message == "tail-24"
            for event in sink.events
        )
        assert any(
            event.event_type == "summary" and "省略其他输出 5 行" in event.message
            for event in sink.events
        )

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
