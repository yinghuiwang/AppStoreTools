# tests/test_web_task_runner.py
import time
from threading import Event

from asc.progress import ProcessCanceled
from asc.web.task_runner import (
    SSE_ABSOLUTE_TIMEOUT_SEC,
    TaskScheduler,
    start_background_task,
)
from asc.web.tasks import TaskStore, TaskStatus


def _wait_terminal(store, task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = store.get(task_id)
        if task and task["status"] in {
            TaskStatus.DONE,
            TaskStatus.ERROR,
            TaskStatus.CANCELED,
        }:
            return task
        time.sleep(0.02)
    return store.get(task_id)


def _wait_status(store, task_id, status, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = store.get_state(task_id) or store.get(task_id)
        if task and task["status"] == status:
            return task
        time.sleep(0.02)
    return store.get_state(task_id) or store.get(task_id)


def test_sse_absolute_timeout_constant():
    assert SSE_ABSOLUTE_TIMEOUT_SEC == 7200


def test_start_background_task_reports_progress(tmp_path):
    store = TaskStore(tmp_path / "t.db")

    def run(reporter, cancel_event: Event):
        reporter.set_phases([("upload", 100, "上传")])
        reporter.phase("upload")
        reporter.progress(1, 1, msg="done")
        reporter.log("finished")
        return {"success": True}

    task_id = start_background_task(
        store, kind="urls", profile="demo", verbose=False, run=run
    )
    task = _wait_terminal(store, task_id)
    assert task["status"] == TaskStatus.DONE
    assert task["progress"]["pct"] == 100
    assert any("finished" in line for line in task["logs"])


def test_scheduler_passes_task_kind_to_web_reporter(tmp_path):
    store = TaskStore(tmp_path / "kind.db")
    observed = []

    def run(reporter, cancel_event: Event):
        observed.append(reporter.task_kind)
        return {"success": True}

    task_id = start_background_task(
        store, kind="iap", profile="demo", verbose=False, run=run
    )
    task = _wait_terminal(store, task_id)
    assert task["status"] == TaskStatus.DONE
    assert observed == ["iap"]


def test_cancel_then_worker_completes_stays_canceled(tmp_path):
    """If cancel finishes the task first, a later successful run must not overwrite."""
    store = TaskStore(tmp_path / "cancel.db")
    started = Event()
    release = Event()

    def run(reporter, cancel_event: Event):
        started.set()
        release.wait(timeout=2.0)
        reporter.log("worker finished after cancel")
        return {"success": True}

    task_id = start_background_task(
        store, kind="metadata", profile="demo", verbose=False, run=run
    )
    assert started.wait(timeout=2.0)
    store.set_status(task_id, TaskStatus.CANCELED)
    store.set_result(task_id, {"success": False, "canceled": True})
    release.set()

    # Give the worker time to attempt DONE overwrite
    time.sleep(0.15)
    task = store.get(task_id)
    assert task["status"] == TaskStatus.CANCELED
    assert task["result"] == {"success": False, "canceled": True}


def test_cancel_request_waits_for_worker_then_marks_canceled(tmp_path):
    store = TaskStore(tmp_path / "cooperative-cancel.db")
    started = Event()
    release = Event()

    def run(reporter, cancel_event: Event):
        started.set()
        release.wait(timeout=2.0)
        return {"success": True}

    task_id = start_background_task(store, kind="metadata", profile="demo", verbose=False, run=run)
    assert started.wait(timeout=2.0)
    assert store.request_cancel(task_id)
    assert store.get(task_id)["status"] == TaskStatus.RUNNING
    release.set()

    task = _wait_terminal(store, task_id)
    assert task["status"] == TaskStatus.CANCELED
    assert task["result"]["success"] is False
    assert task["result"]["canceled"] is True
    assert task["result"]["_asc_terminal_recovery"]["status"] == "canceled"


def test_cancel_before_start_skips_running(tmp_path):
    store = TaskStore(tmp_path / "pre-cancel.db")
    task_id = store.create("metadata", profile="demo")
    store.set_status(task_id, TaskStatus.CANCELED)
    store.set_result(task_id, {"success": False, "canceled": True})

    ran = Event()

    def run(reporter, cancel_event: Event):
        ran.set()
        return {"success": True}

    start_background_task(
        store,
        kind="metadata",
        profile="demo",
        verbose=False,
        run=run,
        task_id=task_id,
    )
    time.sleep(0.15)
    task = store.get(task_id)
    assert task["status"] == TaskStatus.CANCELED
    assert not ran.is_set()


def test_exception_marks_error(tmp_path):
    store = TaskStore(tmp_path / "err.db")

    def run(reporter, cancel_event: Event):
        raise RuntimeError("boom")

    task_id = start_background_task(
        store, kind="urls", profile="demo", verbose=False, run=run
    )
    task = _wait_terminal(store, task_id)
    assert task["status"] == TaskStatus.ERROR
    assert any("boom" in line for line in task["logs"])
    assert any("Traceback" in line for line in task["logs"])


def test_exception_skips_second_fail_when_core_already_failed(tmp_path):
    store = TaskStore(tmp_path / "dup-fail.db")

    def run(reporter, cancel_event: Event):
        reporter.fail("core already failed")
        raise RuntimeError("core already failed")

    task_id = start_background_task(
        store, kind="urls", profile="demo", verbose=False, run=run
    )
    task = _wait_terminal(store, task_id)
    assert task["status"] == TaskStatus.ERROR
    # Friendly fail once; traceback is appended separately for the log drawer.
    assert task["logs"].count("core already failed") == 1
    assert any("Traceback" in line for line in task["logs"])


def test_process_canceled_marks_canceled_when_not_pre_finished(tmp_path):
    store = TaskStore(tmp_path / "pc.db")

    def run(reporter, cancel_event: Event):
        raise ProcessCanceled("stopped")

    task_id = start_background_task(
        store, kind="urls", profile="demo", verbose=False, run=run
    )
    task = _wait_terminal(store, task_id)
    assert task["status"] == TaskStatus.CANCELED


def test_third_task_stays_pending_until_worker_free(tmp_path):
    store = TaskStore(tmp_path / "pool.db")
    scheduler = TaskScheduler(store, max_workers=2)
    started = [Event(), Event()]
    release = [Event(), Event()]

    def make_run(i):
        def run(reporter, cancel_event: Event):
            started[i].set()
            release[i].wait(timeout=5)
            return {"success": True}

        return run

    tid1 = start_background_task(
        store,
        kind="build",
        profile="demo",
        verbose=False,
        run=make_run(0),
        scheduler=scheduler,
    )
    tid2 = start_background_task(
        store,
        kind="build",
        profile="demo",
        verbose=False,
        run=make_run(1),
        scheduler=scheduler,
    )
    assert started[0].wait(timeout=2.0)
    assert started[1].wait(timeout=2.0)

    started3 = Event()
    release3 = Event()

    def run3(reporter, cancel_event: Event):
        started3.set()
        release3.wait(timeout=5)
        return {"success": True}

    tid3 = start_background_task(
        store,
        kind="build",
        profile="demo",
        verbose=False,
        run=run3,
        scheduler=scheduler,
    )
    time.sleep(0.15)
    assert store.get_state(tid3)["status"] == TaskStatus.PENDING
    assert not started3.is_set()

    release[0].set()
    assert _wait_status(store, tid1, TaskStatus.DONE, timeout=3.0)["status"] == TaskStatus.DONE
    assert started3.wait(timeout=2.0)
    assert store.get_state(tid3)["status"] == TaskStatus.RUNNING

    release[1].set()
    release3.set()
    assert _wait_terminal(store, tid2)["status"] == TaskStatus.DONE
    assert _wait_terminal(store, tid3)["status"] == TaskStatus.DONE
    scheduler.shutdown(wait=True, timeout=5.0)


def test_cancel_pending_never_runs(tmp_path):
    store = TaskStore(tmp_path / "pending-cancel.db")
    scheduler = TaskScheduler(store, max_workers=1)
    started = Event()
    release = Event()
    ran = Event()

    def blocking_run(reporter, cancel_event: Event):
        started.set()
        release.wait(timeout=5)
        return {"success": True}

    def queued_run(reporter, cancel_event: Event):
        ran.set()
        return {"success": True}

    tid1 = start_background_task(
        store,
        kind="build",
        profile="demo",
        verbose=False,
        run=blocking_run,
        scheduler=scheduler,
    )
    tid2 = start_background_task(
        store,
        kind="build",
        profile="demo",
        verbose=False,
        run=queued_run,
        scheduler=scheduler,
    )
    assert started.wait(timeout=2.0)
    time.sleep(0.1)
    assert store.get_state(tid2)["status"] == TaskStatus.PENDING

    assert store.request_cancel(tid2)
    release.set()

    assert _wait_terminal(store, tid1)["status"] == TaskStatus.DONE
    task2 = _wait_terminal(store, tid2)
    assert task2["status"] == TaskStatus.CANCELED
    assert task2["result"]["success"] is False
    assert task2["result"]["canceled"] is True
    assert task2["result"]["_asc_terminal_recovery"]["status"] == "canceled"
    assert not ran.is_set()
    scheduler.shutdown(wait=True, timeout=5.0)


def test_two_tasks_run_in_parallel(tmp_path):
    import threading

    store = TaskStore(tmp_path / "parallel.db")
    scheduler = TaskScheduler(store, max_workers=2)
    barrier = threading.Barrier(2, timeout=5)
    release = Event()

    def make_run():
        def run(reporter, cancel_event: Event):
            barrier.wait()
            release.wait(timeout=5)
            return {"success": True}

        return run

    tid1 = start_background_task(
        store,
        kind="urls",
        profile="demo",
        verbose=False,
        run=make_run(),
        scheduler=scheduler,
    )
    tid2 = start_background_task(
        store,
        kind="urls",
        profile="demo",
        verbose=False,
        run=make_run(),
        scheduler=scheduler,
    )
    deadline = time.time() + 2.0
    while time.time() < deadline:
        s1 = store.get_state(tid1)
        s2 = store.get_state(tid2)
        if (
            s1
            and s2
            and s1["status"] == TaskStatus.RUNNING
            and s2["status"] == TaskStatus.RUNNING
        ):
            break
        time.sleep(0.02)
    assert store.get_state(tid1)["status"] == TaskStatus.RUNNING
    assert store.get_state(tid2)["status"] == TaskStatus.RUNNING
    release.set()
    assert _wait_terminal(store, tid1)["status"] == TaskStatus.DONE
    assert _wait_terminal(store, tid2)["status"] == TaskStatus.DONE
    scheduler.shutdown(wait=True, timeout=5.0)


def test_terminal_waits_for_soft_log_flush_and_retries_pending_diagnostics(
    tmp_path, monkeypatch, capsys
):
    from asc.reporting import make_web_reporter
    from asc.web.task_runner import TerminalWriteState, finalize_task_outcome

    store = TaskStore(tmp_path / "flush-retry.db")
    task_id = store.create("build")
    store.set_status(task_id, TaskStatus.RUNNING)
    reporter = make_web_reporter(store, task_id, "build")
    raw = reporter.make_raw_log_callback("xcodebuild", "archive")
    raw("raw-before-error")
    raw("error: archive exploded")
    raw("traceback-tail")
    reporter.fail("archive failed")

    original_append_logs = store.append_logs
    fail_once = True

    def soft_fail_once(tid, lines):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            return False
        return original_append_logs(tid, lines)

    monkeypatch.setattr(store, "append_logs", soft_fail_once)
    first = finalize_task_outcome(
        store,
        reporter,
        task_id,
        TaskStatus.ERROR,
        {"success": False, "error": "archive exploded"},
    )

    assert first.state is TerminalWriteState.BLOCKED
    snapshot = store.get_stream_snapshot(task_id, 0)
    assert snapshot is not None
    assert snapshot["task"]["status"] == TaskStatus.RUNNING
    assert snapshot["task"]["result"] is None
    assert snapshot["logs"] == []
    assert "operation=flush" in capsys.readouterr().err

    second = finalize_task_outcome(
        store,
        reporter,
        task_id,
        TaskStatus.ERROR,
        {"success": False, "error": "archive exploded"},
    )

    assert second.state is TerminalWriteState.COMMITTED
    snapshot = store.get_stream_snapshot(task_id, 0)
    assert snapshot is not None
    assert snapshot["task"]["status"] == TaskStatus.ERROR
    messages = [entry["message"] for entry in snapshot["logs"]]
    assert "raw-before-error" in messages
    assert "error: archive exploded" in messages
    assert "traceback-tail" in messages
    assert "archive failed" in messages
    assert [entry["seq"] for entry in snapshot["logs"]] == list(
        range(1, len(snapshot["logs"]) + 1)
    )
    store.close()


def test_pending_commit_never_notifies_ordinary_task(monkeypatch):
    from unittest.mock import patch

    from asc.web.task_runner import (
        TerminalWriteOutcome,
        TerminalWriteState,
        _execute_task,
    )

    store = TaskStore()
    task_id = store.create("metadata")
    pending = TerminalWriteOutcome(
        TerminalWriteState.PENDING_COMMIT,
        TaskStatus.DONE,
        recovery_confirmed=True,
    )

    with patch(
        "asc.web.task_runner.finalize_task_outcome",
        return_value=pending,
    ), patch("asc.web.task_runner._notify_task_finished") as notify:
        _execute_task(
            store,
            task_id,
            "metadata",
            lambda *_: {"success": True},
            verbose=False,
        )

    assert store.get_state(task_id)["status"] == TaskStatus.RUNNING
    notify.assert_not_called()


def test_worker_retries_terminal_after_transient_final_log_flush(
    tmp_path, monkeypatch
):
    store = TaskStore(tmp_path / "worker-flush-retry.db")
    original_append_logs = store.append_logs
    failed = False

    def soft_fail_once(task_id, lines):
        nonlocal failed
        if not failed and "final diagnostic" in lines:
            failed = True
            return False
        return original_append_logs(task_id, lines)

    monkeypatch.setattr(store, "append_logs", soft_fail_once)

    def run(reporter, _cancel_event):
        reporter.log("final diagnostic")
        return {"success": True, "uploaded": 1}

    task_id = start_background_task(
        store,
        kind="metadata",
        profile="demo",
        verbose=False,
        run=run,
    )
    task = _wait_terminal(store, task_id)

    assert failed is True
    assert task["status"] == TaskStatus.DONE
    assert task["result"]["uploaded"] == 1
    assert "final diagnostic" in task["logs"]
    store.close()
