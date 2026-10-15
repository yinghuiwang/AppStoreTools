from __future__ import annotations

import threading
from pathlib import Path

import pytest

from asc.schedule import (
    ScheduleCorruptError,
    ScheduleError,
    ScheduleLockBusy,
    ScheduleLockTimeout,
    ScheduleTask,
    load_tasks,
    new_task_id,
    save_tasks,
    schedule_lock,
)


def _daily(task_id: str = "a1b2c3d4") -> ScheduleTask:
    return ScheduleTask(
        id=task_id,
        profile="myapp",
        enabled=True,
        kind="daily",
        time="09:30",
        timezone="Asia/Shanghai",
        next_run_at="2026-10-15T09:30:00+08:00",
        last_run_at="",
        last_error="",
        last_result="",
    )


def test_missing_file_is_zero_tasks(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    assert load_tasks(path) == []
    assert not path.exists()


@pytest.mark.parametrize("text", ["", "\n", "# comment\n", "tasks = []\n"])
def test_empty_documents_are_zero_tasks(tmp_path: Path, text: str):
    path = tmp_path / "schedules.toml"
    path.write_text(text, encoding="utf-8")
    assert load_tasks(path) == []


@pytest.mark.parametrize(
    "text",
    [
        "{",
        'note = "x"\n',
        '[tasks]\nid = "a1b2c3d4"\n',
        'tasks = "no"\n',
        "[[tasks]]\nid = \"a1b2c3d4\"\n",
        "[[tasks]]\n"
        'id = "a1b2c3d4"\nprofile = "myapp"\nenabled = true\nkind = "daily"\n'
        'time = "09:30"\ntimezone = "Asia/Shanghai"\n'
        'next_run_at = "2026-10-15T09:30:00+08:00"\n'
        'last_run_at = ""\nlast_error = ""\nlast_result = ""\nnote = "x"\n',
        "[[tasks]]\n"
        'id = "a1b2c3d4"\nprofile = "myapp"\nenabled = "true"\nkind = "daily"\n'
        'time = "09:30"\ntimezone = "Asia/Shanghai"\n'
        'next_run_at = "2026-10-15T09:30:00+08:00"\n'
        'last_run_at = ""\nlast_error = ""\nlast_result = ""\n',
        "[[tasks]]\n"
        'id = "a1b2c3d4"\nprofile = "myapp"\nenabled = true\nkind = "daily"\n'
        'time = "09:30"\ntimezone = "Not/AZone"\n'
        'next_run_at = "2026-10-15T09:30:00+08:00"\n'
        'last_run_at = ""\nlast_error = ""\nlast_result = ""\n',
        "[[tasks]]\n"
        'id = "a1b2c3d4"\nprofile = "myapp"\nenabled = true\nkind = "daily"\n'
        'time = "09:30"\ntimezone = "Asia/Shanghai"\n'
        'next_run_at = "2026-10-15T09:30:00Z"\n'
        'last_run_at = ""\nlast_error = ""\nlast_result = ""\n',
        "[[tasks]]\n"
        'id = "AAAAAAAA"\nprofile = "myapp"\nenabled = true\nkind = "daily"\n'
        'time = "9:30"\ntimezone = "Asia/Shanghai"\n'
        'next_run_at = "2026-10-15T09:30:00+08:00"\n'
        'last_run_at = ""\nlast_error = ""\nlast_result = ""\n',
        "[[tasks]]\n"
        'id = "a1b2c3d4"\nprofile = "myapp"\nenabled = true\nkind = "daily"\n'
        'time = "09:30"\ninterval_hours = 2\ntimezone = "Asia/Shanghai"\n'
        'next_run_at = "2026-10-15T09:30:00+08:00"\n'
        'last_run_at = ""\nlast_error = ""\nlast_result = ""\n',
        "[[tasks]]\n"
        'id = "a1b2c3d4"\nprofile = "myapp"\nenabled = true\nkind = "weekly"\n'
        'time = "09:30"\nweekdays = [4, 1]\ntimezone = "Asia/Shanghai"\n'
        'next_run_at = "2026-10-15T09:30:00+08:00"\n'
        'last_run_at = ""\nlast_error = ""\nlast_result = ""\n',
    ],
)
def test_corrupt_files_raise_and_keep_bytes(tmp_path: Path, text: str):
    path = tmp_path / "schedules.toml"
    path.write_text(text, encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ScheduleCorruptError) as exc:
        load_tasks(path)
    assert exc.value.code == "corrupt"
    assert path.read_bytes() == before


def test_round_trip_preserves_order_and_kind_fields(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    daily = _daily("a1b2c3d4")
    interval = ScheduleTask(
        id="b2c3d4e5",
        profile="myapp",
        enabled=True,
        kind="interval",
        time="09:30",
        timezone="Asia/Shanghai",
        next_run_at="2026-10-14T11:30:00+08:00",
        last_run_at="",
        last_error="",
        last_result="",
        interval_hours=2,
    )
    weekly = ScheduleTask(
        id="c3d4e5f6",
        profile="myapp",
        enabled=False,
        kind="weekly",
        time="09:30",
        timezone="Asia/Shanghai",
        next_run_at="2026-10-15T09:30:00+08:00",
        last_run_at="",
        last_error="",
        last_result="",
        weekdays=[1, 4],
    )
    save_tasks(path, [daily, interval, weekly])
    loaded = load_tasks(path)
    assert [item.id for item in loaded] == ["a1b2c3d4", "b2c3d4e5", "c3d4e5f6"]
    assert loaded[0].interval_hours is None and loaded[0].weekdays is None
    assert loaded[1].interval_hours == 2 and loaded[1].weekdays is None
    assert loaded[2].weekdays == [1, 4] and loaded[2].interval_hours is None
    assert [item.watch for item in loaded] == ["app_store", "app_store", "app_store"]
    text = path.read_text(encoding="utf-8")
    assert 'watch = "app_store"' in text.split("[[tasks]]")[1]
    assert "interval_hours" in text.split("[[tasks]]")[2]
    assert "weekdays" not in text.split("[[tasks]]")[2]
    assert "weekdays" in text.split("[[tasks]]")[3]
    assert "interval_hours" not in text.split("[[tasks]]")[3]


def test_replace_failure_keeps_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_daily()])
    before = path.read_bytes()

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr("asc.schedule.os.replace", boom)
    with pytest.raises(OSError):
        save_tasks(path, [_daily("ffffffff")])
    assert path.read_bytes() == before


def test_new_task_id_retries_collision():
    seen = iter(["a1b2c3d4", "a1b2c3d4", "b2c3d4e5"])
    assert new_task_id({"a1b2c3d4"}, rng=lambda: next(seen)) == "b2c3d4e5"


def test_nonblocking_lock_is_busy(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    started = threading.Event()
    release = threading.Event()

    def holder():
        with schedule_lock(path, blocking=True):
            started.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert started.wait(5)
    with pytest.raises(ScheduleLockBusy):
        with schedule_lock(path, blocking=False):
            pass
    assert not path.exists()
    release.set()
    thread.join(5)


def test_blocking_lock_times_out(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    started = threading.Event()
    release = threading.Event()

    def holder():
        with schedule_lock(path, blocking=True):
            started.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert started.wait(5)
    with pytest.raises(ScheduleLockTimeout) as exc:
        with schedule_lock(path, blocking=True, timeout=0.2):
            pass
    assert exc.value.code == "lock_timeout"
    release.set()
    thread.join(5)


def test_missing_fcntl_does_not_create_schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "schedules.toml"
    monkeypatch.setattr("asc.schedule._flock_module", lambda: None)
    with pytest.raises(ScheduleError) as exc:
        with schedule_lock(path, blocking=True):
            pass
    assert exc.value.code == "fcntl_unavailable"
    assert not path.exists()


def test_legacy_task_without_watch_defaults_to_app_store(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    path.write_text(
        "[[tasks]]\n"
        'id = "a1b2c3d4"\nprofile = "myapp"\nenabled = true\nkind = "daily"\n'
        'time = "09:30"\ntimezone = "Asia/Shanghai"\n'
        'next_run_at = "2026-10-15T09:30:00+08:00"\n'
        'last_run_at = ""\nlast_error = ""\nlast_result = ""\n',
        encoding="utf-8",
    )
    loaded = load_tasks(path)
    assert loaded[0].watch == "app_store"


def test_watch_testflight_round_trips(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    task = _daily()
    task.watch = "testflight"
    save_tasks(path, [task])
    assert load_tasks(path)[0].watch == "testflight"
    assert 'watch = "testflight"' in path.read_text(encoding="utf-8")


def test_invalid_watch_is_corrupt(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    path.write_text(
        "[[tasks]]\n"
        'id = "a1b2c3d4"\nprofile = "myapp"\nenabled = true\nkind = "daily"\n'
        'watch = "store"\ntime = "09:30"\ntimezone = "Asia/Shanghai"\n'
        'next_run_at = "2026-10-15T09:30:00+08:00"\n'
        'last_run_at = ""\nlast_error = ""\nlast_result = ""\n',
        encoding="utf-8",
    )
    with pytest.raises(ScheduleCorruptError):
        load_tasks(path)
