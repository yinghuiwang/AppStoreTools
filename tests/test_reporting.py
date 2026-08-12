import subprocess
import sys
import threading
from pathlib import Path

import pytest

from asc.progress import ProcessCanceled, Spinner
from asc.reporting import (
    CliSink,
    TaskReporter,
    make_cli_reporter,
    make_web_reporter,
)


class RecordingSink:
    def __init__(self):
        self.logs = []
        self.events = []
        self.progress_events = []

    def on_log(self, message, *, level="info"):
        self.logs.append((level, message))

    def on_event(self, event):
        self.events.append(event)
        self.on_log(event.message, level=event.level)

    def on_progress(self, *, pct, msg, phase, phase_label, phase_index, phase_total):
        self.progress_events.append({
            "pct": pct,
            "msg": msg,
            "phase": phase,
            "phase_label": phase_label,
            "phase_index": phase_index,
            "phase_total": phase_total,
        })


class MockTaskStore:
    def __init__(self):
        self.logs = []
        self.log_batches = []
        self.progress_calls = []

    def append_log(self, task_id, line):
        self.logs.append((task_id, line))

    def append_logs(self, task_id, lines):
        self.log_batches.append((task_id, list(lines)))
        self.logs.extend((task_id, line) for line in lines)

    def set_progress(
        self,
        task_id,
        pct,
        msg,
        *,
        phase="",
        phase_label="",
        phase_index=0,
        phase_total=0,
    ):
        self.progress_calls.append({
            "task_id": task_id,
            "pct": pct,
            "msg": msg,
            "phase": phase,
            "phase_label": phase_label,
            "phase_index": phase_index,
            "phase_total": phase_total,
        })


def recording_web_reporter(*, task_kind):
    sink = RecordingSink()
    reporter = TaskReporter(
        sinks=[sink],
        task_kind=task_kind,
        policy_factory=lambda kind, source, raw_log_path=None: (
            __import__("asc.reporting", fromlist=["web_policy_for"]).web_policy_for(
                kind, source, raw_log_path
            )
        ),
    )
    return reporter, sink


@pytest.mark.parametrize(
    ("returncode", "cancel", "terminal_prefix"),
    [
        (0, False, "✅"),
        (1, False, "❌"),
        (0, True, "⏹"),
    ],
)
def test_spinner_flushes_callback_after_terminal_message(
    tmp_path, returncode, cancel, terminal_prefix
):
    events = []

    class RecordingCallback:
        def __call__(self, message):
            events.append(("log", message))

        def flush(self):
            events.append(("flush", None))

    callback = RecordingCallback()
    cancel_event = threading.Event() if cancel else None
    if cancel_event is not None:
        cancel_event.set()
    command = (
        [sys.executable, "-c", "import time; print('raw'); time.sleep(10)"]
        if cancel
        else [sys.executable, "-c", f"print('raw'); raise SystemExit({returncode})"]
    )
    spinner = Spinner(
        "测试",
        log_path=tmp_path / "subprocess.log",
        tty=False,
        on_log_line=callback,
    )

    if cancel:
        with pytest.raises(ProcessCanceled):
            spinner.run(command, cancel_event=cancel_event)
    else:
        result = spinner.run(command)
        assert isinstance(result, subprocess.CompletedProcess)
        assert result.returncode == returncode

    assert events[-1] == ("flush", None)
    assert any(
        kind == "log" and message.startswith(terminal_prefix)
        for kind, message in events[:-1]
    )


def test_spinner_tees_exact_binary_bytes_and_decodes_safe_text_lines(
    tmp_path, monkeypatch
):
    raw_bytes = b"first\r\nbad:\xff\nutf8:" + "中".encode() + b"\ntail"
    script = (
        "import os,sys;"
        f"os.write(sys.stdout.fileno(), {raw_bytes!r})"
    )
    raw_lines = []
    application_lines = []
    finished = []

    class RecordingCallback:
        def __call__(self, line):
            raw_lines.append(line)

        def application(self, message, *, level="info"):
            application_lines.append((level, message))

        def finish(self, *, failed):
            finished.append(failed)

    monkeypatch.setattr("asc.progress.READ_CHUNK_SIZE", 1)
    log_path = tmp_path / "build.log"
    result = Spinner(
        "archive",
        log_path=log_path,
        tty=False,
        on_log_line=RecordingCallback(),
    ).run([sys.executable, "-c", script])

    assert result.returncode == 0
    assert log_path.read_bytes() == raw_bytes
    assert raw_lines == ["first", "bad:�", "utf8:中", "tail"]
    assert application_lines[0][1].startswith("✅")
    assert finished == [False]


def test_spinner_retries_short_raw_writes_without_duplicate_callbacks(
    tmp_path, monkeypatch
):
    import asc.progress as progress_module

    raw_bytes = b"first\nsecond\nthird\n"
    script = (
        "import os,sys;"
        f"os.write(sys.stdout.fileno(), {raw_bytes!r})"
    )
    log_path = tmp_path / "build.log"
    raw_lines = []
    finished = []
    wrappers = []
    real_open = open

    class ShortWriteFile:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.write_calls = 0

        def write(self, data):
            self.write_calls += 1
            limit = min(len(data), (self.write_calls % 3) + 1)
            return self.wrapped.write(memoryview(data)[:limit])

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

    def short_open(path, mode, *args, **kwargs):
        wrapped = real_open(path, mode, *args, **kwargs)
        if Path(path) == log_path and mode == "wb":
            partial = ShortWriteFile(wrapped)
            wrappers.append(partial)
            return partial
        return wrapped

    class RecordingCallback:
        def __call__(self, message):
            raw_lines.append(message)

        def application(self, message, *, level="info"):
            pass

        def finish(self, *, failed):
            finished.append(failed)

    monkeypatch.setattr(progress_module, "open", short_open, raising=False)
    result = Spinner(
        "archive",
        log_path=log_path,
        tty=False,
        on_log_line=RecordingCallback(),
    ).run([sys.executable, "-c", script])

    assert result.returncode == 0
    assert wrappers[0].write_calls > 1
    assert log_path.read_bytes() == raw_bytes
    assert raw_lines == ["first", "second", "third"]
    assert finished == [False]


def test_spinner_zero_byte_raw_write_raises_and_finishes_failed(
    tmp_path, monkeypatch
):
    import asc.progress as progress_module

    raw_bytes = b"never-truncate\n"
    script = (
        "import os,sys;"
        f"os.write(sys.stdout.fileno(), {raw_bytes!r})"
    )
    log_path = tmp_path / "build.log"
    finished = []
    real_open = open

    class ZeroWriteFile:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def write(self, data):
            return 0

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

    def zero_open(path, mode, *args, **kwargs):
        wrapped = real_open(path, mode, *args, **kwargs)
        if Path(path) == log_path and mode == "wb":
            return ZeroWriteFile(wrapped)
        return wrapped

    class RecordingCallback:
        def __call__(self, message):
            pass

        def finish(self, *, failed):
            finished.append(failed)

    monkeypatch.setattr(progress_module, "open", zero_open, raising=False)

    with pytest.raises(OSError, match="raw log write made no progress"):
        Spinner(
            "archive",
            log_path=log_path,
            tty=False,
            on_log_line=RecordingCallback(),
        ).run([sys.executable, "-c", script])

    assert log_path.read_bytes() == b""
    assert finished == [True]


def test_spinner_classifier_failure_does_not_change_raw_bytes(tmp_path):
    raw_bytes = b"first\nsecond\nwarning: keep\n"
    script = (
        "import os,sys;"
        f"os.write(sys.stdout.fileno(), {raw_bytes!r})"
    )
    seen = []

    def broken_callback(line):
        seen.append(line)
        raise RuntimeError("classifier broke")

    log_path = tmp_path / "build.log"
    result = Spinner(
        "archive",
        log_path=log_path,
        tty=False,
        on_log_line=broken_callback,
    ).run([sys.executable, "-c", script])

    assert result.returncode == 0
    assert log_path.read_bytes() == raw_bytes
    assert seen


@pytest.mark.parametrize(
    ("returncode", "cancel", "failed"),
    [(0, False, False), (1, False, True), (0, True, True)],
)
def test_spinner_finishes_raw_callback_with_terminal_status(
    tmp_path, returncode, cancel, failed
):
    events = []

    class SemanticCallback:
        def __call__(self, message):
            events.append(("raw", message))

        def application(self, message, *, level="info"):
            events.append(("application", level, message))

        def finish(self, *, failed):
            events.append(("finish", failed))

    cancel_event = threading.Event() if cancel else None
    if cancel_event is not None:
        cancel_event.set()
    command = (
        [sys.executable, "-c", "import time; print('raw'); time.sleep(10)"]
        if cancel
        else [sys.executable, "-c", f"print('raw'); raise SystemExit({returncode})"]
    )
    spinner = Spinner(
        "测试",
        log_path=tmp_path / "semantic.log",
        tty=False,
        on_log_line=SemanticCallback(),
    )

    if cancel:
        with pytest.raises(ProcessCanceled):
            spinner.run(command, cancel_event=cancel_event)
    else:
        spinner.run(command)

    assert events[-1] == ("finish", failed)
    terminal = [event for event in events if event[0] == "application"]
    assert terminal
    assert not any(
        event[0] == "raw" and event[1].startswith(("✅", "❌", "⏹", "   完整日志"))
        for event in events
    )


def test_spinner_popen_failure_still_finishes_callback(tmp_path, monkeypatch):
    finished = []

    class RecordingCallback:
        def __call__(self, message):
            pass

        def finish(self, *, failed):
            finished.append(failed)

    def fail_popen(*args, **kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr("asc.progress.subprocess.Popen", fail_popen)

    with pytest.raises(OSError, match="spawn failed"):
        Spinner(
            "archive",
            log_path=tmp_path / "build.log",
            tty=False,
            on_log_line=RecordingCallback(),
        ).run(["xcodebuild"])

    assert finished == [True]


def test_spinner_output_callback_failure_isolated_after_binary_tee(
    tmp_path, caplog
):
    raw_bytes = b"first\nsecond\n"
    script = (
        "import os,sys;"
        f"os.write(sys.stdout.fileno(), {raw_bytes!r})"
    )
    raw_lines = []
    finished = []

    class RecordingCallback:
        def __call__(self, message):
            raw_lines.append(message)

        def finish(self, *, failed):
            finished.append(failed)

    def broken_output_callback(line):
        raise RuntimeError("progress parser broke")

    log_path = tmp_path / "upload.log"
    result = Spinner(
        "upload",
        log_path=log_path,
        tty=False,
        on_log_line=RecordingCallback(),
    ).run(
        [sys.executable, "-c", script],
        output_callback=broken_output_callback,
    )

    assert result.returncode == 0
    assert log_path.read_bytes() == raw_bytes
    assert raw_lines[:2] == ["first", "second"]
    assert finished == [False]
    assert "progress parser broke" in caplog.text


def test_operation_events_default_to_preserved_business_logs():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-1", "metadata")
    reporter.log("  ✅ en-US: 已更新")
    reporter.log("  ❌ ja: 上传失败", level="error")
    reporter.flush()
    lines = [line for _, batch in store.log_batches for line in batch]
    assert lines == ["  ✅ en-US: 已更新", "  ❌ ja: 上传失败"]


def test_build_regex_is_not_applied_to_ordinary_task_kinds():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-1", "iap")
    reporter.log("product CompileSwift-Pro created")
    reporter.flush()
    assert ("task-1", "product CompileSwift-Pro created") in store.logs


def test_cli_reporter_has_no_web_raw_policy(capsys):
    reporter = make_cli_reporter()
    callback = reporter.make_raw_log_callback("pip", "download")
    callback("Collecting package")
    assert "Collecting package" in capsys.readouterr().out


def test_cli_phase_event_does_not_add_output(capsys):
    reporter = make_cli_reporter()
    reporter.phase("archive")
    assert capsys.readouterr().out == "[0%] archive\n"


def test_raw_warning_keeps_first_and_summarizes_duplicates():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive", "build.log")
    callback("warning: Signing setting A")
    callback("\x1b[33mWARNING:   Signing setting A\x1b[0m")
    callback.finish(failed=False)
    messages = [message for _, message in sink.logs]
    matching = [event for event in sink.events if "Signing setting A" in event.message]
    assert sum("Signing setting A" in message for message in messages) == 2
    assert [event.event_type for event in matching] == ["warning", "summary"]
    assert any("重复 1 次" in message for message in messages)


def test_raw_warning_overflow_is_capped_per_phase():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive", "build.log")
    for index in range(55):
        callback(f"warning: distinct-{index}.swift")
    callback.finish(failed=False)
    messages = [message for _, message in sink.logs]
    assert len([m for m in messages if "warning: distinct-" in m]) == 50
    assert any("其他 warning：5 行" in m for m in messages)


def test_warning_limit_remains_per_phase_across_spinner_flushes():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    for index in range(40):
        callback(f"warning: first-{index}")
    callback.flush()
    for index in range(20):
        callback(f"warning: second-{index}")
    callback.flush()
    warnings = [event for event in sink.events if event.event_type == "warning"]
    assert len(warnings) == 50
    assert any(
        event.event_type == "summary" and "其他 warning：10 行" in event.message
        for event in sink.events
    )


def test_business_warning_limit_does_not_apply_to_application_logs():
    reporter, sink = recording_web_reporter(task_kind="iap")
    for index in range(55):
        reporter.log(f"warning: product-id-{index}")
    reporter.flush()
    assert len([message for _, message in sink.logs if "product-id-" in message]) == 55


def test_error_captures_five_before_ten_after_and_failure_tail_without_duplicates():
    reporter, sink = recording_web_reporter(task_kind="update")
    callback = reporter.make_raw_log_callback("pip", "install")
    for index in range(30):
        callback(f"line-{index}")
        if index == 10:
            callback("ERROR: wheel build failed")
    callback.finish(failed=True)
    raw_events = [event for event in sink.events if event.raw_line_no is not None]
    raw_lines = {(event.source, event.raw_line_no) for event in raw_events}
    assert len(raw_lines) == len(raw_events)
    assert any(event.event_type == "error" for event in sink.events)
    assert any(event.message == "line-6" for event in sink.events)
    assert not any(event.message == "line-5" for event in sink.events)
    assert any(event.message == "line-20" for event in sink.events)
    assert any(event.message == "line-29" for event in sink.events)


def test_generic_infrastructure_failure_keeps_bounded_diagnostic_context():
    reporter, sink = recording_web_reporter(task_kind="metadata")
    callback = reporter.make_raw_log_callback("web-infrastructure", "poll")
    for index in range(30):
        callback(f"poll endpoint=/v1/apps asset=asset-{index} status=WAITING")
        if index == 10:
            callback("error: polling transport failed")
    callback.finish(failed=True)

    assert any(
        event.event_type == "error"
        and event.message == "error: polling transport failed"
        for event in sink.events
    )
    contexts = {
        event.message
        for event in sink.events
        if event.event_type == "context"
    }
    assert "poll endpoint=/v1/apps asset=asset-6 status=WAITING" in contexts
    assert "poll endpoint=/v1/apps asset=asset-20 status=WAITING" in contexts
    assert "poll endpoint=/v1/apps asset=asset-29 status=WAITING" in contexts


def test_generic_error_warning_and_application_events_passthrough():
    reporter, sink = recording_web_reporter(task_kind="metadata")
    callback = reporter.make_raw_log_callback("web-infrastructure", "poll")

    callback("warning: polling is slow")
    callback("error: polling failed")
    callback.application("✅ locale=en-US updated")
    callback.finish(failed=True)

    messages = [event.message for event in sink.events]
    assert "warning: polling is slow" in messages
    assert "error: polling failed" in messages
    assert "✅ locale=en-US updated" in messages


@pytest.mark.parametrize(
    "diagnostic",
    [
        "\x1b[31merror: polling transport stopped\x1b[0m",
        "\x1b[31mRuntimeError: polling transport stopped\x1b[0m",
    ],
)
def test_generic_ansi_error_preserves_diagnostic_context(diagnostic):
    reporter, sink = recording_web_reporter(task_kind="metadata")
    callback = reporter.make_raw_log_callback("web-infrastructure", "poll")
    for index in range(30):
        callback(f"poll endpoint=/v1/apps asset=asset-{index} status=WAITING")
        if index == 10:
            callback(diagnostic)
    callback.finish(failed=True)

    error = next(
        event
        for event in sink.events
        if event.event_type == "error"
    )
    assert error.message == diagnostic
    contexts = {
        event.message
        for event in sink.events
        if event.event_type == "context"
    }
    assert "poll endpoint=/v1/apps asset=asset-6 status=WAITING" in contexts
    assert "poll endpoint=/v1/apps asset=asset-20 status=WAITING" in contexts
    assert "poll endpoint=/v1/apps asset=asset-29 status=WAITING" in contexts


def test_generic_phase_overflow_is_isolated_and_finish_is_idempotent():
    reporter, sink = recording_web_reporter(task_kind="metadata")
    callback = reporter.make_raw_log_callback("web-infrastructure", "phase-a")
    for index in range(260):
        callback(f"poll endpoint=/v1/apps asset=a-{index} status=WAITING")
    callback.set_phase("phase-b")
    for index in range(260):
        callback(f"poll endpoint=/v1/apps asset=b-{index} status=WAITING")
    callback.finish(failed=False)

    overflow = [
        event
        for event in sink.events
        if "overflow" in event.message.lower()
    ]
    assert [(event.phase, event.message) for event in overflow] == [
        (
            "phase-a",
            "generic infrastructure overflow: 4 high-cardinality lines omitted",
        ),
        (
            "phase-b",
            "generic infrastructure overflow: 4 high-cardinality lines omitted",
        ),
    ]
    event_count = len(sink.events)
    callback.finish(failed=False)
    assert len(sink.events) == event_count
    assert callback._policy._phase_order == []
    assert callback._policy._overflow_count == 0


def test_generic_policy_normalizes_ansi_before_grouping():
    reporter, sink = recording_web_reporter(task_kind="metadata")
    callback = reporter.make_raw_log_callback("web-infrastructure", "locales")

    colored_endpoint = (
        "HTTP retry endpoint=\x1b[36m/v1/localizations\x1b[0m locale=en-US status=429"
    )
    colored_identity = (
        "HTTP retry endpoint=/v1/localizations locale=\x1b[33men-US\x1b[0m status=429"
    )
    callback(colored_endpoint)
    callback(colored_identity)
    callback.finish(failed=False)

    summaries = [event for event in sink.events if event.event_type == "summary"]
    assert len(summaries) == 1
    assert "重复 1 次" in summaries[0].message
    assert summaries[0].message.startswith(colored_endpoint)


@pytest.mark.parametrize(
    ("task_kind", "source", "first_phase", "second_phase", "first_label", "second_label"),
    [
        ("build", "xcodebuild", "archive", "export", "归档摘要", "导出摘要"),
        ("update", "pip", "download", "install", "下载摘要", "安装摘要"),
    ],
)
def test_raw_context_failure_tail_does_not_cross_phase_boundary(
    task_kind, source, first_phase, second_phase, first_label, second_label
):
    reporter, sink = recording_web_reporter(task_kind=task_kind)
    callback = reporter.make_raw_log_callback(source, first_phase)

    for index in range(3):
        callback(f"{first_phase}-line-{index}")
    callback.set_phase(second_phase)
    callback(f"{second_phase}-line-0")
    reporter.fail(f"{second_phase} failed")
    reporter.flush()

    contexts = [event for event in sink.events if event.event_type == "context"]
    assert contexts
    assert all(event.phase == second_phase for event in contexts)
    assert not any(first_phase in event.message for event in contexts)
    summaries = [
        event.message for event in sink.events if event.event_type == "summary"
    ]
    assert any(first_label in message for message in summaries)
    assert any(second_label in message for message in summaries)


def test_raw_context_same_phase_flush_keeps_failure_tail(tmp_path):
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")

    for index in range(3):
        callback(f"archive-{index}")
    callback.flush()  # Spinner finally within the same phase
    reporter.fail("archive failed")
    reporter.flush()

    contexts = [event.message for event in sink.events if event.event_type == "context"]
    assert "archive-2" in contexts


def test_generic_error_context_does_not_cross_phase_boundary():
    reporter, sink = recording_web_reporter(task_kind="metadata")
    callback = reporter.make_raw_log_callback("web-infrastructure", "phase-a")
    for index in range(3):
        callback(f"poll endpoint=/v1/apps asset=a-{index} status=WAITING")
    callback.set_phase("phase-b")
    callback("error: phase-b failed")
    callback.finish(failed=True)

    contexts = [
        event
        for event in sink.events
        if event.event_type == "context"
    ]
    assert all(event.phase == "phase-b" for event in contexts)


@pytest.mark.parametrize(
    "diagnostic",
    [
        "\x1b[31merror: signing failed\x1b[0m",
        "\x1b[31mRuntimeError: boom\x1b[0m",
        "\x1b[31mTraceback (most recent call last):\x1b[0m",
    ],
)
def test_ansi_colored_errors_are_classified_without_changing_message(diagnostic):
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    callback(diagnostic)
    error = next(event for event in sink.events if event.event_type == "error")
    assert error.message == diagnostic


def test_duplicate_warnings_in_error_after_window_remain_visible_context():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    callback("warning: repeated")
    callback("error: compiler stopped")
    for _ in range(10):
        callback("warning: repeated")
    callback.finish(failed=False)
    after = [
        event
        for event in sink.events
        if event.message == "warning: repeated" and event.event_type == "context"
    ]
    assert len(after) == 10
    assert any("warning 11 行，context 10 行" in event.message for event in sink.events)


def test_overflow_warnings_in_error_after_window_remain_visible_context():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    for index in range(50):
        callback(f"warning: seed-{index}")
    callback("error: compiler stopped")
    for index in range(50, 60):
        callback(f"warning: seed-{index}")
    callback.finish(failed=False)
    visible_overflow = [
        event
        for event in sink.events
        if event.event_type == "context" and "warning: seed-" in event.message
    ]
    assert len(visible_overflow) == 10
    assert any("其他 warning：10 行" in event.message for event in sink.events)


def test_spinner_flush_does_not_prevent_failure_tail_at_reporter_finish():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    for index in range(30):
        callback(f"archive-{index}")
    callback.flush()  # Spinner finally
    reporter.fail("archive failed")
    reporter.flush()
    assert any(event.message == "archive-10" for event in sink.events)
    assert any(event.message == "archive-29" for event in sink.events)
    assert any(
        event.event_type == "summary" and "归档摘要" in event.message
        for event in sink.events
    )


def test_spinner_failure_tail_contains_only_last_twenty_subprocess_lines(tmp_path):
    reporter, sink = recording_web_reporter(task_kind="build")
    log_path = tmp_path / "build.log"
    callback = reporter.make_raw_log_callback(
        "xcodebuild",
        "archive",
        log_path,
    )
    script = (
        "import sys;"
        "[print(f'raw-{index}') for index in range(25)];"
        "raise SystemExit(1)"
    )

    result = Spinner(
        "构建 Archive",
        log_path=log_path,
        tty=False,
        on_log_line=callback,
    ).run([sys.executable, "-c", script])

    assert result.returncode == 1
    context = [
        event.message
        for event in sink.events
        if event.event_type == "context" and event.raw_line_no is not None
    ]
    assert context == [f"raw-{index}" for index in range(5, 25)]
    terminal = [
        event
        for event in sink.events
        if event.raw_line_no is None
        and ("失败" in event.message or "完整日志" in event.message)
    ]
    assert terminal[0].message.startswith("❌ 构建 Archive 失败 (")
    assert terminal[1].message == f"   完整日志: {log_path}"


def test_same_callback_emits_archive_and_export_summaries_after_spinner_flushes():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    callback("archive raw")
    callback.flush()
    callback.set_phase("export")
    callback("export raw")
    callback.flush()
    summaries = [
        event.message for event in sink.events if event.event_type == "summary"
    ]
    assert any("归档摘要" in message for message in summaries)
    assert any("导出摘要" in message for message in summaries)


def test_intermediate_reporter_flush_does_not_disable_later_phase():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    callback("archive raw")
    reporter.flush()
    callback.set_phase("export")
    callback("warning: export remains active")
    reporter.flush()
    assert any(
        event.event_type == "warning" and "export remains active" in event.message
        for event in sink.events
    )
    assert any(
        event.event_type == "summary" and "导出摘要" in event.message
        for event in sink.events
    )


def test_reentering_flushed_phase_clears_context_and_emits_new_summary():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    callback("old context")
    callback.flush()
    callback.set_phase("export")
    callback("export raw")
    callback.set_phase("archive")
    callback("error: new archive failure")
    callback.flush()
    error_index = next(
        index
        for index, event in enumerate(sink.events)
        if event.message == "error: new archive failure"
    )
    nearby = sink.events[max(0, error_index - 5) : error_index]
    assert all(event.message != "old context" for event in nearby)
    assert sum(
        event.event_type == "summary" and "归档摘要" in event.message
        for event in sink.events
    ) == 2


def test_failed_tail_keeps_warning_totals_and_adds_visible_context():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    callback("warning: duplicate")
    callback("warning: duplicate")
    callback.finish(failed=True)
    summaries = [
        event.message for event in sink.events if "归档摘要" in event.message
    ]
    assert summaries == [
        "归档摘要：warning 2 行，context 1 行。"
    ]


def test_raw_policy_state_is_bounded_after_one_hundred_thousand_plain_lines():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    for index in range(100_000):
        callback(f"raw-{index}")
    callback.flush()
    policy = callback._policy
    assert len(policy._emitted_raw_ids) <= 64
    assert len(policy._emitted_raw_order) <= 64
    assert len(policy._unclassified_ids) <= 25
    assert len(policy._before) <= 5
    assert len(policy._tail) <= 20
    assert not hasattr(policy, "_raw_categories")
    assert any(
        "省略其他输出 100000 行" in event.message
        for event in sink.events
        if event.event_type == "summary"
    )


def test_xcodebuild_100k_lines_stay_below_500_persisted_events(tmp_path):
    store = MockTaskStore()
    reporter = make_web_reporter(store, "build-1", "build")
    callback = reporter.make_raw_log_callback(
        "xcodebuild",
        "archive",
        tmp_path / "build.log",
    )
    for index in range(100_000):
        callback(f"CompileSwift normal arm64 File{index}.swift")
    callback.finish(failed=False)
    reporter.flush()

    lines = [line for _, batch in store.log_batches for line in batch]
    assert len(lines) <= 500
    assert not any("File99999.swift" in line for line in lines)
    assert any("CompileSwift 100000" in line for line in lines)


def test_xcodebuild_summary_classifies_build_operations_and_other_output():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive", "build.log")
    callback("CompileSwift normal arm64 A.swift")
    callback("CompileC normal arm64 B.c")
    callback("Ld /tmp/App normal")
    callback("CodeSign /tmp/App.app")
    callback("CpResource /tmp/a /tmp/b")
    callback("ordinary xcode output")
    callback.finish(failed=False)

    summary = next(
        event.message
        for event in sink.events
        if event.event_type == "summary" and "归档摘要" in event.message
    )
    assert "CompileSwift 1" in summary
    assert "CompileC 1" in summary
    assert "Ld 1" in summary
    assert "CodeSign 1" in summary
    assert "Copy 1" in summary
    assert "省略其他输出 1 行" in summary
    assert "完整日志：build.log" in summary


def test_pip_policy_classifies_noise_without_claiming_local_raw_log():
    reporter, sink = recording_web_reporter(task_kind="update")
    callback = reporter.make_raw_log_callback("pip", "download", None)
    callback("Collecting package-a")
    callback("Using cached package_a.whl")
    callback("Requirement already satisfied: requests")
    callback("Downloading package-a (50%)")
    callback.set_phase("install")
    callback("Installing collected packages: package-a")
    callback("ordinary pip output")
    callback.finish(failed=False)

    summaries = [
        event.message for event in sink.events if event.event_type == "summary"
    ]
    assert any(
        "Collecting 1" in message
        and "Using cached 1" in message
        and "Requirement already satisfied 1" in message
        and "download 1" in message
        for message in summaries
    )
    assert any(
        "install files 1" in message and "省略其他输出 1 行" in message
        for message in summaries
    )
    assert not any("完整日志" in message for message in summaries)


def test_pip_policy_is_selected_only_for_pip_source():
    reporter, pip_sink = recording_web_reporter(task_kind="update")
    pip_callback = reporter.make_raw_log_callback("pip", "download")
    pip_callback("Collecting package-a")
    pip_callback.finish(failed=False)
    assert any("Collecting 1" in event.message for event in pip_sink.events)

    reporter, git_sink = recording_web_reporter(task_kind="update")
    git_callback = reporter.make_raw_log_callback("git", "download")
    git_callback("Collecting package-a")
    git_callback.finish(failed=False)
    assert any(
        event.event_type == "raw" and event.message == "Collecting package-a"
        for event in git_sink.events
    )
    assert not any("Collecting 1" in event.message for event in git_sink.events)


def test_pip_phase_switch_keeps_raw_line_numbers_monotonic():
    reporter, sink = recording_web_reporter(task_kind="update")
    callback = reporter.make_raw_log_callback("pip", "download")
    callback("error: download failed")
    callback.set_phase("install")
    callback("Traceback (most recent call last):")
    callback.finish(failed=True)
    raw_line_numbers = [
        event.raw_line_no
        for event in sink.events
        if event.raw_line_no is not None
    ]
    assert raw_line_numbers == sorted(set(raw_line_numbers))
    assert raw_line_numbers == [1, 2]


def test_raw_phase_summary_reports_classification_counts():
    reporter, sink = recording_web_reporter(task_kind="build")
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    callback("CompileSwift normal.swift")
    callback("warning: once")
    callback.set_phase("export")
    summaries = [e for e in sink.events if e.event_type == "summary"]
    assert any(
        "归档摘要" in event.message
        and "CompileSwift 1" in event.message
        and "warning 1 行" in event.message
        for event in summaries
    )


def test_milestone_deduplicates_quarter_boundaries_per_phase():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], task_kind="metadata")
    reporter.phase("upload")
    reporter.milestone(25, message="quarter")
    reporter.milestone(25, message="duplicate")
    reporter.milestone(30, message="not a boundary")
    milestones = [event for event in sink.events if event.event_type == "milestone"]
    assert [event.message for event in milestones] == ["quarter"]


def test_policy_and_event_sink_failures_do_not_escape(caplog):
    class ExplodingPolicy:
        def consume(self, event):
            raise RuntimeError("classifier broke")

        def flush_phase(self, phase, *, closing=False):
            raise RuntimeError("flush broke")

        def finish(self, *, failed):
            raise RuntimeError("finish broke")

    class ExplodingSink(RecordingSink):
        def on_event(self, event):
            raise RuntimeError("sink broke")

        def on_progress(self, **kwargs):
            raise RuntimeError("progress sink broke")

    reporter = TaskReporter(
        sinks=[ExplodingSink()],
        task_kind="build",
        policy_factory=lambda kind, source, raw_log_path=None: ExplodingPolicy(),
    )
    callback = reporter.make_raw_log_callback("xcodebuild", "archive")
    callback("raw")
    callback.set_phase("export")
    callback.finish(failed=True)
    reporter.log("business operation")
    reporter.phase("archive")
    assert "classifier broke" in caplog.text
    assert "sink broke" in caplog.text
    assert "progress sink broke" in caplog.text


def test_one_failing_sink_does_not_block_healthy_sink():
    class FailingSink:
        def on_event(self, event):
            raise RuntimeError("broken sink")

    healthy = RecordingSink()
    reporter = TaskReporter(
        sinks=[FailingSink(), healthy],
        task_kind="metadata",
    )
    reporter.log("business operation")
    assert healthy.logs == [("info", "business operation")]


def test_legacy_log_sink_filters_internal_events_but_keeps_operations():
    class LegacySink:
        def __init__(self):
            self.logs = []

        def on_log(self, message, *, level="info"):
            self.logs.append((level, message))

        def on_progress(self, **kwargs):
            pass

    sink = LegacySink()
    reporter = TaskReporter(sinks=[sink], task_kind="metadata")
    reporter.phase("upload")
    reporter.milestone(25, message="internal milestone")
    reporter.emit(reporter._event("success", ""))
    reporter.log("business operation")
    assert sink.logs == [("info", "business operation")]


def test_phase_and_progress_map_to_global_pct():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.set_phases([("check", 5, "校验"), ("locales", 95, "上传")])
    r.phase("check")
    r.progress(1, 1, msg="ok")
    assert sink.progress_events[-1]["pct"] == 5
    r.phase("locales")
    r.progress(1, 2, msg="en-US")
    assert sink.progress_events[-1]["pct"] == 5 + int(0.5 * 95)
    assert sink.progress_events[-1]["phase"] == "locales"
    assert sink.progress_events[-1]["phase_index"] == 2
    assert sink.progress_events[-1]["phase_total"] == 2


def test_pct_is_monotonic_when_current_regresses():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.set_phases([("upload", 100, "上传")])
    r.phase("upload")
    r.progress(2, 4)
    mid = sink.progress_events[-1]["pct"]
    r.progress(1, 4)
    assert sink.progress_events[-1]["pct"] >= mid


def test_debug_hidden_unless_verbose():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.log("visible")
    r.debug("hidden")
    assert ("info", "visible") in sink.logs
    assert all(msg != "hidden" for _, msg in sink.logs)

    sink2 = RecordingSink()
    r2 = TaskReporter(sinks=[sink2], verbose=True)
    r2.debug("shown")
    assert ("debug", "shown") in sink2.logs


def test_cli_sink_writes_to_stdout(capsys):
    r = TaskReporter(sinks=[CliSink()], verbose=False)
    r.set_phases([("upload", 100, "上传")])
    r.phase("upload")
    r.progress(1, 2, msg="a")
    r.log("done item")
    out = capsys.readouterr().out
    assert "done item" in out
    assert "[50%] 上传: a" in out


def test_done_forces_pct_100_and_logs_summary():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.set_phases([("upload", 100, "上传")])
    r.phase("upload")
    r.progress(1, 4)
    assert sink.progress_events[-1]["pct"] < 100
    r.done("all finished")
    assert sink.progress_events[-1]["pct"] == 100
    assert ("info", "all finished") in sink.logs


def test_done_without_summary_still_emits_success_event():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], task_kind="build")
    reporter.done()
    assert [event.event_type for event in sink.events] == ["success"]
    assert sink.events[0].message == ""


def test_fail_logs_message_and_detail():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.fail("boom", detail="traceback here")
    assert sink.logs == [("error", "boom"), ("error", "traceback here")]


def test_pct_stays_monotonic_across_combined_phase_plan():
    """Combined meta+screenshots phases must not regress pct within one reporter."""
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.set_phases([
        ("check", 5, "校验"),
        ("locales", 45, "元数据"),
        ("scan", 5, "扫描"),
        ("upload", 45, "截图"),
    ])
    r.phase("check")
    r.progress(1, 1)
    r.phase("locales")
    r.progress(1, 1)
    mid = sink.progress_events[-1]["pct"]
    assert mid == 50
    r.phase("scan")
    assert sink.progress_events[-1]["pct"] >= mid
    r.progress(1, 1)
    r.phase("upload")
    r.progress(1, 1)
    pcts = [e["pct"] for e in sink.progress_events]
    assert pcts == sorted(pcts)
    assert pcts[-1] == 100


def test_set_phases_normalizes_weights_not_summing_to_100():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.set_phases([("x", 1, "X"), ("y", 3, "Y")])  # -> 25 / 75
    r.phase("x")
    r.progress(1, 1)
    assert sink.progress_events[-1]["pct"] == 25
    r.phase("y")
    r.progress(1, 1)
    assert sink.progress_events[-1]["pct"] == 100


def test_task_store_sink_via_make_web_reporter():
    store = MockTaskStore()
    r = make_web_reporter(store, "task-1", "metadata", verbose=False)
    r.set_phases([("check", 5, "校验"), ("locales", 95, "上传")])
    r.phase("locales")
    r.progress(1, 2, msg="en-US")
    r.log("hello")
    r.flush()
    assert ("task-1", "hello") in store.logs
    last = store.progress_calls[-1]
    assert last["task_id"] == "task-1"
    assert last["pct"] == 5 + int(0.5 * 95)
    assert last["msg"] == "en-US"
    assert last["phase"] == "locales"
    assert last["phase_label"] == "上传"
    assert last["phase_index"] == 2
    assert last["phase_total"] == 2


def test_task_store_sink_persists_readable_milestone_once():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-1", "deploy")
    reporter.phase("upload")
    reporter.milestone(25, message="上传进度里程碑：已上传 25%")
    reporter.milestone(25, message="上传进度里程碑：重复")
    reporter.flush()

    lines = [line for _, batch in store.log_batches for line in batch]
    assert lines == ["上传进度里程碑：已上传 25%"]


def test_task_store_sink_batches_high_volume_logs_until_flush():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-1", "metadata")

    for index in range(99):
        reporter.log(f"line {index}")
    assert store.log_batches == []

    reporter.log("line 99")
    assert store.log_batches == [("task-1", [f"line {index}" for index in range(100)])]

    reporter.log("tail")
    reporter.flush()
    assert store.log_batches[-1] == ("task-1", ["tail"])


def test_fail_sets_failed_flag():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    assert r.failed is False
    r.fail("boom")
    assert r.failed is True
    assert ("error", "boom") in sink.logs


def test_task_store_sink_flush_degrades_without_raising():
    class FailingStore(MockTaskStore):
        def __init__(self):
            super().__init__()
            self.fail = True

        def append_logs(self, task_id, lines):
            if self.fail:
                raise RuntimeError("unable to open database file")
            return super().append_logs(task_id, lines)

    store = FailingStore()
    reporter = make_web_reporter(store, "task-db", "update")
    reporter.log("Collecting annotated-types")
    # Must not raise into the update/pip streaming loop.
    assert reporter.flush() is False
    store.fail = False
    assert reporter.flush() is True
    assert store.logs == [("task-db", "Collecting annotated-types")]


def test_reporter_flush_fails_when_any_flushable_sink_soft_fails():
    class SoftFailSink(RecordingSink):
        def flush(self):
            return False

    class SuccessfulSink(RecordingSink):
        def flush(self):
            return True

    reporter = TaskReporter(sinks=[SuccessfulSink(), SoftFailSink()])

    assert reporter.flush() is False


def test_reporter_flush_without_flushable_sink_is_successful():
    reporter = TaskReporter(sinks=[RecordingSink()])

    assert reporter.flush() is True


def test_task_store_sink_progress_degrades_without_raising():
    class FailingStore(MockTaskStore):
        def set_progress(self, *args, **kwargs):
            raise RuntimeError("unable to open database file")

    store = FailingStore()
    reporter = make_web_reporter(store, "task-db", "update")
    reporter.set_phases([("download", 100, "下载")])
    reporter.phase("download")
    reporter.progress(50, 100, msg="half")
