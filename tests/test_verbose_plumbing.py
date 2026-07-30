"""Verbose flag plumbing: CLI → make_cli_reporter, Web → start_background_task."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from asc.reporting import TaskReporter, make_web_reporter
from asc.web.task_runner import start_background_task
from asc.web.tasks import TaskStatus, TaskStore


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from asc.web.server import create_app

    return TestClient(create_app())


def test_cmd_metadata_passes_verbose_flag(monkeypatch, tmp_path):
    """asc metadata --verbose flows into _upload_metadata_core(verbose=True)."""
    captured = {}
    csv_file = tmp_path / "appstore_info.csv"
    csv_file.write_text("locale,name\nEnglish(en-US),Demo\n", encoding="utf-8")

    class FakeConfig:
        app_id = "app-1"
        app_name = "test-app"
        key_id = "key"
        issuer_id = "issuer"

        def __init__(self, *args, **kwargs):
            self.csv_path = str(csv_file)

    def fake_core(*args, **kwargs):
        captured["verbose"] = kwargs.get("verbose")

    monkeypatch.setattr("asc.commands.metadata.Config", FakeConfig)
    monkeypatch.setattr(
        "asc.commands.metadata.resolve_app_profile", lambda app, config: "test-app"
    )
    monkeypatch.setattr(
        "asc.commands.metadata.Guard",
        lambda: MagicMock(is_enabled=MagicMock(return_value=False)),
    )
    monkeypatch.setattr(
        "asc.commands.metadata.make_api_from_config",
        lambda config: (MagicMock(), "app-1"),
    )
    monkeypatch.setattr("asc.commands.metadata._upload_metadata_core", fake_core)

    from asc.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app, ["metadata", "--verbose", "--app", "test-app", "--csv", str(csv_file)]
    )
    assert result.exit_code == 0, result.output
    assert captured["verbose"] is True


def test_metadata_run_api_passes_verbose_flag(client):
    """POST /api/metadata/run with verbose=on reaches _start_metadata_task."""
    with patch("asc.web.routes_api._start_metadata_task") as mock_start:
        mock_start.return_value = "verbose-task-id"
        resp = client.post(
            "/api/metadata/run",
            cookies={"asc_profile": "myapp"},
            data={
                "csv_path": "data/appstore_info.csv",
                "screenshots_dir": "data/screenshots",
                "include_metadata": "on",
                "verbose": "on",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["task_id"] == "verbose-task-id"
        mock_start.assert_called_once()
        assert mock_start.call_args.kwargs["verbose"] is True


def test_start_background_task_persists_debug_only_when_verbose(tmp_path):
    """YAGNI: debug lines reach TaskStore only when verbose=True."""
    store = TaskStore(tmp_path / "tasks.db")

    def run_quiet(reporter: TaskReporter, cancel_event):
        reporter.log("info-line")
        reporter.debug("debug-line")
        return {"ok": True}

    quiet_id = start_background_task(
        store, kind="urls", profile="demo", verbose=False, run=run_quiet
    )
    deadline = time.time() + 2
    while store.get(quiet_id)["status"] not in {
        TaskStatus.DONE,
        TaskStatus.ERROR,
    } and time.time() < deadline:
        time.sleep(0.01)

    quiet_logs = "\n".join(store.get(quiet_id).get("logs") or [])
    assert "info-line" in quiet_logs
    assert "debug-line" not in quiet_logs

    def run_verbose(reporter: TaskReporter, cancel_event):
        reporter.debug("debug-only")
        return {"ok": True}

    verbose_id = start_background_task(
        store, kind="urls", profile="demo", verbose=True, run=run_verbose
    )
    deadline = time.time() + 2
    while store.get(verbose_id)["status"] not in {
        TaskStatus.DONE,
        TaskStatus.ERROR,
    } and time.time() < deadline:
        time.sleep(0.01)

    verbose_logs = "\n".join(store.get(verbose_id).get("logs") or [])
    assert "debug-only" in verbose_logs


def test_make_web_reporter_debug_gated_by_verbose():
    store = MagicMock()
    quiet = make_web_reporter(store, "t1", verbose=False)
    quiet.debug("hidden")
    store.append_log.assert_not_called()

    noisy = make_web_reporter(store, "t2", verbose=True)
    noisy.debug("shown")
    store.append_log.assert_called_once_with("t2", "shown")
