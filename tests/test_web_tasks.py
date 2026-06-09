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
    assert task["progress"] == {"pct": 80, "msg": "uploading"}
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
    assert store.get("task-1")["progress"] == {"pct": 0, "msg": "ok"}
