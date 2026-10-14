import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from asc.schedule import (
    QueryOutcome,
    ReviewSnapshot,
    ScheduleNotFound,
    ScheduleTask,
    SendOutcome,
    load_tasks,
    run_task,
    save_tasks,
    schedule_lock,
    tick,
    user_message,
)

SH = ZoneInfo("Asia/Shanghai")


def _task(task_id="a1b2c3d4", profile="myapp", when="2026-10-14T09:30:00+08:00", **kwargs):
    return ScheduleTask(
        id=task_id,
        profile=profile,
        enabled=kwargs.pop("enabled", True),
        kind=kwargs.pop("kind", "interval"),
        time="09:30",
        timezone="Asia/Shanghai",
        next_run_at=when,
        last_run_at="",
        last_error="",
        last_result="",
        interval_hours=kwargs.pop("interval_hours", 2),
        **kwargs,
    )


def _ok_query(profile):
    return QueryOutcome("1.2.3 审核中", "", ReviewSnapshot([("1.2.3", "审核中")], []))


def _quiet_send(text):
    return SendOutcome(False, [], False)


def test_tick_writes_next_run_before_send(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])
    seen = {}

    def query(profile):
        return QueryOutcome("1.2.3 审核中", "", ReviewSnapshot([("1.2.3", "审核中")], []))

    def send(text):
        saved = load_tasks(path)[0]
        seen["next"] = saved.next_run_at
        seen["result"] = saved.last_result
        assert "应用：myapp" in text
        return SendOutcome(False, [], False)

    now = datetime(2026, 10, 14, 9, 32, tzinfo=SH)
    assert tick(schedule_path=path, now=now, query=query, send=send) == 0
    assert seen["next"] == "2026-10-14T11:30:00+08:00"
    assert seen["result"] == "1.2.3 审核中"


def test_tick_skip_at_121_seconds_does_not_query(tmp_path: Path, capsys):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])

    def query(profile):
        raise AssertionError("skipped task must not query")

    now = datetime(2026, 10, 14, 9, 32, 1, tzinfo=SH)
    assert tick(schedule_path=path, now=now, query=query, send=query) == 0
    saved = load_tasks(path)[0]
    assert saved.next_run_at == "2026-10-14T11:30:00+08:00"
    assert saved.last_run_at == saved.last_error == saved.last_result == ""
    assert capsys.readouterr().out == "a1b2c3d4 myapp skipped\n"


def test_tick_skip_stays_on_clock_face(tmp_path: Path, capsys):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task(when="2026-10-14T11:30:00+08:00")])
    now = datetime(2026, 10, 14, 12, 10, tzinfo=SH)
    assert tick(schedule_path=path, now=now, query=_ok_query, send=_ok_query) == 0
    assert load_tasks(path)[0].next_run_at == "2026-10-14T13:30:00+08:00"
    assert capsys.readouterr().out == "a1b2c3d4 myapp skipped\n"


def test_one_task_failure_does_not_stop_the_next(tmp_path: Path, capsys):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [
        _task("a1b2c3d4", "first"),
        _task("b2c3d4e5", "second"),
    ])
    calls = []

    def query(profile):
        calls.append(profile)
        if profile == "first":
            raise RuntimeError("boom")
        return _ok_query(profile)

    now = datetime(2026, 10, 14, 9, 32, tzinfo=SH)
    assert tick(schedule_path=path, now=now, query=query, send=_quiet_send) == 0
    assert calls == ["first", "second"]
    assert capsys.readouterr().out == "a1b2c3d4 first error\nb2c3d4e5 second ok\n"
    saved = load_tasks(path)
    assert saved[0].next_run_at == "2026-10-14T11:30:00+08:00"
    assert saved[0].last_result == "检查失败"
    assert saved[1].last_error == ""


def test_overlapping_tick_skips(tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("asc.i18n.LANG", "zh")
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])
    started = threading.Event()
    release = threading.Event()

    def holder():
        with schedule_lock(path, blocking=True):
            started.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert started.wait(5)

    def send(text):
        raise AssertionError("sent")

    now = datetime(2026, 10, 14, 9, 32, tzinfo=SH)
    assert tick(schedule_path=path, now=now, query=send, send=send) == 0
    assert "已有 tick 正在运行，本次跳过" in capsys.readouterr().err
    release.set()
    thread.join(5)
    monkeypatch.setattr("asc.i18n.LANG", "en")
    assert user_message("lock_busy") == "A schedule tick is already running; this one was skipped"


def test_corrupt_file_exits_1_without_send(tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("asc.i18n.LANG", "zh")
    path = tmp_path / "schedules.toml"
    path.write_text('tasks = "no"\n', encoding="utf-8")
    before = path.read_bytes()

    def send(text):
        raise AssertionError("sent")

    assert tick(schedule_path=path, query=send, send=send) == 1
    assert path.read_bytes() == before
    assert "调度文件已损坏" in capsys.readouterr().err


def test_run_keeps_next_and_updates_last_run(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task(enabled=False)])
    before = load_tasks(path)[0].next_run_at
    now = datetime(2026, 10, 14, 9, 32, tzinfo=SH)
    ran = run_task("a1b2c3d4", schedule_path=path, now=now, query=_ok_query, send=_quiet_send)
    assert ran.next_run_at == before
    assert ran.last_run_at == "2026-10-14T09:32:00+08:00"
    assert ran.enabled is False
    assert load_tasks(path)[0].next_run_at == before


def test_run_send_failure_records_error_without_moving_next(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])
    before = load_tasks(path)[0].next_run_at

    def send(text):
        return SendOutcome(False, ["feishu HTTP 500"], True)

    now = datetime(2026, 10, 14, 9, 32, tzinfo=SH)
    ran = run_task("a1b2c3d4", schedule_path=path, now=now, query=_ok_query, send=send)
    assert ran.next_run_at == before
    assert ran.last_error == "通知发送失败：feishu HTTP 500"
    assert load_tasks(path)[0].next_run_at == before


def test_run_unknown_id_does_not_send(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])

    def send(text):
        raise AssertionError("sent")

    with pytest.raises(ScheduleNotFound):
        run_task("ffffffff", schedule_path=path, query=_ok_query, send=send)


def test_successful_query_without_send_is_ok(tmp_path: Path, capsys):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])
    now = datetime(2026, 10, 14, 9, 32, tzinfo=SH)
    assert tick(schedule_path=path, now=now, query=_ok_query, send=_quiet_send) == 0
    saved = load_tasks(path)[0]
    assert saved.last_error == ""
    assert saved.last_result == "1.2.3 审核中"
    assert capsys.readouterr().out == "a1b2c3d4 myapp ok\n"


def test_tick_uses_one_now_for_every_last_run(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task("a1b2c3d4", "first"), _task("b2c3d4e5", "second")])
    now = datetime(2026, 10, 14, 9, 31, 8, tzinfo=SH)
    assert tick(schedule_path=path, now=now, query=_ok_query, send=_quiet_send) == 0
    saved = load_tasks(path)
    assert saved[0].last_run_at == saved[1].last_run_at == "2026-10-14T09:31:08+08:00"


def test_save_failure_does_not_send_current_task(tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task("a1b2c3d4", "first"), _task("b2c3d4e5", "second")])
    real_save = save_tasks
    calls = {"n": 0}

    def flaky(schedule_path, tasks):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk")
        real_save(schedule_path, tasks)

    monkeypatch.setattr("asc.schedule.save_tasks", flaky)
    sent = []

    def send(text):
        sent.append(text)
        return SendOutcome(False, [], False)

    now = datetime(2026, 10, 14, 9, 32, tzinfo=SH)
    assert tick(schedule_path=path, now=now, query=_ok_query, send=send) == 1
    assert len(sent) == 1
    assert "second" not in sent[0]
    assert "disk" in capsys.readouterr().err
    saved = load_tasks(path)
    assert saved[0].next_run_at == "2026-10-14T11:30:00+08:00"
    assert saved[1].next_run_at == "2026-10-14T09:30:00+08:00"


def test_missing_schedule_tree_exits_0(tmp_path: Path, capsys):
    path = tmp_path / "missing" / "schedules.toml"
    assert tick(schedule_path=path, query=_ok_query, send=_quiet_send) == 0
    assert not path.parent.exists()
    assert capsys.readouterr().out == ""


def test_fcntl_unavailable_exits_1(tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("asc.i18n.LANG", "zh")
    monkeypatch.setattr("asc.schedule._flock_module", lambda: None)
    path = tmp_path / "schedules.toml"
    assert tick(schedule_path=path, query=_ok_query, send=_quiet_send) == 1
    assert not path.exists()
    assert "fcntl" in capsys.readouterr().err
