# tests/test_web_task_runner.py
import time
from threading import Event

from asc.progress import ProcessCanceled
from asc.web.task_runner import start_background_task, SSE_ABSOLUTE_TIMEOUT_SEC
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
    assert task["result"] == {"success": False, "canceled": True}


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
    assert task["logs"].count("core already failed") == 1


def test_process_canceled_marks_canceled_when_not_pre_finished(tmp_path):
    store = TaskStore(tmp_path / "pc.db")

    def run(reporter, cancel_event: Event):
        raise ProcessCanceled("stopped")

    task_id = start_background_task(
        store, kind="urls", profile="demo", verbose=False, run=run
    )
    task = _wait_terminal(store, task_id)
    assert task["status"] == TaskStatus.CANCELED
