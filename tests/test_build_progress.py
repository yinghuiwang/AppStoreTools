"""TaskReporter progress for build / deploy / release phases."""
from __future__ import annotations

import inspect
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from asc.commands.build import (
    UploadProgressReporter,
    _build_phase_plan,
    build_core,
    deploy_core,
)
from asc.commands.build_inputs import ResolvedInputs
from asc.reporting import TaskReporter


class RecordingSink:
    def __init__(self):
        self.logs = []
        self.progress_events = []

    def on_log(self, message, *, level="info"):
        self.logs.append((level, message))

    def on_progress(self, *, pct, msg, phase, phase_label, phase_index, phase_total):
        self.progress_events.append({
            "pct": pct,
            "msg": msg,
            "phase": phase,
            "phase_label": phase_label,
            "phase_index": phase_index,
            "phase_total": phase_total,
        })


class _FakeSpinner:
    returncode: int = 0
    stderr: str = ""
    last_on_log_line = None

    def __init__(self, label, *, log_path, verbose=False, tty=None, on_log_line=None):
        self.label = label
        self.log_path = log_path
        self.on_log_line = on_log_line
        _FakeSpinner.last_on_log_line = on_log_line

    def run(self, cmd, output_callback=None, cancel_event=None):
        Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
        text = self.__class__.stderr or ""
        Path(self.log_path).write_text(text)
        if output_callback and text:
            output_callback(text)
        if self.__class__.returncode != 0 and self.on_log_line and text:
            for line in text.splitlines()[-20:]:
                self.on_log_line(line)
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=self.__class__.returncode,
            stdout="",
            stderr=text,
        )


def _resolved(**overrides):
    base = dict(
        project_path="/tmp/x.xcodeproj",
        project_kind="project",
        scheme="X",
        bundle_id="com.x",
        signing="auto",
        certificate=None,
        profile=None,
        destination="appstore",
    )
    base.update(overrides)
    return ResolvedInputs(**base)


def test_upload_phase_maps_bytes_into_global_pct():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.set_phases([
        ("archive", 35, "归档"),
        ("export", 15, "导出"),
        ("upload", 50, "上传"),
    ])
    r.phase("archive"); r.progress(1, 1)
    r.phase("export"); r.progress(1, 1)
    r.phase("upload"); r.progress(50, 100, msg="50%")
    assert sink.progress_events[-1]["pct"] == 35 + 15 + 25


def test_build_phase_plan_modes():
    assert _build_phase_plan(mode="full") == [
        ("archive", 35, "归档"),
        ("export", 15, "导出"),
        ("upload", 50, "上传"),
    ]
    assert _build_phase_plan(mode="deploy") == [("upload", 100, "上传")]
    assert _build_phase_plan(mode="build") == [
        ("archive", 35, "归档"),
        ("export", 15, "导出"),
    ]


def test_build_only_renormalizes_archive_export():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.set_phases(_build_phase_plan(mode="build"))
    r.phase("archive")
    r.progress(1, 1)
    assert sink.progress_events[-1]["pct"] == 70
    r.phase("export")
    r.progress(1, 1)
    assert sink.progress_events[-1]["pct"] == 100


def test_upload_progress_reporter_feeds_task_reporter():
    sink = RecordingSink()
    task = TaskReporter(sinks=[sink], verbose=False)
    task.set_phases(_build_phase_plan(mode="deploy"))
    task.phase("upload")

    up = UploadProgressReporter(total_bytes=8 * 1024 * 1024, task_reporter=task)
    up.handle_output_line("Uploaded 4194304 of 8388608 bytes")

    assert sink.progress_events[-1]["pct"] == 50
    assert sink.progress_events[-1]["phase"] == "upload"
    joined = "\n".join(msg for _, msg in sink.logs)
    assert "4.0 MB" in joined


def test_build_core_reports_archive_export_phases(tmp_path, monkeypatch):
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    _FakeSpinner.returncode = 0
    _FakeSpinner.stderr = ""
    monkeypatch.setattr("asc.commands.build.Spinner", _FakeSpinner)
    monkeypatch.setattr(
        "asc.commands.build.detect_versions", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "asc.commands.build.run_xcodebuild_export",
        lambda *a, **k: str(tmp_path / "export" / "X.ipa"),
    )
    (tmp_path / "export").mkdir(parents=True)

    ipa = build_core(
        _resolved(),
        output=str(tmp_path),
        dry_run=False,
        reuse_archive=False,
        reporter=reporter,
    )

    assert ipa
    pcts = [e["pct"] for e in sink.progress_events]
    assert pcts == sorted(pcts)
    phases = [e["phase"] for e in sink.progress_events if e["phase"]]
    assert "archive" in phases
    assert "export" in phases
    assert sink.progress_events[-1]["pct"] == 100
    assert all(e["phase_index"] in (0, 1, 2) for e in sink.progress_events)


def test_deploy_core_reports_upload_phase(tmp_path, monkeypatch):
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    ipa = tmp_path / "App.ipa"
    ipa.write_bytes(b"x" * 1024)

    def fake_upload(*args, **kwargs):
        progress_reporter = kwargs.get("progress_reporter")
        assert progress_reporter is not None
        progress_reporter.handle_output_line("Uploading package: 50%")
        progress_reporter.handle_output_line("Uploading package: 100%")

    monkeypatch.setattr("asc.commands.build.upload_ipa", fake_upload)

    deploy_core(
        ipa_path=str(ipa),
        issuer_id="issuer",
        key_id="key",
        key_file="/tmp/k.p8",
        destination="testflight",
        dry_run=False,
        reporter=reporter,
    )

    pcts = [e["pct"] for e in sink.progress_events]
    assert pcts == sorted(pcts)
    assert sink.progress_events[-1]["pct"] == 100
    upload_events = [e for e in sink.progress_events if e["phase"] == "upload"]
    assert upload_events
    mid = [e for e in upload_events if e["msg"] == "50%"]
    assert mid
    assert mid[0]["pct"] == 50


def test_release_shared_reporter_phase_index_123(tmp_path, monkeypatch):
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    reporter.set_phases(_build_phase_plan(mode="full"))

    _FakeSpinner.returncode = 0
    _FakeSpinner.stderr = ""
    monkeypatch.setattr("asc.commands.build.Spinner", _FakeSpinner)
    monkeypatch.setattr(
        "asc.commands.build.detect_versions", lambda *a, **k: None
    )
    ipa_path = str(tmp_path / "export" / "X.ipa")
    (tmp_path / "export").mkdir(parents=True)
    Path(ipa_path).write_bytes(b"ipa")
    monkeypatch.setattr(
        "asc.commands.build.run_xcodebuild_export",
        lambda *a, **k: ipa_path,
    )

    def fake_upload(*args, **kwargs):
        pr = kwargs.get("progress_reporter")
        pr.handle_output_line("Uploaded 1 of 2 bytes")
        pr.handle_output_line("Uploaded 2 of 2 bytes")

    monkeypatch.setattr("asc.commands.build.upload_ipa", fake_upload)

    build_core(
        _resolved(),
        output=str(tmp_path),
        dry_run=False,
        reuse_archive=False,
        reporter=reporter,
        configure_phases=False,
    )
    deploy_core(
        ipa_path=ipa_path,
        issuer_id="issuer",
        key_id="key",
        key_file="/tmp/k.p8",
        destination="testflight",
        dry_run=False,
        reporter=reporter,
        configure_phases=False,
    )

    by_phase = {}
    for e in sink.progress_events:
        if e["phase"]:
            by_phase[e["phase"]] = e["phase_index"]
    assert by_phase.get("archive") == 1
    assert by_phase.get("export") == 2
    assert by_phase.get("upload") == 3
    pcts = [e["pct"] for e in sink.progress_events]
    assert pcts == sorted(pcts)
    assert sink.progress_events[-1]["pct"] == 100


def test_build_source_has_no_progress_protocol():
    root = Path(__file__).resolve().parents[1]
    src = (root / "src/asc/commands/build.py").read_text(encoding="utf-8")
    assert "[PROGRESS:" not in src


def test_build_web_starter_uses_start_background_task():
    from asc.web import routes_api

    starter = inspect.getsource(routes_api._start_build_task)
    assert "start_background_task" in starter
    assert "_PROGRESS_RE" not in starter
    assert "capture_stdout_to_queue" not in starter
    assert "reporter=" in starter
    assert "phase" in starter or "_build_phase_plan" in starter


def test_spinner_failure_tail_calls_on_log_line(tmp_path):
    from asc.progress import Spinner

    lines: list[str] = []
    log = tmp_path / "fail.log"
    sp = Spinner(
        "Fail bridge",
        log_path=str(log),
        verbose=False,
        tty=False,
        on_log_line=lines.append,
    )
    code = "import sys\n" + "\n".join(f"print('L{i}')" for i in range(5)) + "\nsys.exit(1)\n"
    result = sp.run([__import__("sys").executable, "-c", code])
    assert result.returncode == 1
    assert any("L4" in line for line in lines)
    assert len(lines) <= 20
