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
        self.progress_calls = []

    def append_log(self, task_id, line):
        self.logs.append((task_id, line))

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
    assert ("task-1", "hello") in store.logs
    last = store.progress_calls[-1]
    assert last["task_id"] == "task-1"
    assert last["pct"] == 5 + int(0.5 * 95)
    assert last["msg"] == "en-US"
    assert last["phase"] == "locales"
    assert last["phase_label"] == "上传"
    assert last["phase_index"] == 2
    assert last["phase_total"] == 2


def test_fail_sets_failed_flag():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    assert r.failed is False
    r.fail("boom")
    assert r.failed is True
    assert ("error", "boom") in sink.logs
