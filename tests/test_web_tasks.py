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
