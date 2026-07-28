from __future__ import annotations

import time
from datetime import datetime

import pytest

from asc.web.dashboard import build_dashboard_summary
from asc.web.tasks import TaskStatus


NOW = datetime.fromisoformat("2026-07-21T12:00:00")


@pytest.fixture
def utc_plus_eight(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setenv("TZ", "UTC-8")
        time.tzset()
        yield
    time.tzset()


def task(kind, status, seconds, *, profile="myapp", created="2026-07-20T10:00:00"):
    return {
        "id": f"{kind}-{status}-{seconds}",
        "kind": kind,
        "title": kind,
        "profile": profile,
        "status": status,
        "created_at": created,
        "completed_at": "2026-07-20T10:10:00",
        "updated_at": "2026-07-20T10:10:00",
        "duration_seconds": seconds,
        "duration_label": f"{seconds}s",
        "progress": {"pct": 50, "msg": "working"},
        "retry_path": "/retry",
    }


def test_summary_counts_only_successful_tasks_as_savings():
    result = build_dashboard_summary(
        [task("metadata", "done", 600), task("build", "error", 120)],
        days=30,
        now=NOW,
    )

    assert result["metrics"] == {
        "saved_seconds": 1200,
        "success_rate": 50.0,
        "failed_seconds": 120,
        "running_count": 0,
        "active_count": 0,
        "completed_count": 2,
    }


def test_summary_clamps_negative_savings_to_zero():
    result = build_dashboard_summary([task("urls", "done", 900)], days=30, now=NOW)

    assert result["metrics"]["saved_seconds"] == 0


def test_summary_returns_none_success_rate_without_terminal_tasks():
    result = build_dashboard_summary([task("build", "running", 30)], days=30, now=NOW)

    assert result["metrics"]["success_rate"] is None
    assert result["metrics"]["running_count"] == 1


def test_summary_filters_by_date_profile_kind_and_status():
    tasks = [
        task("metadata", "done", 60, profile="myapp"),
        task("build", "done", 60, profile="other"),
        task("metadata", "error", 60, profile="myapp"),
        task("metadata", "done", 60, profile="myapp", created="2026-01-01T00:00:00"),
    ]

    result = build_dashboard_summary(
        tasks,
        days=30,
        profile="myapp",
        kind="metadata",
        status="done",
        now=NOW,
    )

    assert [item["id"] for item in result["tasks"]] == ["metadata-done-60"]


def test_summary_active_count_precedes_status_filter_and_display_limit():
    tasks = [
        task("metadata", "done", 60, profile="myapp"),
        task("metadata", "running", 61, profile="myapp"),
        task("metadata", "pending", 62, profile="myapp"),
        task("metadata", "running", 63, profile="other"),
        task("metadata", "running", 64, profile="myapp", created="2026-01-01T00:00:00"),
    ]

    result = build_dashboard_summary(
        tasks,
        days=30,
        profile="myapp",
        kind="metadata",
        status="done",
        task_limit=1,
        now=NOW,
    )

    assert [item["status"] for item in result["tasks"]] == ["done"]
    assert result["metrics"]["running_count"] == 0
    assert result["metrics"]["active_count"] == 2


@pytest.mark.parametrize("days", [7, 30, 90])
def test_summary_exposes_fixed_baselines(days):
    result = build_dashboard_summary([], days=days, now=NOW)

    assert result["baseline_minutes"]["metadata"] == 30
    assert result["range_days"] == days


def test_summary_skips_invalid_dates_and_normalizes_enum_statuses():
    invalid = task("metadata", "done", 60, created="not-a-date")
    invalid["id"] = "invalid"
    missing = task("metadata", "done", 60)
    missing.pop("created_at")
    missing["id"] = "missing"
    enum_task = task("metadata", TaskStatus.DONE, 60)
    enum_task["id"] = "enum"

    result = build_dashboard_summary(
        [invalid, missing, enum_task],
        days=30,
        status=TaskStatus.DONE,
        now=NOW,
    )

    assert [item["id"] for item in result["tasks"]] == ["enum"]
    assert result["tasks"][0]["status"] == "done"


def test_summary_unknown_kind_has_no_savings_and_does_not_mutate_input():
    source = task("unknown", TaskStatus.DONE, 10)
    original = dict(source)

    result = build_dashboard_summary([source], days=30, now=NOW)
    result["baseline_minutes"]["metadata"] = 999

    assert result["metrics"]["saved_seconds"] == 0
    assert source == original
    assert source["status"] is TaskStatus.DONE
    assert build_dashboard_summary([], days=30, now=NOW)["baseline_minutes"]["metadata"] == 30


@pytest.mark.parametrize(("task_limit", "expected_count"), [(0, 1), (101, 100)])
def test_summary_clamps_task_limit(task_limit, expected_count):
    tasks = [
        task("metadata", "done", index, created="2026-07-21T10:00:00")
        for index in range(101)
    ]

    result = build_dashboard_summary(tasks, days=30, now=NOW, task_limit=task_limit)

    assert len(result["tasks"]) == expected_count


def test_summary_compares_aware_created_at_with_naive_now():
    source = task("metadata", "done", 60, created="2026-07-20T10:00:00+08:00")

    result = build_dashboard_summary([source], days=30, now=NOW)

    assert [item["id"] for item in result["tasks"]] == ["metadata-done-60"]


def test_summary_includes_aware_timestamp_at_exact_cutoff():
    aware_now = datetime.fromisoformat("2026-07-21T20:00:00+08:00")
    source = task("metadata", "done", 60, created="2026-07-14T08:00:00-04:00")

    result = build_dashboard_summary([source], days=7, now=aware_now)

    assert [item["id"] for item in result["tasks"]] == ["metadata-done-60"]


@pytest.mark.parametrize("duration", [None, "not-a-number", -10, float("inf"), float("-inf")])
def test_summary_coerces_invalid_and_negative_durations_to_zero(duration):
    result = build_dashboard_summary([task("metadata", "done", duration)], days=30, now=NOW)

    assert result["metrics"]["saved_seconds"] == 1800


def test_summary_includes_aware_created_at_at_naive_local_cutoff(utc_plus_eight):
    local_now = datetime.fromisoformat("2026-07-21T20:00:00")
    source = task("metadata", "done", 60, created="2026-07-14T12:00:00+00:00")

    result = build_dashboard_summary([source], days=7, now=local_now)

    assert [item["id"] for item in result["tasks"]] == ["metadata-done-60"]


def test_summary_includes_naive_created_at_at_aware_cutoff(utc_plus_eight):
    aware_now = datetime.fromisoformat("2026-07-21T12:00:00+00:00")
    source = task("metadata", "done", 60, created="2026-07-14T20:00:00")

    result = build_dashboard_summary([source], days=7, now=aware_now)

    assert [item["id"] for item in result["tasks"]] == ["metadata-done-60"]
