# tests/test_web_tasks.py
from __future__ import annotations

import os
import sqlite3
import threading
import time
from unittest.mock import MagicMock

import pytest
from asc.web.tasks import TaskStore, TaskStatus


def _join_threads(threads, timeout):
    deadline = time.monotonic() + timeout
    for thread in threads:
        if thread.ident is not None:
            thread.join(max(0.0, deadline - time.monotonic()))
    return [thread.name for thread in threads if thread.is_alive()]


def _raise_primary_or_cleanup(
    primary,
    *,
    close_attempted,
    cleanup_errors,
    alive_before_close,
    alive_after_close,
):
    cleanup_failures = []
    if not close_attempted:
        cleanup_failures.append("store.close was not attempted")
    cleanup_failures.extend(
        f"store.close failed: {error!r}" for error in cleanup_errors
    )
    if alive_before_close:
        cleanup_failures.append(
            f"threads alive before close: {alive_before_close!r}"
        )
    if alive_after_close:
        cleanup_failures.append(
            f"threads alive after close: {alive_after_close!r}"
        )
    if cleanup_failures:
        message = "cleanup verification failed: " + "; ".join(cleanup_failures)
        if primary is not None:
            raise AssertionError(message) from primary
        raise AssertionError(message)
    if primary is not None:
        raise primary.with_traceback(primary.__traceback__)


def _run_with_threaded_store_cleanup(
    *,
    store,
    threads,
    stop,
    body,
    join_timeout=5,
):
    primary = None
    result = None
    cleanup_errors = []
    close_attempted = False
    try:
        result = body()
    except BaseException as exc:  # noqa: BLE001
        primary = exc
    finally:
        stop.set()
        alive_before_close = _join_threads(threads, join_timeout)
        try:
            close_attempted = True
            store.close()
        except BaseException as exc:  # noqa: BLE001
            cleanup_errors.append(exc)
        alive_after_close = _join_threads(threads, join_timeout)
    _raise_primary_or_cleanup(
        primary,
        close_attempted=close_attempted,
        cleanup_errors=cleanup_errors,
        alive_before_close=alive_before_close,
        alive_after_close=alive_after_close,
    )
    return result


def test_threaded_store_cleanup_combines_real_body_close_and_thread_failures():
    primary = RuntimeError("primary test failure")
    release = threading.Event()
    cleanup_stop = threading.Event()

    class FailingStore:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            raise OSError("close failed")

    store = FailingStore()
    thread = threading.Thread(
        target=release.wait,
        name="short-lived-daemon-reader",
        daemon=True,
    )

    def fail_body():
        thread.start()
        raise primary

    try:
        with pytest.raises(
            AssertionError,
            match="threads alive after close",
        ) as caught:
            _run_with_threaded_store_cleanup(
                store=store,
                threads=[thread],
                stop=cleanup_stop,
                body=fail_body,
                join_timeout=0.01,
            )
    finally:
        release.set()
        thread.join(1)

    assert caught.value.__cause__ is primary
    assert "store.close failed" in str(caught.value)
    assert "threads alive before close" in str(caught.value)
    assert "short-lived-daemon-reader" in str(caught.value)
    assert store.close_calls == 1
    assert cleanup_stop.is_set()
    assert not thread.is_alive()


def _open_fd_count():
    for path in ("/proc/self/fd", "/dev/fd"):
        try:
            return len(os.listdir(path))
        except OSError:
            continue
    pytest.skip("open file descriptor sampling is unavailable")


def test_four_writers_and_twenty_stream_readers_preserve_order(
    tmp_path, capsys
):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build")
    writer_errors = []
    reader_errors = []
    reader_sequences = [[] for _ in range(20)]
    stop = threading.Event()
    expected_count = 1000

    def writer(worker_id):
        try:
            for index in range(250):
                assert store.append_logs(task_id, [f"w{worker_id}-{index}"])
        except BaseException as exc:  # noqa: BLE001
            writer_errors.append(exc)

    def reader(reader_id):
        cursor = 0
        try:
            while True:
                snapshot = store.get_stream_snapshot(task_id, cursor)
                if snapshot is None:
                    raise AssertionError("task disappeared")
                for log in snapshot["logs"]:
                    if log["seq"] != cursor + 1:
                        raise AssertionError(
                            f"reader {reader_id} expected seq {cursor + 1}, "
                            f"got {log['seq']}"
                        )
                    cursor = log["seq"]
                    reader_sequences[reader_id].append(cursor)
                if stop.is_set():
                    count = store.count_logs(task_id)
                    if cursor >= count:
                        if count != expected_count:
                            raise AssertionError(
                                f"writers stopped after {count} of {expected_count} logs"
                            )
                        break
                if not snapshot["logs"]:
                    time.sleep(0.001)
        except BaseException as exc:  # noqa: BLE001
            reader_errors.append(exc)

    readers = [
        threading.Thread(
            target=reader,
            args=(index,),
            name=f"stream-reader-{index}",
            daemon=True,
        )
        for index in range(20)
    ]
    writers = [
        threading.Thread(
            target=writer,
            args=(index,),
            name=f"log-writer-{index}",
            daemon=True,
        )
        for index in range(4)
    ]

    def exercise_concurrency():
        for thread in readers + writers:
            thread.start()
        alive_after_writers = _join_threads(writers, 30)
        assert not alive_after_writers
        stop.set()
        alive_after_test = _join_threads(readers, 30)

        assert not writer_errors
        assert not reader_errors
        assert not alive_after_test
        assert reader_sequences == [
            list(range(1, expected_count + 1)) for _ in range(20)
        ]
        assert [item["seq"] for item in store.get_logs_after(task_id)] == list(
            range(1, expected_count + 1)
        )
        assert "database is locked" not in capsys.readouterr().err.lower()

    _run_with_threaded_store_cleanup(
        store=store,
        threads=writers + readers,
        stop=stop,
        body=exercise_concurrency,
    )


def test_twenty_stream_readers_do_not_leak_file_descriptors(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build")
    store.append_logs(task_id, ["warmup"])
    errors = []

    def reader():
        try:
            for _ in range(500):
                snapshot = store.get_stream_snapshot(task_id, 0)
                assert snapshot is not None
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=reader, name=f"fd-reader-{index}", daemon=True)
        for index in range(20)
    ]
    stop = threading.Event()

    def exercise_fd_polling():
        for _ in range(100):
            assert store.get_stream_snapshot(task_id, 0) is not None
        stable = _open_fd_count()
        for thread in threads:
            thread.start()
        alive_after_test = _join_threads(threads, 30)
        final = _open_fd_count()

        assert not errors
        assert not alive_after_test
        assert final <= stable + 10, (stable, final)

    _run_with_threaded_store_cleanup(
        store=store,
        threads=threads,
        stop=stop,
        body=exercise_fd_polling,
    )


def test_open_configured_connection_closes_when_pragma_fails(tmp_path, monkeypatch):
    store = TaskStore.__new__(TaskStore)
    store._db_path = tmp_path / "tasks.db"
    closed = []

    class TrackedConnection:
        row_factory = None

        def execute(self, sql):
            if "journal_mode" in sql:
                raise sqlite3.OperationalError("pragma failed")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: TrackedConnection())
    with pytest.raises(sqlite3.OperationalError, match="pragma failed"):
        store._open_configured_connection()
    assert closed == [True]


@pytest.mark.parametrize("write", [False, True])
def test_connection_commits_or_rolls_back_and_always_closes(write, monkeypatch):
    calls = []
    conn = MagicMock()
    conn.execute.side_effect = lambda sql: calls.append(sql)
    conn.commit.side_effect = lambda: calls.append("commit")
    conn.rollback.side_effect = lambda: calls.append("rollback")
    conn.close.side_effect = lambda: calls.append("close")
    store = TaskStore.__new__(TaskStore)
    monkeypatch.setattr(store, "_open_configured_connection", lambda: conn)

    with store._connection(write=write):
        calls.append("body")
    assert calls[-2:] == ["commit", "close"]
    assert calls[0] == ("BEGIN IMMEDIATE" if write else "BEGIN")

    calls.clear()
    with pytest.raises(RuntimeError, match="boom"):
        with store._connection(write=write):
            raise RuntimeError("boom")
    assert calls[-2:] == ["rollback", "close"]


def test_connection_begin_failure_rolls_back_and_closes(monkeypatch):
    calls = []
    conn = MagicMock()

    def fail_begin(sql):
        calls.append(sql)
        raise sqlite3.OperationalError("begin failed")

    conn.execute.side_effect = fail_begin
    conn.rollback.side_effect = lambda: calls.append("rollback")
    conn.close.side_effect = lambda: calls.append("close")
    store = TaskStore.__new__(TaskStore)
    monkeypatch.setattr(store, "_open_configured_connection", lambda: conn)

    with pytest.raises(sqlite3.OperationalError, match="begin failed"):
        with store._connection(write=True):
            pass

    assert calls == ["BEGIN IMMEDIATE", "rollback", "close"]


def test_connection_commit_failure_rolls_back_and_closes(monkeypatch):
    calls = []
    conn = MagicMock()
    conn.execute.side_effect = lambda sql: calls.append(sql)

    def fail_commit():
        calls.append("commit")
        raise sqlite3.OperationalError("commit failed")

    conn.commit.side_effect = fail_commit
    conn.rollback.side_effect = lambda: calls.append("rollback")
    conn.close.side_effect = lambda: calls.append("close")
    store = TaskStore.__new__(TaskStore)
    monkeypatch.setattr(store, "_open_configured_connection", lambda: conn)

    with pytest.raises(sqlite3.OperationalError, match="commit failed"):
        with store._connection(write=True):
            calls.append("body")

    assert calls == ["BEGIN IMMEDIATE", "body", "commit", "rollback", "close"]


def test_init_db_rolls_back_all_ddl_when_later_statement_fails(tmp_path, monkeypatch):
    db_path = tmp_path / "tasks.db"

    class FailingDDLConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.lstrip().startswith("CREATE TABLE IF NOT EXISTS task_order"):
                raise sqlite3.OperationalError("task_order DDL failed")
            return super().execute(sql, parameters)

    store = TaskStore.__new__(TaskStore)
    store._db_path = db_path
    store._last_db_error = ""
    store._db_write_failures = 0
    monkeypatch.setattr(
        store,
        "_open_configured_connection",
        lambda: sqlite3.connect(db_path, factory=FailingDDLConnection),
    )

    with pytest.raises(sqlite3.OperationalError, match="task_order"):
        store._init_db()

    with sqlite3.connect(db_path) as conn:
        task_runs = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'task_runs'"
        ).fetchone()
    assert task_runs is None


def test_init_db_records_config_error_context_once(tmp_path, monkeypatch, capsys):
    store = TaskStore.__new__(TaskStore)
    store._db_path = tmp_path / "tasks.db"
    store._last_db_error = ""
    store._db_write_failures = 0

    def fail_open():
        raise sqlite3.OperationalError("pragma failed")

    monkeypatch.setattr(store, "_open_configured_connection", fail_open)

    for _ in range(2):
        with pytest.raises(sqlite3.OperationalError, match="pragma failed"):
            store._init_db()

    stderr = capsys.readouterr().err
    assert stderr.count("TaskStore DB error") == 1
    assert "task_id=-" in stderr
    assert "operation=init_db" in stderr
    assert f"path={store._db_path}" in stderr


def test_all_sqlite_entrypoints_balance_open_and_close(tmp_path, monkeypatch):
    original_connect = sqlite3.connect

    class CountingConnection(sqlite3.Connection):
        opened = 0
        closed = 0

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            type(self).opened += 1

        def close(self):
            type(self).closed += 1
            super().close()

    def counting_connect(*args, **kwargs):
        kwargs["factory"] = CountingConnection
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting_connect)
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build")
    store.get(task_id)
    store.get_logs_after(task_id)
    store.is_cancel_requested(task_id)
    store.list_recent()
    store.list_recent_states()
    store.get_state(task_id)
    store.get_stream_snapshot(task_id, 0)
    store.count_logs(task_id)
    store.get_replay(task_id)
    store.list_failed(limit=5)
    store.set_replay(task_id, {"kind": "build", "profile": "", "verbose": False, "params": {}})
    store.append_logs(task_id, ["writer"])
    store._db_write(lambda conn: conn.execute("SELECT 1"), critical=True)
    store._init_db()
    store._db_is_empty()
    store._load_db()
    store._save()
    store.close()
    assert CountingConnection.opened == CountingConnection.closed


def test_create_task():
    store = TaskStore()
    task_id = store.create("metadata")
    assert task_id is not None
    task = store.get(task_id)
    assert task["status"] == TaskStatus.PENDING
    assert task["kind"] == "metadata"
    assert task["logs"] == []


def test_append_log():
    store = TaskStore()
    task_id = store.create("build")
    store.append_log(task_id, "step 1 done")
    store.append_log(task_id, "step 2 done")
    task = store.get(task_id)
    assert task["logs"] == ["step 1 done", "step 2 done"]


def test_append_logs_assigns_contiguous_sequences_in_one_batch(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build")

    store.append_logs(task_id, ["one", "two", "three"])

    assert store.get_logs_after(task_id) == [
        {"seq": 1, "message": "one"},
        {"seq": 2, "message": "two"},
        {"seq": 3, "message": "three"},
    ]


def test_set_status():
    store = TaskStore()
    task_id = store.create("metadata")
    store.set_status(task_id, TaskStatus.RUNNING)
    assert store.get(task_id)["status"] == TaskStatus.RUNNING
    store.set_status(task_id, TaskStatus.DONE)
    assert store.get(task_id)["status"] == TaskStatus.DONE


def test_request_cancel_marks_task_and_sets_event():
    store = TaskStore()
    task_id = store.create("metadata")
    store.set_status(task_id, TaskStatus.RUNNING)

    assert store.request_cancel(task_id) is True
    assert store.is_cancel_requested(task_id) is True
    assert store.cancel_event(task_id).is_set()
    assert store.get(task_id)["cancel_requested"] is True


def test_request_cancel_returns_false_for_missing_task():
    store = TaskStore()
    assert store.request_cancel("missing") is False


def test_set_result():
    store = TaskStore()
    task_id = store.create("metadata")
    store.set_result(task_id, {"success": 3, "skipped": 1, "failed": 0})
    assert store.get(task_id)["result"]["success"] == 3


def test_get_nonexistent_returns_none():
    store = TaskStore()
    assert store.get("nonexistent-id") is None


def test_list_recent():
    store = TaskStore()
    ids = [store.create("metadata") for _ in range(3)]
    recent = store.list_recent(limit=2)
    assert len(recent) == 2
    assert recent[0]["id"] == ids[2]  # newest first


def test_list_recent_states_returns_newest_tasks_without_logs():
    store = TaskStore()
    first = store.create("metadata", profile="one")
    second = store.create("build", profile="two")
    store.append_log(second, "line")

    recent = store.list_recent_states(limit=2)

    assert [task["id"] for task in recent] == [second, first]
    assert [task["logs"] for task in recent] == [[], []]
    assert recent[0]["profile"] == "two"


def test_list_recent_states_stops_after_limit(monkeypatch):
    store = TaskStore()
    task_ids = [store.create("metadata") for _ in range(3)]
    public_task = store._public_task
    converted_ids = []

    def record_conversion(task):
        converted_ids.append(task["id"])
        return public_task(task)

    monkeypatch.setattr(store, "_public_task", record_conversion)

    recent = store.list_recent_states(limit=2)

    assert [task["id"] for task in recent] == [task_ids[2], task_ids[1]]
    assert converted_ids == [task_ids[2], task_ids[1]]


@pytest.mark.parametrize(
    ("kind", "title", "retry_path"),
    [
        ("metadata", "元数据上传", "/metadata"),
        ("build", "构建上传", "/build"),
        ("whats-new", "更新说明上传", "/whats-new"),
        ("iap", "内购上传", "/iap"),
        ("urls", "URL 更新", "/urls"),
        ("update", "工具更新", "/update"),
    ],
)
def test_task_store_adds_display_title_and_retry_path(kind, title, retry_path):
    store = TaskStore()
    task_id = store.create(kind)
    task = store.get(task_id)
    assert task["title"] == title
    assert task["retry_path"] == retry_path


def test_task_store_adds_duration_for_completed_task():
    store = TaskStore()
    task_id = store.create("build")
    store._tasks[task_id]["created_at"] = "2026-06-09T10:00:00"
    store._tasks[task_id]["completed_at"] = "2026-06-09T10:01:05"
    store._tasks[task_id]["status"] = TaskStatus.DONE

    task = store.get(task_id)
    assert task["duration_seconds"] == 65
    assert task["duration_label"] == "1m 5s"


def test_task_store_persists_tasks(tmp_path):
    storage_path = tmp_path / "web_tasks.json"
    store = TaskStore(storage_path)
    task_id = store.create("metadata", profile="myapp")
    store.append_log(task_id, "uploaded metadata")
    store.set_progress(task_id, 80, "uploading")
    store.set_status(task_id, TaskStatus.DONE)
    store.set_result(task_id, {"success": True})

    restored = TaskStore(storage_path)
    task = restored.get(task_id)
    assert task is not None
    assert task["kind"] == "metadata"
    assert task["profile"] == "myapp"
    assert task["logs"] == ["uploaded metadata"]
    assert task["progress"] == {
        "pct": 80,
        "msg": "uploading",
        "phase": "",
        "phase_label": "",
        "phase_index": 0,
        "phase_total": 0,
    }
    assert task["status"] == TaskStatus.DONE
    assert task["result"] == {"success": True}


def test_task_store_marks_interrupted_tasks_after_restart(tmp_path):
    storage_path = tmp_path / "web_tasks.json"
    store = TaskStore(storage_path)
    task_id = store.create("build")
    store.set_status(task_id, TaskStatus.RUNNING)

    restored = TaskStore(storage_path)
    task = restored.get(task_id)
    assert task["status"] == TaskStatus.ERROR
    assert task["result"]["success"] is False
    assert "Task interrupted" in task["result"]["error"]


def test_task_store_recovers_even_when_legacy_json_exists(tmp_path):
    """Legacy web_tasks.json must not skip SQLite recover-on-boot."""
    storage_path = tmp_path / "web_tasks.json"
    storage_path.write_text(
        '{"version": 1, "order": ["legacy"], "tasks": {'
        '"legacy": {"id": "legacy", "kind": "build", "status": "done", '
        '"logs": ["old"], "progress": {"pct": 100, "msg": "done"}}}}',
        encoding="utf-8",
    )
    store = TaskStore(storage_path)
    stuck_id = store.create("update", profile="system")
    store.set_status(stuck_id, TaskStatus.RUNNING)
    store.set_result(stuck_id, None)

    restored = TaskStore(storage_path)
    task = restored.get(stuck_id)
    assert task["status"] == TaskStatus.ERROR
    assert "Task interrupted" in task["result"]["error"]
    assert restored.get("legacy")["status"] == TaskStatus.DONE


def test_task_store_keeps_successful_update_done_after_restart(tmp_path):
    storage_path = tmp_path / "tasks.db"
    store = TaskStore(storage_path)
    task_id = store.create("update", profile="system")
    store.set_status(task_id, TaskStatus.DONE)
    store.set_result(
        task_id,
        {"success": True, "installed": True, "restarting": True},
    )

    restored = TaskStore(storage_path)
    task = restored.get(task_id)
    assert task["status"] == TaskStatus.DONE
    assert task["result"]["success"] is True
    assert task["result"]["restarting"] is False
    assert task["result"]["restarted"] is True
    assert any("重启" in line for line in task["logs"])


def test_task_store_marks_update_error_from_install_marker(tmp_path, monkeypatch):
    from asc.web import daemon

    monkeypatch.setattr(daemon, "_STATE_DIR", tmp_path)
    storage_path = tmp_path / "tasks.db"
    store = TaskStore(storage_path)
    task_id = store.create("update", profile="system")
    store.set_status(task_id, TaskStatus.DONE)
    store.set_result(
        task_id,
        {"success": True, "pending_install": True, "restarting": True},
    )
    daemon.write_update_restart_marker(
        task_id,
        installed=False,
        pending_install=True,
        install_error="pip timed out",
    )

    restored = TaskStore(storage_path)
    task = restored.get(task_id)
    assert task["status"] == TaskStatus.ERROR
    assert task["result"]["success"] is False
    assert "pip timed out" in task["result"]["error"]


def test_task_store_finalizes_running_update_with_success_result(tmp_path):
    storage_path = tmp_path / "tasks.db"
    store = TaskStore(storage_path)
    task_id = store.create("update", profile="system")
    store.set_status(task_id, TaskStatus.RUNNING)
    store.set_result(task_id, {"success": True, "installed": True, "restarting": True})

    restored = TaskStore(storage_path)
    task = restored.get(task_id)
    assert task["status"] == TaskStatus.DONE
    assert task["result"]["success"] is True
    assert task["result"]["restarted"] is True
    assert task["result"]["restarting"] is False


def test_restart_blocked_update_never_recovers_as_success(tmp_path):
    contradictory = {
        "success": False,
        "restart_blocked": True,
        "installed": True,
        "restarting": True,
        "pending_install": True,
    }
    assert TaskStore._update_result_looks_successful(contradictory) is False

    storage_path = tmp_path / "tasks.db"
    store = TaskStore(storage_path)
    task_id = store.create("update", profile="system")
    store.set_status(task_id, TaskStatus.RUNNING)
    store.set_result(
        task_id,
        {
            "success": False,
            "restart_blocked": True,
            "installed": False,
            "restarting": False,
            "pending_install": False,
            "commit": "abc1234",
        },
    )

    restored = TaskStore(storage_path)
    task = restored.get(task_id)
    assert task["status"] == TaskStatus.ERROR
    assert task["result"]["success"] is False
    assert task["result"]["restart_blocked"] is True
    assert task["result"]["installed"] is False
    assert task["result"]["restarting"] is False
    assert task["result"]["pending_install"] is False
    assert task["result"]["commit"] == "abc1234"


def test_task_store_ignores_invalid_storage_file(tmp_path):
    storage_path = tmp_path / "web_tasks.json"
    storage_path.write_text("{not-json", encoding="utf-8")

    store = TaskStore(storage_path)
    assert store.list_recent() == []


def test_task_store_defaults_invalid_progress_on_load(tmp_path):
    storage_path = tmp_path / "web_tasks.json"
    storage_path.write_text(
        """
        {
          "version": 1,
          "order": ["task-1"],
          "tasks": {
            "task-1": {
              "id": "task-1",
              "kind": "metadata",
              "status": "done",
              "logs": [],
              "progress": {"pct": "bad", "msg": "ok"}
            }
          }
        }
        """,
        encoding="utf-8",
    )

    store = TaskStore(storage_path)
    assert store.get("task-1")["progress"] == {
        "pct": 0,
        "msg": "ok",
        "phase": "",
        "phase_label": "",
        "phase_index": 0,
        "phase_total": 0,
    }


def test_task_store_uses_sqlite_and_exposes_log_sequences(tmp_path):
    storage_path = tmp_path / "tasks.db"
    store = TaskStore(storage_path)
    task_id = store.create("metadata")
    store.append_log(task_id, "first")
    store.append_log(task_id, "second")
    store.set_status(task_id, TaskStatus.DONE)

    assert storage_path.exists()
    assert store.get_logs_after(task_id, 1) == [{"seq": 2, "message": "second"}]
    restored = TaskStore(storage_path)
    assert restored.get(task_id)["logs"] == ["first", "second"]


def test_task_store_migrates_legacy_json_to_sqlite(tmp_path):
    storage_path = tmp_path / "web_tasks.json"
    storage_path.write_text(
        '{"version": 1, "order": ["old"], "tasks": {'
        '"old": {"id": "old", "kind": "build", "status": "done", '
        '"logs": ["legacy"], "progress": {"pct": 100, "msg": "done"}}}}',
        encoding="utf-8",
    )

    store = TaskStore(storage_path)

    assert (tmp_path / "web_tasks.db").exists()
    assert store.get("old")["logs"] == ["legacy"]


def test_sqlite_append_log_does_not_rewrite_full_snapshot(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build")
    store._save = lambda: (_ for _ in ()).throw(AssertionError("full snapshot save"))

    store.append_log(task_id, "incremental")

    assert store.get_logs_after(task_id) == [{"seq": 1, "message": "incremental"}]


def test_sqlite_log_cursor_does_not_reload_all_tasks(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build")
    store.append_log(task_id, "line")
    store._refresh_db = lambda: (_ for _ in ()).throw(AssertionError("full reload"))

    assert store.get_logs_after(task_id) == [{"seq": 1, "message": "line"}]


def test_sqlite_task_state_query_does_not_load_logs(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build")
    store.append_log(task_id, "line")
    state = store.get_state(task_id)

    assert state["id"] == task_id
    assert state["logs"] == []


def test_stream_snapshot_returns_state_and_incremental_logs(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build", profile="demo")
    store.append_logs(task_id, ["one", "two"])
    store.set_progress(task_id, 50, "half")
    opens = 0
    original = store._open_configured_connection

    def counted_open():
        nonlocal opens
        opens += 1
        return original()

    monkeypatch.setattr(store, "_open_configured_connection", counted_open)

    snapshot = store.get_stream_snapshot(task_id, 1)

    assert opens == 1
    assert snapshot is not None
    assert snapshot["task"]["logs"] == []
    assert snapshot["task"]["progress"]["pct"] == 50
    assert snapshot["logs"] == [{"seq": 2, "message": "two"}]


def test_stream_snapshot_keeps_state_and_logs_in_one_read_transaction(tmp_path, monkeypatch):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    task_id = store.create("build")
    store.append_log(task_id, "old")
    store.set_progress(task_id, 10, "old")
    original = store._open_configured_connection
    writer_started = threading.Event()
    writer_finished = threading.Event()

    def write_new_state() -> None:
        assert writer_started.wait(2)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO task_logs (task_id, seq, message, created_at) VALUES (?, ?, ?, ?)",
                (task_id, 2, "new", "2026-08-11T00:00:00"),
            )
            conn.execute(
                "UPDATE task_runs SET progress_pct = 90, progress_msg = ? WHERE id = ?",
                ("new", task_id),
            )
        writer_finished.set()

    writer = threading.Thread(target=write_new_state)
    writer.start()

    def open_with_writer_between_selects():
        connection = original()

        def trace(statement: str) -> None:
            if "FROM task_logs" in statement:
                writer_started.set()
                assert writer_finished.wait(2)

        connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(store, "_open_configured_connection", open_with_writer_between_selects)

    snapshot = store.get_stream_snapshot(task_id, 0)
    writer.join(2)

    assert snapshot is not None
    assert snapshot["task"]["progress"]["pct"] == 10
    assert snapshot["logs"] == [{"seq": 1, "message": "old"}]
    next_snapshot = store.get_stream_snapshot(task_id, 1)
    assert next_snapshot is not None
    assert next_snapshot["task"]["progress"]["pct"] == 90
    assert next_snapshot["logs"] == [{"seq": 2, "message": "new"}]


def test_memory_stream_snapshot_is_built_under_one_lock():
    store = TaskStore()
    task_id = store.create("metadata")
    store.append_log(task_id, "business")
    original_lock = store._lock

    class CountingLock:
        def __init__(self):
            self.enters = 0

        def __enter__(self):
            self.enters += 1
            original_lock.acquire()
            return self

        def __exit__(self, exc_type, exc, traceback):
            original_lock.release()

    lock = CountingLock()
    store._lock = lock

    snapshot = store.get_stream_snapshot(task_id, 0)

    assert lock.enters == 1
    assert snapshot is not None
    assert snapshot["task"]["logs"] == []
    assert snapshot["logs"] == [{"seq": 1, "message": "business"}]


def test_stream_snapshot_has_same_complete_structure_in_sqlite_and_memory(tmp_path, monkeypatch):
    fixed_now = "2026-08-11T12:00:00"
    fixed_task_id = "snapshot-parity-task"
    monkeypatch.setattr(
        "asc.web.tasks.uuid.uuid4",
        lambda: fixed_task_id,
    )
    stores = [TaskStore(tmp_path / "tasks.db"), TaskStore()]

    snapshots = []
    for store in stores:
        monkeypatch.setattr(store, "_now", lambda: fixed_now)
        task_id = store.create("build", profile="demo")
        store.append_logs(task_id, ["one", "two", "three"])
        store.set_progress(
            task_id,
            60,
            "uploading",
            phase="upload",
            phase_label="Uploading",
            phase_index=2,
            phase_total=3,
        )
        store.set_result(task_id, {"success": True, "artifact": "Demo.ipa"})
        store.set_status(task_id, TaskStatus.DONE)
        snapshots.append(store.get_stream_snapshot(task_id, 1))

    assert snapshots[0] == snapshots[1]
    assert snapshots[0] is not None
    assert snapshots[0]["task"]["id"] == fixed_task_id
    assert snapshots[0]["task"]["status"] == TaskStatus.DONE
    assert snapshots[0]["task"]["logs"] == []
    assert snapshots[0]["task"]["progress"] == {
        "pct": 60,
        "msg": "uploading",
        "phase": "upload",
        "phase_label": "Uploading",
        "phase_index": 2,
        "phase_total": 3,
    }
    assert snapshots[0]["task"]["result"] == {
        "success": True,
        "artifact": "Demo.ipa",
    }
    assert snapshots[0]["logs"] == [
        {"seq": 2, "message": "two"},
        {"seq": 3, "message": "three"},
    ]


def test_sqlite_list_recent_states_does_not_query_task_logs(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    task_ids = [store.create("build") for _ in range(3)]
    store.append_log(task_ids[2], "line")
    connect = store._open_configured_connection
    statements = []

    def traced_connect():
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(store, "_open_configured_connection", traced_connect)

    recent = store.list_recent_states(limit=2)

    assert [task["id"] for task in recent] == [task_ids[2], task_ids[1]]
    assert [task["logs"] for task in recent] == [[], []]
    assert not any("task_logs" in statement.lower() for statement in statements)


def test_sqlite_state_updates_do_not_rewrite_logs(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build")
    store._save = lambda: (_ for _ in ()).throw(AssertionError("full snapshot save"))

    store.set_status(task_id, TaskStatus.RUNNING)
    store.set_progress(task_id, 42, "building")
    store.set_result(task_id, {"ok": True})
    store.request_cancel(task_id)

    task = store.get(task_id)
    assert task["progress"] == {
        "pct": 42,
        "msg": "building",
        "phase": "",
        "phase_label": "",
        "phase_index": 0,
        "phase_total": 0,
    }
    assert task["result"] == {"ok": True}
    assert task["cancel_requested"] is True


def test_set_progress_persists_phase_fields(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata", profile="demo")
    store.set_progress(
        task_id, 52, "en-US",
        phase="locales", phase_label="上传本地化",
        phase_index=2, phase_total=2,
    )
    task = store.get(task_id)
    assert task["progress"]["pct"] == 52
    assert task["progress"]["phase"] == "locales"
    assert task["progress"]["phase_label"] == "上传本地化"
    assert task["progress"]["phase_index"] == 2
    assert task["progress"]["phase_total"] == 2
    restored = TaskStore(tmp_path / "tasks.db")
    assert restored.get(task_id)["progress"]["phase"] == "locales"


def test_legacy_progress_defaults_phase_fields(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build", profile="demo")
    store.set_progress(task_id, 10, "old")
    task = store.get(task_id)
    assert task["progress"]["phase"] == ""
    assert task["progress"]["phase_index"] == 0
    assert task["progress"]["phase_total"] == 0


def test_task_store_creates_missing_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "state" / "tasks.db"
    assert not db_path.parent.exists()

    store = TaskStore(db_path)
    task_id = store.create("update")
    store.append_log(task_id, "hello")

    assert db_path.exists()
    assert db_path.parent.is_dir()
    assert store.get(task_id)["logs"] == ["hello"]


def test_append_logs_soft_fails_when_connect_broken(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("update")

    def boom():
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(store, "_open_configured_connection", boom)

    assert store.append_logs(task_id, ["pip line"]) is False
    assert store._db_write_failures >= 1
    assert f"task_id={task_id}" in store._last_db_error
    assert "operation=append_logs" in store._last_db_error


def test_set_progress_soft_fails_when_connect_broken(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("update")

    def boom():
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(store, "_open_configured_connection", boom)

    assert store.set_progress(task_id, 10, "downloading") is False


def test_open_configured_connection_rejects_directory_path_as_database(tmp_path):
    db_path = tmp_path / "tasks.db"
    db_path.mkdir()
    store = TaskStore.__new__(TaskStore)
    store._db_path = db_path
    store._last_db_error = ""
    store._db_write_failures = 0

    with pytest.raises(sqlite3.OperationalError, match="directory"):
        store._open_configured_connection()


def test_sqlite_busy_writer_does_not_block_state_readers(tmp_path):
    """Regression: Python lock must not wrap SQLite busy waits (UI freeze)."""
    import sqlite3
    import threading
    import time

    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    task_id = store.create("build", profile="p")

    ready = threading.Event()
    release = threading.Event()

    def blocker() -> None:
        conn = sqlite3.connect(str(db_path), timeout=1)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE task_runs SET updated_at = ? WHERE id = ?", ("x", task_id))
        ready.set()
        release.wait(5)
        conn.rollback()
        conn.close()

    threading.Thread(target=blocker, daemon=True).start()
    assert ready.wait(2)

    results: dict[str, float] = {}

    def writer() -> None:
        started = time.perf_counter()
        store.append_logs(task_id, ["while-busy"])
        results["append"] = time.perf_counter() - started

    def reader() -> None:
        time.sleep(0.05)
        started = time.perf_counter()
        assert store.get_state(task_id) is not None
        store.list_recent_states(5)
        results["read"] = time.perf_counter() - started

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for thread in threads:
        thread.start()
    time.sleep(0.2)
    # Reader must finish while writer is still waiting on the DB lock.
    assert "read" in results
    assert results["read"] < 0.1
    release.set()
    for thread in threads:
        thread.join(5)
    assert results["append"] >= 0.05


def test_count_logs_without_loading_messages(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build")
    store.append_logs(task_id, ["a", "b", "c"])
    assert store.count_logs(task_id) == 3
    assert store.get_state(task_id)["logs"] == []


def test_append_logs_trims_to_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("ASC_WEB_TASK_LOG_LIMIT", "5")
    store = TaskStore(tmp_path / "tasks.db")
    tid = store.create("build")
    store.append_logs(tid, [f"L{i}" for i in range(1, 9)])
    logs = store.get_logs_after(tid, 0)
    assert len(logs) == 5
    assert logs[0]["message"] == "L4"  # keep newest 5; original seq retained
    assert logs[-1]["message"] == "L8"
    assert store.count_logs(tid) == 5
    store.close()


def test_concurrent_append_logs_single_writer_preserves_all_lines(tmp_path):
    import threading

    store = TaskStore(tmp_path / "tasks.db")
    tid = store.create("build")
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(50):
                store.append_logs(tid, [f"w{n}-{i}"])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    store.close()  # drain
    assert not errors
    assert store.count_logs(tid) == 200  # 4*50


def test_create_waits_until_visible_to_get_state(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    tid = store.create("build", profile="demo")
    state = store.get_state(tid)
    assert state is not None
    assert state["id"] == tid
    assert state["status"] == TaskStatus.PENDING
    assert state["profile"] == "demo"
    store.close()


def test_terminal_status_timeout_confirms_single_pending_write(tmp_path, monkeypatch):
    import threading
    import time

    from asc.reporting import make_web_reporter
    from asc.web.task_runner import finalize_task

    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata")
    store.set_status(task_id, TaskStatus.RUNNING)
    store._WRITE_WAIT_TIMEOUT_SEC = 0.08
    reporter = make_web_reporter(store, task_id, "metadata")
    entered = threading.Event()
    release = threading.Event()
    status_ops: list[object] = []
    original_run_batch = store._writer_run_batch

    def blocked_batch(ops):
        terminal_ops = [
            op
            for op in ops
            if op.kind == "set_status"
            and op.payload.get("status") == TaskStatus.DONE.value
        ]
        if terminal_ops and not entered.is_set():
            entered.set()
            assert release.wait(2)
        status_ops.extend(terminal_ops)
        return original_run_batch(ops)

    monkeypatch.setattr(store, "_writer_run_batch", blocked_batch)
    outcome: list[bool] = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            finalize_task(
                store,
                reporter,
                task_id,
                TaskStatus.DONE,
                {"success": True, "uploaded": 2},
            )
        )
    )
    worker.start()
    assert entered.wait(1)
    time.sleep(0.1)
    release.set()
    worker.join(1)
    store.flush()

    assert outcome == [True]
    assert len(status_ops) == 1
    assert store.get(task_id)["status"] == TaskStatus.DONE
    result = store.get(task_id)["result"]
    assert result["success"] is True
    assert result["uploaded"] == 2
    assert result["_asc_terminal_recovery"]["status"] == "done"
    store.close()


def test_terminal_status_timeout_abandons_unconfirmed_write(tmp_path, monkeypatch):
    import threading
    import time

    from asc.reporting import make_web_reporter
    from asc.web import task_runner

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(task_runner, "TERMINAL_STATUS_CONFIRM_TIMEOUT_SEC", 0.04)
    task_id = store.create("iap-review-screenshots")
    store.set_status(task_id, TaskStatus.RUNNING)
    store._WRITE_WAIT_TIMEOUT_SEC = 0.08
    reporter = make_web_reporter(store, task_id, "iap-review-screenshots")
    entered = threading.Event()
    release = threading.Event()
    status_ops: list[object] = []
    original_run_batch = store._writer_run_batch

    def blocked_batch(ops):
        terminal_ops = [op for op in ops if op.kind == "set_status"]
        if terminal_ops and not entered.is_set():
            entered.set()
            assert release.wait(2)
        status_ops.extend(terminal_ops)
        return original_run_batch(ops)

    monkeypatch.setattr(store, "_writer_run_batch", blocked_batch)
    payload = {
        "success": False,
        "uploaded": 1,
        "skipped": 2,
        "failed": 1,
        "failures": [{"productId": "coins_100", "error": "denied"}],
    }
    outcome: list[bool] = []
    started = time.perf_counter()
    worker = threading.Thread(
        target=lambda: outcome.append(
            task_runner.finalize_task(
                store,
                reporter,
                task_id,
                TaskStatus.ERROR,
                payload,
            )
        )
    )
    worker.start()
    assert entered.wait(1)
    worker.join(1)
    elapsed = time.perf_counter() - started
    assert outcome == [False]
    assert elapsed < 0.5
    release.set()
    store.flush()

    task = store.get(task_id)
    assert len(status_ops) == 1
    assert task["status"] == TaskStatus.RUNNING
    assert task["result"]["uploaded"] == 1
    assert task["result"]["failures"] == payload["failures"]
    assert "terminal_write_uncertainty" in task["result"]
    store.close()


def test_abandoned_done_write_cannot_overwrite_canceled_terminal(
    tmp_path, monkeypatch
):
    import json
    import sqlite3
    import threading

    from asc.reporting import make_web_reporter
    from asc.web import task_runner

    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    monkeypatch.setattr(task_runner, "TERMINAL_STATUS_CONFIRM_TIMEOUT_SEC", 0.04)
    task_id = store.create("metadata")
    store.set_status(task_id, TaskStatus.RUNNING)
    store._WRITE_WAIT_TIMEOUT_SEC = 0.08
    reporter = make_web_reporter(store, task_id, "metadata")
    entered = threading.Event()
    release = threading.Event()
    original_run_batch = store._writer_run_batch

    def blocked_batch(ops):
        if any(op.kind == "set_status" for op in ops) and not entered.is_set():
            entered.set()
            assert release.wait(2)
        return original_run_batch(ops)

    monkeypatch.setattr(store, "_writer_run_batch", blocked_batch)
    outcome: list[bool] = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            task_runner.finalize_task(
                store,
                reporter,
                task_id,
                TaskStatus.DONE,
                {"success": True, "uploaded": 1},
            )
        )
    )
    worker.start()
    assert entered.wait(1)
    worker.join(1)
    assert outcome == [False]

    canceled = {"success": False, "canceled": True}
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE task_runs SET status = ?, result_json = ? WHERE id = ?",
            (TaskStatus.CANCELED.value, json.dumps(canceled), task_id),
        )
    release.set()
    store.flush()

    task = store.get(task_id)
    assert task["status"] == TaskStatus.CANCELED
    assert task["result"] == canceled
    store.close()


def test_terminal_timeout_waits_for_commit_after_abandon_window(
    tmp_path, monkeypatch
):
    """Writer commits inside the settle window: finalize confirms the status."""
    import threading
    import time

    from asc.reporting import make_web_reporter
    from asc.web import task_runner

    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata")
    store.set_status(task_id, TaskStatus.RUNNING)
    store._WRITE_WAIT_TIMEOUT_SEC = 0.08
    monkeypatch.setattr(task_runner, "TERMINAL_STATUS_CONFIRM_TIMEOUT_SEC", 0.04)
    reporter = make_web_reporter(store, task_id, "metadata")
    update_executed = threading.Event()
    original_apply = store._apply_op

    def block_after_update(conn, op):
        result = original_apply(conn, op)
        if (
            op.kind == "set_status"
            and op.payload.get("status") == TaskStatus.DONE.value
        ):
            update_executed.set()
            threading.Event().wait(0.15)
        return result

    monkeypatch.setattr(store, "_apply_op", block_after_update)
    started = time.perf_counter()
    outcome = task_runner.finalize_task_outcome(
        store,
        reporter,
        task_id,
        TaskStatus.DONE,
        {"success": True, "uploaded": 1},
    )
    elapsed = time.perf_counter() - started
    store.flush()

    assert update_executed.is_set()
    assert bool(outcome) is True
    assert outcome.persisted is True
    assert outcome.blocked is False
    assert elapsed < 0.5
    task = store.get(task_id)
    assert task["status"] == TaskStatus.DONE
    assert "terminal_write_uncertainty" not in task["result"]
    store.close()


def test_terminal_write_pending_commit_is_not_blocked(tmp_path, monkeypatch):
    """A claimed but uncommitted status is recoverable, not published success."""
    import threading
    import time

    from asc.reporting import make_web_reporter
    from asc.web import task_runner
    from asc.web.task_runner import TerminalWriteState

    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata")
    store.set_status(task_id, TaskStatus.RUNNING)
    store._WRITE_WAIT_TIMEOUT_SEC = 0.08
    monkeypatch.setattr(task_runner, "TERMINAL_STATUS_CONFIRM_TIMEOUT_SEC", 0.04)
    reporter = make_web_reporter(store, task_id, "metadata")
    update_executed = threading.Event()
    release = threading.Event()
    original_apply = store._apply_op

    def block_after_update(conn, op):
        result = original_apply(conn, op)
        if (
            op.kind == "set_status"
            and op.payload.get("status") == TaskStatus.DONE.value
        ):
            update_executed.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(store, "_apply_op", block_after_update)
    started = time.perf_counter()
    outcome = task_runner.finalize_task_outcome(
        store,
        reporter,
        task_id,
        TaskStatus.DONE,
        {"success": True, "uploaded": 1},
    )
    elapsed = time.perf_counter() - started

    assert update_executed.is_set()
    assert outcome.state is TerminalWriteState.PENDING_COMMIT
    assert outcome.blocked is False
    assert outcome.persisted is False
    assert outcome.recovery_confirmed is True
    assert bool(outcome) is False
    # Bounded handoff: no unbounded wait on the blocked writer.
    assert elapsed < 0.6

    release.set()
    store.flush()
    task = store.get(task_id)
    assert task["status"] == TaskStatus.DONE
    assert "terminal_write_uncertainty" not in task["result"]
    store.close()


def test_claimed_terminal_commit_failure_recovers_expected_status_and_result(
    tmp_path, monkeypatch
):
    import sqlite3
    from contextlib import contextmanager

    from asc.reporting import make_web_reporter
    from asc.web import task_runner
    from asc.web.task_runner import TerminalWriteState

    db_path = tmp_path / "commit-failure.db"
    store = TaskStore(db_path)
    task_id = store.create("metadata")
    store.set_status(task_id, TaskStatus.RUNNING)
    reporter = make_web_reporter(store, task_id, "metadata")
    original_connection = store._connection

    class TrackingConnection:
        def __init__(self, connection):
            self._connection = connection
            self.terminal_status_written = False

        def execute(self, sql, parameters=()):
            if sql.lstrip().startswith("UPDATE task_runs SET status ="):
                self.terminal_status_written = True
            return self._connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self._connection, name)

    @contextmanager
    def fail_terminal_commit(*, write=False):
        with original_connection(write=write) as connection:
            tracked = TrackingConnection(connection)
            yield tracked
            if tracked.terminal_status_written:
                raise sqlite3.OperationalError("injected terminal commit failure")

    monkeypatch.setattr(store, "_connection", fail_terminal_commit)
    outcome = task_runner.finalize_task_outcome(
        store,
        reporter,
        task_id,
        TaskStatus.DONE,
        {"success": True, "uploaded": 7},
    )

    assert outcome.state is TerminalWriteState.BLOCKED
    assert bool(outcome) is False
    current = store.get_state(task_id)
    assert current["status"] == TaskStatus.RUNNING
    assert current["result"]["success"] is True
    assert current["result"]["uploaded"] == 7
    assert current["result"]["_asc_terminal_recovery"]["status"] == "done"

    monkeypatch.setattr(store, "_connection", original_connection)
    store.close()
    recovered = TaskStore(db_path)
    task = recovered.get(task_id)
    assert task["status"] == TaskStatus.DONE
    assert task["result"]["success"] is True
    assert task["result"]["uploaded"] == 7
    recovered.close()


def test_terminal_write_blocked_when_writer_never_claimed_op(tmp_path, monkeypatch):
    """Abandon wins the gate: the op is definitely skipped, so finalize is blocked."""
    import threading
    import time

    from asc.reporting import make_web_reporter
    from asc.web import task_runner
    from asc.web.task_runner import TerminalWriteState

    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata")
    store.set_status(task_id, TaskStatus.RUNNING)
    store._WRITE_WAIT_TIMEOUT_SEC = 0.08
    monkeypatch.setattr(task_runner, "TERMINAL_STATUS_CONFIRM_TIMEOUT_SEC", 0.04)
    reporter = make_web_reporter(store, task_id, "metadata")
    entered = threading.Event()
    release = threading.Event()
    original_run_batch = store._writer_run_batch

    def blocked_batch(ops):
        if any(op.kind == "set_status" for op in ops) and not entered.is_set():
            entered.set()
            assert release.wait(3)
        return original_run_batch(ops)

    monkeypatch.setattr(store, "_writer_run_batch", blocked_batch)
    outcome_box: list = []
    worker = threading.Thread(
        target=lambda: outcome_box.append(
            task_runner.finalize_task_outcome(
                store,
                reporter,
                task_id,
                TaskStatus.DONE,
                {"success": True, "uploaded": 1},
            )
        )
    )
    started = time.perf_counter()
    worker.start()
    assert entered.wait(2)
    worker.join(2)
    elapsed = time.perf_counter() - started

    outcome = outcome_box[0]
    assert outcome.state is TerminalWriteState.BLOCKED
    assert bool(outcome) is False
    assert elapsed < 0.5

    release.set()
    store.flush()
    task = store.get(task_id)
    assert task["status"] == TaskStatus.RUNNING
    assert "terminal_write_uncertainty" in task["result"]
    store.close()


def test_same_terminal_status_retry_preserves_completion_timestamps(tmp_path):
    """Idempotent same-terminal writes must not advance completed_at/updated_at."""
    import time

    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata")
    store.set_result(task_id, {"success": True})
    assert store.set_status(task_id, TaskStatus.DONE) is True
    first = store.get_state(task_id)

    time.sleep(0.01)
    assert store.set_status(task_id, TaskStatus.DONE) is True
    second = store.get_state(task_id)

    assert second["completed_at"] == first["completed_at"]
    assert second["updated_at"] == first["updated_at"]
    assert second["status"] == TaskStatus.DONE
    store.close()


def test_writer_base_exception_settles_ops_and_fails_fast(
    tmp_path, monkeypatch, capsys
):
    """A writer killed by BaseException must not leave callers waiting 30s."""
    import threading
    import time

    class WriterKilled(BaseException):
        pass

    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata")
    entered = threading.Event()
    release = threading.Event()
    original_run_batch = store._writer_run_batch

    def killer(ops):
        if any(op.kind == "set_result" for op in ops) and not entered.is_set():
            entered.set()
            assert release.wait(3)
            raise WriterKilled("writer thread terminated")
        return original_run_batch(ops)

    monkeypatch.setattr(store, "_writer_run_batch", killer)
    current: list = []

    def critical_write() -> None:
        try:
            current.append(store.set_result(task_id, {"attempt": 1}))
        except BaseException as exc:  # noqa: BLE001
            current.append(exc)

    first = threading.Thread(target=critical_write)
    first.start()
    assert entered.wait(2)

    queued: list = []
    second = threading.Thread(
        target=lambda: queued.append(store.append_logs(task_id, ["queued line"]))
    )
    second.start()
    threading.Event().wait(0.15)
    release.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert isinstance(current[0], sqlite3.Error)
    assert queued == [False]
    assert store._writer_stop.is_set()

    started = time.perf_counter()
    with pytest.raises(sqlite3.Error):
        store.set_result(task_id, {"attempt": 2})
    assert time.perf_counter() - started < 0.5

    started = time.perf_counter()
    store.flush()
    store.close()
    assert time.perf_counter() - started < 0.5
    assert store._write_q.unfinished_tasks == 0

    err = capsys.readouterr().err
    assert f"task_id={task_id}" in err
    assert "operation=" in err
    assert str(tmp_path / "tasks.db") in err


@pytest.mark.parametrize("winner", [TaskStatus.CANCELED, TaskStatus.ERROR])
def test_sqlite_first_terminal_wins_and_same_terminal_is_idempotent(
    tmp_path, winner
):
    store = TaskStore(tmp_path / f"{winner.value}.db")
    task_id = store.create("metadata")
    winner_result = {
        "success": False,
        "canceled": winner == TaskStatus.CANCELED,
        "error": winner.value,
    }
    store.set_result(task_id, winner_result)
    assert store.set_status(task_id, winner) is True

    assert store.set_result_if_nonterminal(
        task_id,
        {"success": True, "uploaded": 1},
    ) is False
    assert store.set_status(task_id, TaskStatus.DONE) is False
    assert store.set_status(task_id, winner) is True

    task = store.get(task_id)
    assert task["status"] == winner
    assert task["result"] == winner_result
    store.close()


def test_writer_runtime_error_settles_batch_and_keeps_writer_alive(
    tmp_path, monkeypatch, capsys
):
    import time

    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata")
    store._WRITE_WAIT_TIMEOUT_SEC = 0.2
    original_apply = store._apply_op
    failed_once = False

    def fail_first_result(conn, op):
        nonlocal failed_once
        if op.kind == "set_result" and not failed_once:
            failed_once = True
            raise RuntimeError("injected writer failure")
        return original_apply(conn, op)

    monkeypatch.setattr(store, "_apply_op", fail_first_result)
    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="injected writer failure"):
        store.set_result(task_id, {"attempt": 1})
    assert time.perf_counter() - started < 0.5
    assert store._writer is not None and store._writer.is_alive()

    assert store.set_result(task_id, {"attempt": 2}) is True
    assert store.get(task_id)["result"] == {"attempt": 2}
    started = time.perf_counter()
    store.close()
    assert time.perf_counter() - started < 0.5
    assert store._write_q.unfinished_tasks == 0

    err = capsys.readouterr().err
    assert f"task_id={task_id}" in err
    assert "operation=set_result" in err
    assert str(tmp_path / "tasks.db") in err


def test_close_aborts_shutdown_enqueued_after_writer_dies(
    tmp_path, monkeypatch, capsys
):
    import sqlite3
    import time

    from asc.web.tasks import _WriteOp

    store = TaskStore(tmp_path / "close-race.db")
    store._WRITE_WAIT_TIMEOUT_SEC = 0.2
    original_put = store._write_q.put
    captured = []
    intercepted = False

    def stop_before_put(op, *args, **kwargs):
        nonlocal intercepted
        if op.kind == "shutdown" and not intercepted:
            intercepted = True
            captured.append(op)
            original_put(_WriteOp(kind="shutdown"))
            assert store._writer_stop.wait(0.5)
        return original_put(op, *args, **kwargs)

    monkeypatch.setattr(store._write_q, "put", stop_before_put)
    started = time.perf_counter()
    store.close()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.8
    assert captured and captured[0].settled.is_set()
    assert store._write_q.unfinished_tasks == 0
    assert "writer stopped during shutdown" in capsys.readouterr().err

    started = time.perf_counter()
    store.close()
    assert time.perf_counter() - started < 0.1
    with pytest.raises(sqlite3.Error, match="closed"):
        store.set_result("missing", {"success": False})


def test_close_aborts_shutdown_when_writer_dies_after_enqueue(
    tmp_path, monkeypatch
):
    import time
    from threading import Event

    from asc.web.tasks import _WriteOp

    store = TaskStore(tmp_path / "close-after-put.db")
    original_put = store._write_q.put
    stop = _WriteOp(kind="shutdown", done=Event())
    original_put(stop)
    assert stop.done.wait(0.5)
    assert store._writer_stop.is_set()

    class DiesAfterInitialCheck:
        def __init__(self):
            self.checks = 0

        def is_alive(self):
            self.checks += 1
            return self.checks == 1

        def join(self, timeout=None):
            return None

    captured = []

    def capture_put(op, *args, **kwargs):
        captured.append(op)
        return original_put(op, *args, **kwargs)

    store._writer = DiesAfterInitialCheck()
    store._writer_stop.clear()
    monkeypatch.setattr(store._write_q, "put", capture_put)
    started = time.perf_counter()
    store.close()

    assert time.perf_counter() - started < 0.8
    assert captured and captured[0].kind == "shutdown"
    assert captured[0].settled.is_set()
    assert store._write_q.unfinished_tasks == 0


def test_create_stores_replay_but_public_json_only_has_flag(tmp_path):
    from asc.web.task_runner import sanitize_replay
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    try:
        replay = sanitize_replay(
            "metadata",
            "myapp",
            False,
            {
                "csv_path": "data/appstore_info.csv",
                "issuer_id": "SECRET-ISSUER",
                "key_file": "/tmp/AuthKey_X.p8",
                "api_key": "sk-live",
            },
        )
        assert "issuer_id" not in replay["params"]
        assert "key_file" not in replay["params"]
        assert "api_key" not in replay["params"]
        task_id = store.create("metadata", profile="myapp", replay=replay)
        public = store.get_state(task_id)
        assert public["has_replay"] is True
        assert "replay" not in public
        assert "params" not in public
        stored = store.get_replay(task_id)
        assert stored["params"]["csv_path"] == "data/appstore_info.csv"
        assert "SECRET-ISSUER" not in str(stored)
    finally:
        store.close()


def test_list_failed_only_errors_and_prefers_cookie_profile(tmp_path):
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    try:
        a = store.create("metadata", profile="keep")
        b = store.create("build", profile="other")
        c = store.create("iap", profile="keep")
        store.set_status(a, TaskStatus.ERROR)
        store.set_status(b, TaskStatus.ERROR)
        store.set_status(c, TaskStatus.DONE)
        rows = store.list_failed(limit=50, prefer_profile="keep")
        assert [row["id"] for row in rows][0] == a
        assert all(row["status"] == TaskStatus.ERROR or row["status"] == "error" for row in rows)
        assert c not in [row["id"] for row in rows]
        assert all("params" not in row for row in rows)
    finally:
        store.close()


def test_legacy_row_without_replay_has_replay_false(tmp_path):
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    try:
        task_id = store.create("update", profile="system")
        assert store.get_state(task_id)["has_replay"] is False
        assert store.get_replay(task_id) is None
    finally:
        store.close()


def test_save_preserves_replay_json(tmp_path):
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    try:
        replay = {
            "kind": "metadata",
            "profile": "myapp",
            "verbose": False,
            "params": {"csv_path": "data/appstore_info.csv"},
        }
        task_id = store.create("metadata", profile="myapp", replay=replay)
        store._load_db(recover=False)
        store._save()
        stored = store.get_replay(task_id)
        assert stored is not None
        assert stored["params"]["csv_path"] == "data/appstore_info.csv"
        public = store.get_state(task_id)
        assert public["has_replay"] is True
        assert "replay" not in public
    finally:
        store.close()


def test_in_memory_store_keeps_replay_off_public_json():
    from asc.web.tasks import TaskStore

    store = TaskStore()
    replay = {"kind": "iap", "profile": "p", "verbose": False, "params": {"iap_file": "x.json"}}
    task_id = store.create("iap", profile="p", replay=replay)
    public = store.get_state(task_id)
    assert public["has_replay"] is True
    assert "replay" not in public
    assert store.get_replay(task_id)["params"]["iap_file"] == "x.json"


def test_sanitize_replay_truncates_text_and_filters_signing():
    from asc.web.task_runner import FORBIDDEN_REPLAY_KEYS, sanitize_replay

    assert "certificate" in FORBIDDEN_REPLAY_KEYS
    out = sanitize_replay(
        "whats-new",
        "myapp",
        True,
        {
            "text": "x" * 9000,
            "signing": "invalid",
            "Authorization": "Bearer secret",
            "certificate": "iPhone Distribution: Secret",
            "dry_run": True,
        },
    )
    assert out["kind"] == "whats-new"
    assert out["profile"] == "myapp"
    assert out["verbose"] is True
    assert len(out["params"]["text"]) == 8192
    assert "signing" not in out["params"]
    assert "Authorization" not in out["params"]
    assert "certificate" not in out["params"]
    assert out["params"]["dry_run"] is True
    allowed = sanitize_replay("build", "p", False, {"signing": "manual"})
    assert allowed["params"]["signing"] == "manual"


def test_task_kind_labels_include_translate_and_listing_pull():
    from asc.web.tasks import TASK_KIND_LABELS, TASK_KIND_RETRY_PATHS, TaskStore

    assert TASK_KIND_LABELS["whats-new-translate"] == "更新说明翻译"
    assert TASK_KIND_LABELS["listing-pull-screenshots"] == "拉取截图"
    assert TASK_KIND_LABELS["listing-compare"] == "商品页商店核对"
    assert TASK_KIND_RETRY_PATHS["listing-compare"] == "/listing"
    assert TASK_KIND_RETRY_PATHS["whats-new-translate"] == "/whats-new"
    assert TASK_KIND_RETRY_PATHS["listing-pull-screenshots"] == "/listing"
    assert TASK_KIND_RETRY_PATHS["iap-compare"] == "/iap"
    store = TaskStore()
    translate_id = store.create("whats-new-translate")
    pull_id = store.create("listing-pull-screenshots")
    compare_id = store.create("iap-compare")
    assert store.get(translate_id)["title"] == "更新说明翻译"
    assert store.get(translate_id)["retry_path"] == "/whats-new"
    assert store.get(pull_id)["title"] == "拉取截图"
    assert store.get(pull_id)["retry_path"] == "/listing"
    assert store.get(compare_id)["title"] == "内购商店核对"
    assert store.get(compare_id)["retry_path"] == "/iap"
