from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from asc.schedule import (
    WATCH_TESTFLIGHT,
    QueryOutcome,
    ReviewSnapshot,
    ScheduleTask,
    SendOutcome,
    format_last_result,
    load_tasks,
    review_result_notify_key,
    save_tasks,
    tick,
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


def _ok_send(sent):
    def send(text):
        sent.append(text)
        return SendOutcome(False, [], True)

    return send


def _query_from(snapshots):
    remaining = list(snapshots)

    def query(profile, watch="app_store"):
        snapshot = remaining.pop(0) if remaining else snapshots[-1]
        return QueryOutcome(format_last_result(snapshot), "", snapshot)

    return query


def _tick(path, now, query, sent):
    return tick(schedule_path=path, now=now, query=query, send=_ok_send(sent))


def test_store_approved_notifies_once_across_ticks(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])
    snapshot = ReviewSnapshot([("1.2.3", "待开发者发布")], [])
    query = _query_from([snapshot, snapshot])
    sent = []
    assert _tick(path, datetime(2026, 10, 14, 9, 32, tzinfo=SH), query, sent) == 0
    assert _tick(path, datetime(2026, 10, 14, 11, 32, tzinfo=SH), query, sent) == 0
    assert len(sent) == 1
    assert "1.2.3" in sent[0]
    saved = load_tasks(path)[0]
    assert saved.last_result
    assert saved.last_notified_result == review_result_notify_key(snapshot, "myapp")


def test_store_rejected_notifies_once_then_again_after_in_review(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])
    rejected = ReviewSnapshot([("1.2.3", "被拒")], [])
    reviewing = ReviewSnapshot([("1.2.3", "审核中")], [])
    query = _query_from([rejected, rejected, reviewing, rejected])
    sent = []
    nows = [
        datetime(2026, 10, 14, 9, 32, tzinfo=SH),
        datetime(2026, 10, 14, 11, 32, tzinfo=SH),
        datetime(2026, 10, 14, 13, 32, tzinfo=SH),
        datetime(2026, 10, 14, 15, 32, tzinfo=SH),
    ]
    for now in nows:
        assert _tick(path, now, query, sent) == 0
    assert len(sent) == 3
    assert "被拒" in sent[0]
    assert "审核中" in sent[1]
    assert "被拒" in sent[2]
    saved = load_tasks(path)[0]
    assert saved.last_notified_result == review_result_notify_key(rejected, "myapp")


def test_store_new_version_result_notifies_again(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])
    first = ReviewSnapshot([("1.2.3", "已通过")], [])
    second = ReviewSnapshot([("1.3.0", "已通过")], [])
    query = _query_from([first, second])
    sent = []
    assert _tick(path, datetime(2026, 10, 14, 9, 32, tzinfo=SH), query, sent) == 0
    assert _tick(path, datetime(2026, 10, 14, 11, 32, tzinfo=SH), query, sent) == 0
    assert len(sent) == 2
    assert "1.2.3" in sent[0]
    assert "1.3.0" in sent[1]


def test_in_review_still_notifies_every_tick(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])
    reviewing = ReviewSnapshot([("1.2.3", "等待审核")], [])
    query = _query_from([reviewing, reviewing])
    sent = []
    assert _tick(path, datetime(2026, 10, 14, 9, 32, tzinfo=SH), query, sent) == 0
    assert _tick(path, datetime(2026, 10, 14, 11, 32, tzinfo=SH), query, sent) == 0
    assert len(sent) == 2
    assert load_tasks(path)[0].last_notified_result == ""


def test_reloaded_state_does_not_resend_store_result(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    snapshot = ReviewSnapshot([("1.2.3", "被拒")], [])
    task = _task()
    task.last_notified_result = review_result_notify_key(snapshot, "myapp")
    save_tasks(path, [task])
    reloaded = load_tasks(path)
    save_tasks(path, reloaded)
    sent = []
    query = _query_from([snapshot])
    assert _tick(path, datetime(2026, 10, 14, 9, 32, tzinfo=SH), query, sent) == 0
    assert sent == []
    saved = load_tasks(path)[0]
    assert saved.last_notified_result == task.last_notified_result
    assert saved.last_result


def test_tf_approved_notifies_once_across_ticks(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task(watch=WATCH_TESTFLIGHT)])
    snapshot = ReviewSnapshot(
        [("123（External）", "Beta 已通过")],
        [],
        watch=WATCH_TESTFLIGHT,
    )
    query = _query_from([snapshot, snapshot])
    sent = []
    assert _tick(path, datetime(2026, 10, 14, 9, 32, tzinfo=SH), query, sent) == 0
    assert _tick(path, datetime(2026, 10, 14, 11, 32, tzinfo=SH), query, sent) == 0
    assert len(sent) == 1
    assert "123（External）" in sent[0]
    saved = load_tasks(path)[0]
    assert saved.last_notified_result == review_result_notify_key(snapshot, "myapp")


def test_tf_rejected_again_after_beta_review(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task(watch=WATCH_TESTFLIGHT)])
    rejected = ReviewSnapshot(
        [("123（External）", "Beta 被拒")],
        [],
        watch=WATCH_TESTFLIGHT,
    )
    reviewing = ReviewSnapshot(
        [("123（External）", "Beta 审核中")],
        [],
        watch=WATCH_TESTFLIGHT,
    )
    query = _query_from([rejected, reviewing, rejected])
    sent = []
    for now in (
        datetime(2026, 10, 14, 9, 32, tzinfo=SH),
        datetime(2026, 10, 14, 11, 32, tzinfo=SH),
        datetime(2026, 10, 14, 13, 32, tzinfo=SH),
    ):
        assert _tick(path, now, query, sent) == 0
    assert len(sent) == 3
    assert "Beta 被拒" in sent[0]
    assert "Beta 审核中" in sent[1]
    assert "Beta 被拒" in sent[2]


def test_tf_new_build_result_notifies_again(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task(watch=WATCH_TESTFLIGHT)])
    first = ReviewSnapshot(
        [("123（External）", "Beta 已通过")],
        [],
        watch=WATCH_TESTFLIGHT,
    )
    second = ReviewSnapshot(
        [("124（External）", "Beta 已通过")],
        [],
        watch=WATCH_TESTFLIGHT,
    )
    query = _query_from([first, second])
    sent = []
    assert _tick(path, datetime(2026, 10, 14, 9, 32, tzinfo=SH), query, sent) == 0
    assert _tick(path, datetime(2026, 10, 14, 11, 32, tzinfo=SH), query, sent) == 0
    assert len(sent) == 2
    assert "123（External）" in sent[0]
    assert "124（External）" in sent[1]


def test_tf_ready_for_testing_is_approved_result(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task(watch=WATCH_TESTFLIGHT)])
    snapshot = ReviewSnapshot([], ["123（External）"], watch=WATCH_TESTFLIGHT)
    query = _query_from([snapshot, snapshot])
    sent = []
    assert _tick(path, datetime(2026, 10, 14, 9, 32, tzinfo=SH), query, sent) == 0
    assert _tick(path, datetime(2026, 10, 14, 11, 32, tzinfo=SH), query, sent) == 0
    assert len(sent) == 1
    saved = load_tasks(path)[0]
    assert saved.last_notified_result == review_result_notify_key(snapshot, "myapp")


def test_tf_reloaded_state_does_not_resend(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    snapshot = ReviewSnapshot(
        [("123（External）", "Beta 被拒")],
        [],
        watch=WATCH_TESTFLIGHT,
    )
    task = _task(watch=WATCH_TESTFLIGHT)
    task.last_notified_result = review_result_notify_key(snapshot, "myapp")
    save_tasks(path, [task])
    sent = []
    assert _tick(path, datetime(2026, 10, 14, 9, 32, tzinfo=SH), _query_from([snapshot]), sent) == 0
    assert sent == []


def test_pending_then_ready_for_sale_is_same_approved_result(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])
    pending = ReviewSnapshot([("1.2.3", "待开发者发布")], [])
    on_sale = ReviewSnapshot([], ["1.2.3"])
    query = _query_from([pending, on_sale])
    sent = []
    assert _tick(path, datetime(2026, 10, 14, 9, 32, tzinfo=SH), query, sent) == 0
    assert _tick(path, datetime(2026, 10, 14, 11, 32, tzinfo=SH), query, sent) == 0
    assert len(sent) == 1


def test_failed_result_send_retries_next_tick(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task()])
    snapshot = ReviewSnapshot([("1.2.3", "被拒")], [])
    query = _query_from([snapshot, snapshot])
    sent = []

    def send(text):
        sent.append(text)
        if len(sent) == 1:
            return SendOutcome(False, ["feishu HTTP 500"], True)
        return SendOutcome(False, [], True)

    now1 = datetime(2026, 10, 14, 9, 32, tzinfo=SH)
    now2 = datetime(2026, 10, 14, 11, 32, tzinfo=SH)
    assert tick(schedule_path=path, now=now1, query=query, send=send) == 0
    assert load_tasks(path)[0].last_notified_result == ""
    assert tick(schedule_path=path, now=now2, query=query, send=send) == 0
    assert len(sent) == 2
    assert load_tasks(path)[0].last_notified_result == review_result_notify_key(
        snapshot, "myapp"
    )


def test_not_submitted_is_not_treated_as_result(tmp_path: Path):
    path = tmp_path / "schedules.toml"
    save_tasks(path, [_task(watch=WATCH_TESTFLIGHT)])
    snapshot = ReviewSnapshot(
        [("123（External）", "未送审")],
        [],
        watch=WATCH_TESTFLIGHT,
    )
    query = _query_from([snapshot, snapshot])
    sent = []
    assert _tick(path, datetime(2026, 10, 14, 9, 32, tzinfo=SH), query, sent) == 0
    assert _tick(path, datetime(2026, 10, 14, 11, 32, tzinfo=SH), query, sent) == 0
    assert len(sent) == 2
    assert load_tasks(path)[0].last_notified_result == ""
