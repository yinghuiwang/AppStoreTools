# tests/test_web_tasks.py
from __future__ import annotations
import pytest
from asc.web.tasks import TaskStore, TaskStatus


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


def test_sqlite_list_recent_states_does_not_query_task_logs(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    task_ids = [store.create("build") for _ in range(3)]
    store.append_log(task_ids[2], "line")
    connect = store._connect
    statements = []

    def traced_connect():
        connection = connect()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(store, "_connect", traced_connect)

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
    import sqlite3

    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("update")

    def boom():
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(store, "_connect", boom)

    assert store.append_logs(task_id, ["pip line"]) is False
    assert store._db_write_failures >= 1


def test_set_progress_soft_fails_when_connect_broken(tmp_path, monkeypatch):
    import sqlite3

    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("update")

    def boom():
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(store, "_connect", boom)

    assert store.set_progress(task_id, 10, "downloading") is False


def test_connect_rejects_directory_path_as_database(tmp_path):
    import sqlite3

    db_path = tmp_path / "tasks.db"
    db_path.mkdir()
    store = TaskStore.__new__(TaskStore)
    store._db_path = db_path
    store._last_db_error = ""
    store._db_write_failures = 0

    with pytest.raises(sqlite3.OperationalError, match="directory"):
        store._connect()


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
