"""TaskReporter progress for build / deploy / release phases."""
from __future__ import annotations

import inspect
import os
import re
import shutil
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
from asc.reporting import TaskReporter, make_web_reporter
from asc.web.tasks import TaskStore


def _verification_document_shell_blocks():
    document = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "web-task-log-stability-verification.md"
    ).read_text(encoding="utf-8")
    return re.findall(r"```bash\n(.*?)```", document, flags=re.DOTALL)


def _write_executable(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_web_task_stability_document_shell_blocks_parse_with_zsh():
    zsh = shutil.which("zsh")
    if zsh is None:
        pytest.skip("zsh is required for deployment document syntax validation")
    blocks = _verification_document_shell_blocks()

    assert blocks
    for index, block in enumerate(blocks, start=1):
        result = subprocess.run(
            [zsh, "-n"],
            input=block,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"shell block {index} failed zsh -n:\n{result.stderr}"
        )


@pytest.mark.parametrize(
    ("mode", "expected_returncode"),
    [("success", 0), ("release-fail", 23), ("cmp-fail", 31)],
)
def test_raw_capture_block_preserves_failure_and_cleans_wrapper(
    tmp_path, mode, expected_returncode
):
    zsh = shutil.which("zsh")
    if zsh is None:
        pytest.skip("zsh is required for deployment document semantics")
    block = next(
        block
        for block in _verification_document_shell_blocks()
        if "WRAPPER_DIR=" in block and "ASC_ARCHIVE_CAPTURE" in block
    )
    stub_dir = tmp_path / "stubs"
    output_dir = tmp_path / "output"
    verify_dir = output_dir / "web-task-verification"
    temp_dir = tmp_path / "tmp"
    sentinel_dir = tmp_path / "sentinels"
    for directory in (stub_dir, output_dir, verify_dir, temp_dir, sentinel_dir):
        directory.mkdir(parents=True, exist_ok=True)

    real_xcodebuild = stub_dir / "real-xcodebuild"
    _write_executable(
        real_xcodebuild,
        """#!/bin/zsh
if [[ " $* " == *" -exportArchive "* ]]; then
  print -rn -- 'export-bytes\n'
else
  print -rn -- 'archive-bytes\n'
fi
""",
    )
    real_xcrun = stub_dir / "real-xcrun"
    _write_executable(
        real_xcrun,
        """#!/bin/zsh
print -rn -- 'upload-bytes\n'
""",
    )
    _write_executable(
        stub_dir / "asc",
        """#!/bin/zsh
set -eu
if [[ "$ASC_STUB_MODE" == 'release-fail' ]]; then
  exit 23
fi
print -r -- release > "$ASC_SENTINEL_DIR/release"
mkdir -p "$ASC_OUTPUT_DIR/export"
xcodebuild archive > "$ASC_OUTPUT_DIR/build.log" 2>&1
print -r -- archive > "$ASC_SENTINEL_DIR/archive"
xcodebuild -exportArchive > "$ASC_OUTPUT_DIR/export.log" 2>&1
print -r -- export > "$ASC_SENTINEL_DIR/export"
xcrun altool --upload-app > "$ASC_OUTPUT_DIR/export/upload.log" 2>&1
print -r -- upload > "$ASC_SENTINEL_DIR/upload"
""",
    )
    real_cmp = shutil.which("cmp")
    assert real_cmp is not None
    _write_executable(
        stub_dir / "cmp",
        """#!/bin/zsh
print -r -- cmp >> "$ASC_SENTINEL_DIR/cmp"
if [[ "$ASC_STUB_MODE" == 'cmp-fail' ]]; then
  exit 31
fi
exec "$REAL_CMP" "$@"
""",
    )
    environment = {
        **os.environ,
        "ASC_STUB_MODE": mode,
        "ASC_PROFILE": "stub-profile",
        "ASC_PROJECT": str(tmp_path / "Stub.xcodeproj"),
        "ASC_SCHEME": "Stub",
        "ASC_OUTPUT_DIR": str(output_dir),
        "ASC_VERIFY_DIR": str(verify_dir),
        "REAL_XCODEBUILD": str(real_xcodebuild),
        "REAL_XCRUN": str(real_xcrun),
        "REAL_CMP": real_cmp,
        "ASC_SENTINEL_DIR": str(sentinel_dir),
        "TMPDIR": str(temp_dir),
        "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
    }

    result = subprocess.run(
        [zsh],
        input=block,
        text=True,
        capture_output=True,
        env=environment,
    )

    assert result.returncode == expected_returncode, result.stderr
    assert not list(temp_dir.glob("asc-raw-wrapper.*"))
    if mode == "release-fail":
        assert not list(sentinel_dir.iterdir())
        assert not list(verify_dir.glob("*.capture.log"))
    else:
        assert {
            path.name for path in sentinel_dir.iterdir()
        } >= {"release", "archive", "export", "upload", "cmp"}
        assert (verify_dir / "archive.capture.log").read_bytes() == b"archive-bytes\n"
        assert (verify_dir / "export.capture.log").read_bytes() == b"export-bytes\n"
        assert (verify_dir / "upload.capture.log").read_bytes() == b"upload-bytes\n"
        cmp_calls = (sentinel_dir / "cmp").read_text(encoding="utf-8").splitlines()
        assert len(cmp_calls) == (1 if mode == "cmp-fail" else 3)


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


class RecordingTaskReporter(TaskReporter):
    def __init__(self):
        super().__init__(sinks=[], task_kind="build")
        self.raw_callbacks = []
        self.milestone_logs = []
        self.progress_updates = []

    def make_raw_log_callback(self, source, phase, raw_log_path=None):
        self.raw_callbacks.append((source, phase, Path(raw_log_path)))
        return lambda line: None

    def milestone(self, percent, *, message):
        self.milestone_logs.append((percent, message))

    def progress(self, current, total, msg=None):
        self.progress_updates.append((current, total, msg))


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
        if self.on_log_line and text:
            for line in text.splitlines():
                self.on_log_line(line)
        if output_callback and text:
            output_callback(text)
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
    assert sink.progress_events[-1]["msg"] == "50%"
    assert sink.logs == []


@pytest.mark.parametrize(
    ("percents", "expected"),
    [
        ([37], [0, 25]),
        ([24, 26], [0, 25]),
        ([74, 100], [0, 25, 50, 75, 100]),
        ([50, 25, 50, 75, 75], [0, 25, 50, 75]),
    ],
)
def test_upload_progress_logs_each_crossed_milestone_once(percents, expected):
    reporter = RecordingTaskReporter()
    upload = UploadProgressReporter(100, task_reporter=reporter)
    for percent in percents:
        upload.handle_output_line(f"Uploaded {percent} of 100 bytes")

    assert reporter.progress_updates == [
        (percent, 100, f"{percent}%") for percent in percents
    ]
    assert [value for value, _ in reporter.milestone_logs] == expected
    assert all(message for _, message in reporter.milestone_logs)


def test_build_callbacks_carry_exact_source_phase_and_raw_path(tmp_path, monkeypatch):
    reporter = RecordingTaskReporter()
    monkeypatch.setattr("asc.commands.build.detect_versions", lambda *a, **k: None)
    monkeypatch.setattr(
        "asc.commands.build.run_xcodebuild_archive",
        lambda *a, **k: a[4],
    )

    def fake_export(*args, **kwargs):
        ipa = Path(args[2]) / "X.ipa"
        ipa.write_bytes(b"ipa")
        return str(ipa)

    monkeypatch.setattr("asc.commands.build.run_xcodebuild_export", fake_export)

    build_core(
        _resolved(),
        output=str(tmp_path),
        reuse_archive=False,
        reporter=reporter,
    )

    assert ("xcodebuild", "archive", tmp_path / "build.log") in reporter.raw_callbacks
    assert ("xcodebuild", "export", tmp_path / "export.log") in reporter.raw_callbacks


def test_deploy_callback_uses_altool_upload_path(tmp_path, monkeypatch):
    reporter = RecordingTaskReporter()
    ipa = tmp_path / "App.ipa"
    ipa.write_bytes(b"ipa")
    monkeypatch.setattr("asc.commands.build.upload_ipa", lambda *a, **k: None)

    deploy_core(
        ipa_path=str(ipa),
        issuer_id="issuer",
        key_id="key",
        key_file="/tmp/k.p8",
        destination="testflight",
        dry_run=False,
        reporter=reporter,
    )

    assert ("altool", "upload", tmp_path / "upload.log") in reporter.raw_callbacks


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


def test_spinner_streams_lines_to_on_log_line_on_success(tmp_path):
    """Live tee should forward every non-empty line to on_log_line (Web TaskReporter)."""
    from asc.progress import Spinner

    lines: list[str] = []
    log = tmp_path / "ok.log"
    sp = Spinner(
        "Stream ok",
        log_path=str(log),
        verbose=False,
        tty=False,
        on_log_line=lines.append,
    )
    result = sp.run([__import__("sys").executable, "-c", "print('STREAM_LINE_A'); print('STREAM_LINE_B')"])
    assert result.returncode == 0
    assert any("STREAM_LINE_A" in line for line in lines)
    assert any("STREAM_LINE_B" in line for line in lines)
    assert any("完成" in line for line in lines)


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
    # All body lines streamed live; failure summary also forwarded (no duplicate tail).
    assert any("L4" in line for line in lines)
    assert any("L0" in line for line in lines)
    assert sum(1 for line in lines if line == "L4") == 1
    assert any("失败" in line for line in lines)
    assert any("完整日志" in line for line in lines)


def test_one_hundred_thousand_failed_build_lines_are_bounded_and_deduplicated(
    tmp_path,
):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build")
    reporter = make_web_reporter(store, task_id, "build")
    callback = reporter.make_raw_log_callback(
        "xcodebuild",
        "archive",
        tmp_path / "build.log",
    )
    input_count = 0

    def emit(line):
        nonlocal input_count
        callback(line)
        input_count += 1

    ordinary_count = 99_984
    try:
        for index in range(ordinary_count):
            emit(f"CompileSwift normal arm64 File{index}.swift")
        for index in range(1, 6):
            emit(f"context-before-{index}")
        emit("error: compiler stopped")
        for index in range(1, 5):
            emit(f"context-after-{index}")
        emit("warning: signing is deprecated")
        for index in range(6, 11):
            emit(f"context-after-{index}")
        callback.finish(failed=True)
        reporter.flush()
        store.flush()

        logs = store.get_logs_after(task_id)
        messages = [item["message"] for item in logs]
        assert input_count == 100_000
        assert len(logs) <= 500
        assert any("CompileSwift 99980" in message for message in messages)
        assert any(
            "error 1 行" in message
            and "warning 1 行" in message
            and "context 18 行" in message
            for message in messages
        )
        expected_window = {
            *(f"context-before-{index}" for index in range(1, 6)),
            "error: compiler stopped",
            *(f"context-after-{index}" for index in range(1, 5)),
            "warning: signing is deprecated",
            *(f"context-after-{index}" for index in range(6, 11)),
        }
        for message in expected_window:
            assert messages.count(message) == 1
        failure_tail_only = {
            f"CompileSwift normal arm64 File{index}.swift"
            for index in range(99_980, 99_984)
        }
        for message in failure_tail_only:
            assert messages.count(message) == 1
        assert messages.count("context-after-10") == 1
        assert "CompileSwift normal arm64 File99979.swift" not in messages
    finally:
        store.close()
