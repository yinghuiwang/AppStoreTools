import subprocess
import sys
import threading

import pytest

from asc.progress import ProcessCanceled, Spinner
from asc.reporting import TaskReporter, CliSink, make_web_reporter


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


@pytest.mark.parametrize(
    "diagnostic",
    [
        "fail",
        "failed",
        "failure",
        "error",
        "RuntimeError: boom",
        "ValueError: bad value",
        "fatal: linker stopped",
        "exception raised",
        "Traceback (most recent call last):",
        "错误：签名无效",
        "失败：无法导出",
        "异常：构建中断",
    ],
)
def test_web_raw_subprocess_logs_preserve_common_diagnostics(diagnostic):
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], raw_log_lines_per_second=1)
    callback = reporter.make_raw_log_callback()

    callback("ordinary allowance")
    callback(diagnostic)
    callback("ordinary suppressed")
    callback.flush()

    messages = [message for _, message in sink.logs]
    assert diagnostic in messages
    assert "ordinary suppressed" not in messages
    assert any("已省略 1 行" in message for message in messages)


def test_web_raw_subprocess_logs_are_rate_limited_but_keep_errors():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-1")
    callback = reporter.make_raw_log_callback()

    for index in range(30):
        callback(f"CompileSwift File{index}.swift")
    callback("error: signing failed")
    callback.flush()
    reporter.flush()

    lines = [line for _, batch in store.log_batches for line in batch]
    assert len([line for line in lines if line.startswith("CompileSwift")]) == 20
    assert "error: signing failed" in lines
    assert any("已省略 10 行" in line for line in lines)


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
    r = make_web_reporter(store, "task-1", verbose=False)
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


def test_task_store_sink_batches_high_volume_logs_until_flush():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-1")

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
        def append_logs(self, task_id, lines):
            raise RuntimeError("unable to open database file")

    store = FailingStore()
    reporter = make_web_reporter(store, "task-db")
    reporter.log("Collecting annotated-types")
    # Must not raise into the update/pip streaming loop.
    reporter.flush()
    reporter.log("still going")
    reporter.flush()


def test_task_store_sink_progress_degrades_without_raising():
    class FailingStore(MockTaskStore):
        def set_progress(self, *args, **kwargs):
            raise RuntimeError("unable to open database file")

    store = FailingStore()
    reporter = make_web_reporter(store, "task-db")
    reporter.set_phases([("download", 100, "下载")])
    reporter.phase("download")
    reporter.progress(50, 100, msg="half")
