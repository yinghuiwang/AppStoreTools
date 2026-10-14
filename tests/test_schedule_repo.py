from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from asc.schedule import (
    ScheduleError,
    ScheduleNotFound,
    add_task,
    list_tasks,
    load_tasks,
    remove_task,
    set_enabled,
    update_task,
)

NOW = datetime(2026, 10, 14, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
ENV = {"TZ": "Asia/Shanghai"}


class FakeHeartbeat:
    def __init__(self, system: str = "darwin"):
        self._system = system
        self.plist = None
        self.crontab = ""
        self.fail_bootstrap = False
        self.crontab_fail_times = 0
        self.bootouts = []
        self.bootstraps = []
        self._plist_path = Path("/tmp/LaunchAgents/com.asc.schedule.plist")
        self._log_path = Path("/tmp/asc-home/schedule-tick.log")

    def system(self):
        return self._system

    def uid(self):
        return 501

    def plist_path(self):
        return self._plist_path

    def log_path(self):
        return self._log_path

    def read_plist(self):
        return self.plist

    def write_plist(self, data: bytes):
        self.plist = data

    def remove_plist(self):
        self.plist = None

    def bootout(self, domain, plist):
        self.bootouts.append((domain, plist))

    def bootstrap(self, domain, plist):
        self.bootstraps.append((domain, plist))
        if self.fail_bootstrap:
            raise RuntimeError("bootstrap failed")

    def read_crontab(self):
        return self.crontab

    def write_crontab(self, text: str):
        if self.crontab_fail_times:
            self.crontab_fail_times -= 1
            self.crontab = text
            raise RuntimeError("crontab failed")
        self.crontab = text


def lookup_ok(name):
    if name == "missing":
        return None
    return {"issuer_id": "", "key_id": "", "key_file": "", "app_id": ""}


def test_add_daily_on_exact_slot_is_next_day(tmp_path: Path):
    path = tmp_path / "nested" / "schedules.toml"
    backend = FakeHeartbeat()
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    created, installed = add_task(
        profile="myapp",
        kind="daily",
        time="09:30",
        schedule_path=path,
        now=datetime(2026, 10, 14, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        profile_lookup=lookup_ok,
        backend=backend,
        asc_path=asc.resolve(),
        environ=ENV,
    )
    assert installed is True
    assert created.enabled is True
    assert created.next_run_at == "2026-10-15T09:30:00+08:00"
    assert created.last_run_at == created.last_error == created.last_result == ""
    assert backend.plist is not None


def test_second_add_keeps_order_and_skips_install(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    backend = FakeHeartbeat()
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    kwargs = dict(
        schedule_path=path,
        now=NOW,
        profile_lookup=lookup_ok,
        backend=backend,
        asc_path=asc.resolve(),
        environ=ENV,
    )
    first, _ = add_task(profile="myapp", kind="daily", time="09:30", **kwargs)
    plist = backend.plist
    second, installed = add_task(profile="myapp", kind="interval", time="09:30", interval_hours=2, **kwargs)
    assert installed is False
    assert backend.plist == plist
    assert [item.id for item in list_tasks(schedule_path=path)] == [first.id, second.id]


def test_missing_profile_and_bad_timezone_do_not_install(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    backend = FakeHeartbeat()
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    with pytest.raises(ScheduleError) as exc:
        add_task(
            profile="missing",
            kind="daily",
            time="09:30",
            schedule_path=path,
            now=NOW,
            profile_lookup=lookup_ok,
            backend=backend,
            asc_path=asc.resolve(),
            environ=ENV,
        )
    assert exc.value.code == "profile"
    assert backend.bootstraps == []
    assert not path.exists()
    with pytest.raises(ScheduleError) as tz_exc:
        add_task(
            profile="myapp",
            kind="daily",
            time="09:30",
            schedule_path=path,
            now=NOW,
            profile_lookup=lookup_ok,
            backend=backend,
            asc_path=asc.resolve(),
            environ={"TZ": "Not/AZone"},
            localtime=tmp_path / "missing-localtime",
        )
    assert tz_exc.value.code == "timezone"
    assert backend.plist is None
    assert not path.exists()


def test_install_failure_does_not_write_tasks(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    backend = FakeHeartbeat()
    backend.fail_bootstrap = True
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    with pytest.raises(ScheduleError):
        add_task(
            profile="myapp",
            kind="daily",
            time="09:30",
            schedule_path=path,
            now=NOW,
            profile_lookup=lookup_ok,
            backend=backend,
            asc_path=asc.resolve(),
            environ=ENV,
        )
    assert not path.exists()


def test_enable_disable_remove_and_update(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    backend = FakeHeartbeat()
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    created, _ = add_task(
        profile="myapp",
        kind="daily",
        time="09:30",
        schedule_path=path,
        now=NOW,
        profile_lookup=lookup_ok,
        backend=backend,
        asc_path=asc.resolve(),
        environ=ENV,
    )
    before = path.read_bytes()
    again = set_enabled(created.id, True, schedule_path=path)
    assert path.read_bytes() == before
    assert again.next_run_at == created.next_run_at
    disabled = set_enabled(created.id, False, schedule_path=path)
    assert disabled.enabled is False
    assert disabled.next_run_at == created.next_run_at
    same_profile = update_task(
        created.id,
        profile="other",
        kind="daily",
        time="09:30",
        enabled=False,
        interval_hours=None,
        weekdays=None,
        schedule_path=path,
        now=NOW,
        profile_lookup=lookup_ok,
    )
    assert same_profile.profile == "other"
    assert same_profile.next_run_at == created.next_run_at
    moved = update_task(
        created.id,
        profile="other",
        kind="daily",
        time="18:00",
        enabled=False,
        interval_hours=None,
        weekdays=None,
        schedule_path=path,
        now=NOW,
        profile_lookup=lookup_ok,
    )
    assert moved.time == "18:00"
    assert moved.next_run_at != created.next_run_at
    assert moved.timezone == "Asia/Shanghai"
    bytes_before = path.read_bytes()
    with pytest.raises(ScheduleError) as exc:
        update_task(
            created.id,
            profile="other",
            kind="interval",
            time="18:00",
            enabled=False,
            interval_hours=2,
            weekdays=[1],
            schedule_path=path,
            now=NOW,
            profile_lookup=lookup_ok,
        )
    assert exc.value.code == "kind_fields"
    assert path.read_bytes() == bytes_before
    remove_task(created.id, schedule_path=path)
    assert load_tasks(path) == []
    assert backend.plist is not None
    with pytest.raises(ScheduleNotFound):
        remove_task(created.id, schedule_path=path)
