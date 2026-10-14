import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from asc.cli import app
from asc.schedule import (
    QueryOutcome,
    ReviewSnapshot,
    ScheduleError,
    format_timestamp,
    load_tasks,
    save_tasks,
)

runner = CliRunner()


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


def _lookup(name):
    if name == "missing":
        return None
    return {"issuer_id": "", "key_id": "", "key_file": "", "app_id": ""}


def _ok_query(profile, **kwargs):
    return QueryOutcome("1.2.3 审核中", "", ReviewSnapshot([("1.2.3", "审核中")], []))


@pytest.fixture
def scheduled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "schedules.toml"
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    backend = FakeHeartbeat()
    monkeypatch.setattr("asc.schedule.default_schedule_path", lambda: path)
    monkeypatch.setattr("asc.schedule.default_profile_lookup", _lookup)
    monkeypatch.setattr("asc.schedule.query_review", _ok_query)
    monkeypatch.setattr("asc.commands.schedule_cmd.SystemHeartbeatBackend", lambda: backend)
    monkeypatch.setattr("asc.commands.schedule_cmd.resolve_asc_executable", lambda: asc.resolve())
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    monkeypatch.setattr("asc.i18n.LANG", "zh")
    return path, backend, asc


def _add(args, **kwargs):
    return runner.invoke(app, ["schedule", "add", *args], **kwargs)


def _text(result) -> str:
    return "\n".join([result.stdout or "", result.stderr or "", getattr(result, "output", "") or ""])


def test_add_help_accepts_timezone(scheduled):
    result = runner.invoke(app, ["schedule", "add", "--help"])
    assert result.exit_code == 0
    assert "--timezone" in result.stdout


def test_explicit_timezone_skips_capture(scheduled, monkeypatch: pytest.MonkeyPatch):
    path, _, _ = scheduled

    def boom(**kwargs):
        raise ScheduleError("timezone")

    monkeypatch.setattr("asc.schedule.capture_timezone", boom)
    monkeypatch.delenv("TZ", raising=False)
    result = _add(["--app", "myapp", "--daily", "--time", "09:30", "--timezone", "Asia/Shanghai"])
    assert result.exit_code == 0, _text(result)
    assert load_tasks(path)[0].timezone == "Asia/Shanghai"


def test_invalid_timezone_exits_without_capture(scheduled, monkeypatch: pytest.MonkeyPatch):
    path, _, _ = scheduled

    def boom(**kwargs):
        raise AssertionError("capture_timezone should not run")

    monkeypatch.setattr("asc.schedule.capture_timezone", boom)
    result = _add(["--app", "myapp", "--daily", "--time", "09:30", "--timezone", "Not/AZone"])
    assert result.exit_code == 1
    assert "无效的 IANA 时区：Not/AZone" in _text(result)
    assert not path.exists()
    monkeypatch.setattr("asc.i18n.LANG", "en")
    english = _add(["--app", "myapp", "--daily", "--time", "09:30", "--timezone", "Not/AZone"])
    assert english.exit_code == 1
    assert "Invalid IANA time zone: Not/AZone" in _text(english)


def test_omitted_timezone_still_uses_capture(scheduled, monkeypatch: pytest.MonkeyPatch):
    path, _, _ = scheduled
    monkeypatch.setattr("asc.schedule.capture_timezone", lambda **kwargs: "Europe/Berlin")
    result = _add(["--app", "myapp", "--daily", "--time", "09:30"])
    assert result.exit_code == 0, _text(result)
    assert load_tasks(path)[0].timezone == "Europe/Berlin"


def test_capture_failure_without_tty_mentions_timezone_flag(scheduled, monkeypatch: pytest.MonkeyPatch):
    path, _, _ = scheduled
    monkeypatch.setattr(
        "asc.schedule.capture_timezone",
        lambda **kwargs: (_ for _ in ()).throw(ScheduleError("timezone")),
    )
    monkeypatch.setattr("asc.commands.schedule_cmd._stdin_is_tty", lambda: False)
    result = _add(["--app", "myapp", "--daily", "--time", "09:30"])
    assert result.exit_code == 1
    text = _text(result)
    assert "无法确定 IANA 时区" in text
    assert "--timezone" in text
    assert not path.exists()
    monkeypatch.setattr("asc.i18n.LANG", "en")
    english = _add(["--app", "myapp", "--daily", "--time", "09:30"])
    assert "Could not determine an IANA time zone" in _text(english)
    assert "--timezone" in _text(english)


def test_tty_prompt_stores_one_chosen_timezone(scheduled, monkeypatch: pytest.MonkeyPatch):
    path, _, _ = scheduled
    monkeypatch.setattr(
        "asc.schedule.capture_timezone",
        lambda **kwargs: (_ for _ in ()).throw(ScheduleError("timezone")),
    )
    monkeypatch.setattr("asc.commands.schedule_cmd._stdin_is_tty", lambda: True)
    chosen = _add(["--app", "myapp", "--daily", "--time", "09:30"], input="Europe/Berlin\n")
    assert chosen.exit_code == 0, _text(chosen)
    assert load_tasks(path)[0].timezone == "Europe/Berlin"
    empty = _add(["--app", "myapp", "--daily", "--time", "09:30"], input="\n")
    assert empty.exit_code == 1
    assert "无法确定 IANA 时区" in _text(empty)
    assert "无效的 IANA 时区" not in _text(empty)
    assert "--timezone" not in _text(empty)
    invalid = _add(["--app", "myapp", "--daily", "--time", "09:30"], input="Not/AZone\n")
    assert invalid.exit_code == 1
    invalid_text = _text(invalid)
    assert "无法确定 IANA 时区" in invalid_text
    assert "无效的 IANA 时区：Not/AZone" in invalid_text
    assert [item.timezone for item in load_tasks(path)] == ["Europe/Berlin"]


def _task_id(result) -> str:
    match = re.search(r"\b([0-9a-f]{8})\b", result.stdout)
    assert match, result.stdout
    return match.group(1)


def test_add_requires_app(scheduled, monkeypatch: pytest.MonkeyPatch):
    path, _, _ = scheduled
    monkeypatch.setenv("_ASC_APP", "myapp")
    result = runner.invoke(app, ["schedule", "add", "--daily", "--time", "09:30"])
    assert result.exit_code != 0
    assert not path.exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--app", "myapp", "--daily", "--time", "9:30"],
        ["--app", "myapp", "--daily", "--time", "09:30:00"],
        ["--app", "myapp", "--every", "0", "--time", "09:30"],
        ["--app", "myapp", "--every", "-1", "--time", "09:30"],
        ["--app", "myapp", "--weekly", "01", "--time", "09:30"],
        ["--app", "myapp", "--weekly", "1,1", "--time", "09:30"],
        ["--app", "myapp", "--daily", "--every", "2", "--time", "09:30"],
        ["--app", "myapp", "--time", "09:30"],
    ],
)
def test_add_rejects_bad_schedule_fields(scheduled, args):
    path, _, _ = scheduled
    result = _add(args)
    assert result.exit_code == 1
    assert not path.exists()


def test_add_sorts_weekdays_and_accepts_padded_every(scheduled):
    path, _, _ = scheduled
    weekly = _add(["--app", "myapp", "--weekly", "4,1", "--time", "09:30"])
    assert weekly.exit_code == 0
    assert load_tasks(path)[0].weekdays == [1, 4]
    interval = _add(["--app", "myapp", "--every", "01", "--time", "09:30"])
    assert interval.exit_code == 0
    saved = load_tasks(path)[1]
    assert saved.kind == "interval"
    assert saved.interval_hours == 1


def test_unknown_profile_exits_1(scheduled):
    path, _, _ = scheduled
    result = _add(["--app", "missing", "--daily", "--time", "09:30"])
    assert result.exit_code == 1
    assert not path.exists()


def test_empty_profile_can_be_added(scheduled):
    result = _add(["--app", "myapp", "--daily", "--time", "09:30"])
    assert result.exit_code == 0
    assert re.search(r"\b[0-9a-f]{8}\b", result.stdout)
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", result.stdout)
    assert "心跳已安装" in result.stdout


def test_list_shows_compact_cycle_and_empty_message(scheduled, monkeypatch: pytest.MonkeyPatch):
    path, _, _ = scheduled
    empty = runner.invoke(app, ["schedule", "list"])
    assert empty.exit_code == 0
    assert "没有定时任务" in empty.stdout
    created = _add(["--app", "myapp", "--daily", "--time", "09:30"])
    task_id = _task_id(created)
    assert runner.invoke(app, ["schedule", "disable", task_id]).exit_code == 0
    listed = runner.invoke(app, ["schedule", "list"])
    assert listed.exit_code == 0
    assert task_id in listed.stdout
    assert "daily 09:30" in listed.stdout
    assert "停用" in listed.stdout
    monkeypatch.setattr("asc.i18n.LANG", "en")
    english = runner.invoke(app, ["schedule", "list"])
    assert "Next run" in english.stdout
    assert "disabled" in english.stdout


def test_enable_is_noop_and_remove_keeps_heartbeat(scheduled):
    path, backend, _ = scheduled
    created = _add(["--app", "myapp", "--daily", "--time", "09:30"])
    task_id = _task_id(created)
    before = path.read_bytes()
    again = runner.invoke(app, ["schedule", "enable", task_id])
    assert again.exit_code == 0
    assert path.read_bytes() == before
    missing = path.read_bytes()
    removed = runner.invoke(app, ["schedule", "remove", "ffffffff"])
    assert removed.exit_code == 1
    assert path.read_bytes() == missing
    assert runner.invoke(app, ["schedule", "remove", task_id]).exit_code == 0
    assert load_tasks(path) == []
    assert backend.plist is not None


def test_tick_corrupt_exits_1_and_query_error_exits_0(scheduled, monkeypatch: pytest.MonkeyPatch):
    path, _, _ = scheduled
    path.write_text('tasks = "no"\n', encoding="utf-8")
    corrupt = runner.invoke(app, ["schedule", "tick"])
    assert corrupt.exit_code == 1
    path.unlink()
    created = _add(["--app", "myapp", "--daily", "--time", "09:30"])
    assert created.exit_code == 0
    tasks = load_tasks(path)
    zone = ZoneInfo(tasks[0].timezone)
    due = datetime.now(zone) - timedelta(seconds=30)
    tasks[0].next_run_at = format_timestamp(due.replace(microsecond=0))
    save_tasks(path, tasks)

    def explode(profile, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("asc.schedule.query_review", explode)
    failed = runner.invoke(app, ["schedule", "tick"])
    assert failed.exit_code == 0
    assert "error" in failed.stdout


def test_run_error_keeps_next_run(scheduled, monkeypatch: pytest.MonkeyPatch):
    path, _, _ = scheduled
    created = _add(["--app", "myapp", "--daily", "--time", "09:30"])
    task_id = _task_id(created)
    before = load_tasks(path)[0].next_run_at

    def bad(profile, **kwargs):
        return QueryOutcome("检查失败", "凭证不完整", None)

    monkeypatch.setattr("asc.schedule.query_review", bad)
    result = runner.invoke(app, ["schedule", "run", task_id])
    assert result.exit_code == 1
    assert result.stdout.strip().endswith("error")
    assert load_tasks(path)[0].next_run_at == before


def test_install_uses_resolved_asc_and_rejects_other_argv(
    scheduled, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import plistlib

    from asc.schedule import resolve_asc_executable

    path, backend, asc = scheduled
    created = _add(["--app", "myapp", "--daily", "--time", "09:30"])
    assert created.exit_code == 0
    before = path.read_bytes()
    installed = runner.invoke(app, ["schedule", "install"])
    assert installed.exit_code == 0
    data = plistlib.loads(backend.plist)
    assert data["ProgramArguments"][0] == str(asc.resolve())
    isolated = tmp_path / "no-asc"
    isolated.mkdir()
    monkeypatch.setattr(sys, "executable", str(isolated / "python"))
    monkeypatch.setenv("PATH", str(isolated))
    monkeypatch.setattr("asc.commands.schedule_cmd.resolve_asc_executable", resolve_asc_executable)
    rejected = runner.invoke(app, ["schedule", "install"])
    assert rejected.exit_code == 1
    assert "请使用 asc 可执行文件安装心跳，不能用 python -m asc" in rejected.stderr
    assert path.read_bytes() == before
