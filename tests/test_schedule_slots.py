from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from asc.schedule import (
    ScheduleError,
    ScheduleTask,
    capture_timezone,
    due_action,
    format_timestamp,
    next_slot,
    parse_hhmm,
    parse_weekdays,
)

SH = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")


def task(kind, when, **kwargs):
    return ScheduleTask(
        id="a1b2c3d4",
        profile="myapp",
        enabled=True,
        kind=kind,
        time="09:30",
        timezone=kwargs.pop("timezone", "Asia/Shanghai"),
        next_run_at=when,
        last_run_at="",
        last_error="",
        last_result="",
        **kwargs,
    )


def test_parse_hhmm_rejects_unpadded_and_seconds():
    assert parse_hhmm("09:30") == (9, 30)
    with pytest.raises(ScheduleError) as exc:
        parse_hhmm("9:30")
    assert exc.value.code == "time"
    with pytest.raises(ScheduleError):
        parse_hhmm("09:30:00")


def test_parse_weekdays_sorts_and_rejects_duplicates():
    assert parse_weekdays("4, 1") == [1, 4]
    for text in ("01", "0", "8", "1-4", "1,,4", "1,1", ""):
        with pytest.raises(ScheduleError) as exc:
            parse_weekdays(text)
        assert exc.value.code == "weekdays"


def test_daily_exact_slot_uses_next_day():
    now = datetime(2026, 10, 14, 9, 30, tzinfo=SH)
    slot = next_slot(task("daily", "2026-10-14T09:30:00+08:00"), now)
    assert format_timestamp(slot) == "2026-10-15T09:30:00+08:00"


def test_daily_later_today_stays_today():
    now = datetime(2026, 10, 14, 9, 0, tzinfo=SH)
    slot = next_slot(task("daily", "2026-10-14T09:30:00+08:00"), now)
    assert format_timestamp(slot) == "2026-10-14T09:30:00+08:00"


def test_interval_two_hours_has_full_clock_face():
    anchor = task("interval", "2026-10-14T00:00:00+08:00", interval_hours=2)
    now = datetime(2026, 10, 14, 0, 0, tzinfo=SH)
    found = []
    cursor = now
    while True:
        slot = next_slot(anchor, cursor)
        if slot.date() != now.date():
            break
        found.append(format_timestamp(slot)[11:16])
        cursor = slot
    assert found == [
        "01:30", "03:30", "05:30", "07:30", "09:30", "11:30",
        "13:30", "15:30", "17:30", "19:30", "21:30", "23:30",
    ]


def test_interval_created_at_10_00_is_11_30():
    now = datetime(2026, 10, 14, 10, 0, tzinfo=SH)
    slot = next_slot(task("interval", "2026-10-14T11:30:00+08:00", interval_hours=2), now)
    assert format_timestamp(slot) == "2026-10-14T11:30:00+08:00"


def test_interval_seven_hours_crosses_midnight():
    anchor = task("interval", "2026-10-14T23:30:00+08:00", interval_hours=7)
    now = datetime(2026, 10, 14, 23, 30, tzinfo=SH)
    slot = next_slot(anchor, now)
    assert format_timestamp(slot) == "2026-10-15T02:30:00+08:00"


def test_interval_after_wake_stays_on_clock_face():
    anchor = task("interval", "2026-10-14T11:30:00+08:00", interval_hours=2)
    now = datetime(2026, 10, 14, 12, 10, tzinfo=SH)
    slot = next_slot(anchor, now)
    assert format_timestamp(slot) == "2026-10-14T13:30:00+08:00"


def test_weekly_wednesday_10_00_lands_thursday():
    now = datetime(2026, 10, 14, 10, 0, tzinfo=SH)
    slot = next_slot(task("weekly", "2026-10-15T09:30:00+08:00", weekdays=[1, 4]), now)
    assert format_timestamp(slot) == "2026-10-15T09:30:00+08:00"


def test_weekly_exact_thursday_slot_goes_to_next_monday():
    now = datetime(2026, 10, 15, 9, 30, tzinfo=SH)
    slot = next_slot(task("weekly", "2026-10-15T09:30:00+08:00", weekdays=[1, 4]), now)
    assert format_timestamp(slot) == "2026-10-19T09:30:00+08:00"


def test_task_timezone_ignores_a_different_clock():
    now = datetime(2026, 10, 14, 1, 0, tzinfo=ZoneInfo("UTC"))
    item = task("daily", "2026-10-14T09:30:00+08:00", timezone="Asia/Shanghai")
    slot = next_slot(item, now)
    assert format_timestamp(slot) == "2026-10-14T09:30:00+08:00"


def test_spring_gap_skips_missing_wall_time():
    now = datetime(2026, 3, 8, 1, 0, tzinfo=NY)
    item = ScheduleTask(
        id="a1b2c3d4",
        profile="myapp",
        enabled=True,
        kind="daily",
        time="02:30",
        timezone="America/New_York",
        next_run_at="2026-03-09T02:30:00-04:00",
        last_run_at="",
        last_error="",
        last_result="",
    )
    slot = next_slot(item, now)
    assert format_timestamp(slot) == "2026-03-09T02:30:00-04:00"


def test_fall_back_uses_first_occurrence():
    now = datetime(2026, 11, 1, 1, 0, tzinfo=NY)
    item = ScheduleTask(
        id="a1b2c3d4",
        profile="myapp",
        enabled=True,
        kind="daily",
        time="01:30",
        timezone="America/New_York",
        next_run_at="2026-11-01T01:30:00-04:00",
        last_run_at="",
        last_error="",
        last_result="",
    )
    slot = next_slot(item, now)
    assert slot.fold == 0
    assert format_timestamp(slot) == "2026-11-01T01:30:00-04:00"


def test_due_action_boundary():
    planned = datetime(2026, 10, 14, 9, 30, tzinfo=SH)
    assert due_action(planned, datetime(2026, 10, 14, 9, 32, tzinfo=SH)) == "run"
    assert due_action(planned, datetime(2026, 10, 14, 9, 32, 1, tzinfo=SH)) == "skip"
    assert due_action(planned, planned) == "run"


def test_capture_timezone_prefers_valid_tz_then_localtime(tmp_path: Path):
    target = tmp_path / "zoneinfo" / "Asia" / "Shanghai"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "localtime"
    link.symlink_to(target)
    assert capture_timezone(environ={"TZ": "Europe/Berlin"}, localtime=link) == "Europe/Berlin"
    assert capture_timezone(environ={"TZ": ""}, localtime=link) == "Asia/Shanghai"
    assert capture_timezone(environ={"TZ": "Not/AZone"}, localtime=link) == "Asia/Shanghai"
    with pytest.raises(ScheduleError) as exc:
        capture_timezone(environ={"TZ": "Not/AZone"}, localtime=tmp_path / "missing")
    assert exc.value.code == "timezone"
