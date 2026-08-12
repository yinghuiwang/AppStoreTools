"""TaskReporter progress for URL set + asc update phases."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from asc.commands.metadata import (
    _update_app_info_field_core,
    _update_version_field_core,
    _url_phase_plan,
)
from asc.commands.update_cmd import _update_core, _update_phase_plan
from asc.reporting import TaskReporter


class RecordingSink:
    def __init__(self):
        self.logs = []
        self.progress_events = []

    def on_log(self, message, *, level="info"):
        self.logs.append((level, message))

    def on_progress(self, *, pct, msg, phase, phase_label, phase_index, phase_total):
        self.progress_events.append({
            "pct": pct,
            "msg": msg,
            "phase": phase,
            "phase_label": phase_label,
            "phase_index": phase_index,
            "phase_total": phase_total,
        })


class UrlFakeAPI:
    def __init__(self):
        self.calls = []
        self.version_id = "ver_1"
        self.app_info_id = "appinfo_1"
        self.ver_locs = {
            "zh-Hans": {"id": "vloc_zh", "attributes": {"locale": "zh-Hans"}},
            "en-US": {"id": "vloc_en", "attributes": {"locale": "en-US"}},
        }
        self.info_locs = {
            "zh-Hans": {"id": "iloc_zh", "attributes": {"locale": "zh-Hans"}},
            "en-US": {"id": "iloc_en", "attributes": {"locale": "en-US"}},
        }
        self.updated_ver_locs: dict[str, dict] = {}
        self.updated_info_locs: dict[str, dict] = {}

    def get_editable_version(self, app_id):
        return {
            "id": self.version_id,
            "attributes": {
                "versionString": "1.0",
                "appStoreState": "PREPARE_FOR_SUBMISSION",
            },
        }

    def get_version_localizations(self, version_id):
        return [
            {"id": loc["id"], "attributes": {"locale": locale}}
            for locale, loc in self.ver_locs.items()
        ]

    def get_app_infos(self, app_id):
        return [{"id": self.app_info_id, "attributes": {}}]

    def get_app_info_localizations(self, app_info_id):
        return [
            {"id": loc["id"], "attributes": {"locale": locale}}
            for locale, loc in self.info_locs.items()
        ]

    def update_version_localization(self, loc_id, attrs):
        self.updated_ver_locs[loc_id] = attrs

    def update_app_info_localization(self, loc_id, attrs):
        self.updated_info_locs[loc_id] = attrs


def test_url_phase_plan_update_100():
    assert _url_phase_plan() == [("update", 100, "更新")]


def test_update_version_field_reports_per_locale_progress():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    api = UrlFakeAPI()

    _update_version_field_core(
        api,
        "app1",
        "supportUrl",
        "Support URL",
        "https://example.com/support",
        reporter=reporter,
    )

    phases = {e["phase"] for e in sink.progress_events}
    assert phases == {"update"}
    assert sink.progress_events[-1]["pct"] == 100
    locale_msgs = [
        e for e in sink.progress_events
        if e["msg"] and "/" in e["msg"] and e["phase"] == "update"
    ]
    assert len(locale_msgs) == 2  # locales × 1 field
    assert locale_msgs[0]["pct"] == 50
    assert locale_msgs[1]["pct"] == 100
    pcts = [e["pct"] for e in sink.progress_events]
    assert pcts == sorted(pcts)
    joined = "\n".join(msg for _, msg in sink.logs)
    assert "Support URL" in joined or "supportUrl" in joined or "已更新" in joined


def test_update_app_info_field_reports_per_locale_progress():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    api = UrlFakeAPI()

    _update_app_info_field_core(
        api,
        "app1",
        "privacyPolicyUrl",
        "Privacy Policy URL",
        "https://example.com/privacy",
        locales=["en-US"],
        reporter=reporter,
    )

    locale_msgs = [
        e for e in sink.progress_events
        if e["msg"] and "/" in e["msg"] and e["phase"] == "update"
    ]
    assert len(locale_msgs) == 1
    assert locale_msgs[-1]["pct"] == 100
    assert "iloc_en" in api.updated_info_locs
    assert "iloc_zh" not in api.updated_info_locs


def test_url_source_has_no_progress_protocol():
    root = Path(__file__).resolve().parents[1]
    meta = (root / "src/asc/commands/metadata.py").read_text(encoding="utf-8")
    assert "[PROGRESS:" not in meta
    update_src = (root / "src/asc/commands/update_cmd.py").read_text(encoding="utf-8")
    assert "[PROGRESS:" not in update_src


def test_urls_web_starter_uses_start_background_task():
    import inspect
    from asc.web import routes_api

    starter = inspect.getsource(routes_api._start_urls_task)
    assert "start_background_task" in starter
    assert "_PROGRESS_RE" not in starter
    assert "reporter=" in starter
    assert "capture_stdout_to_queue" not in starter
    # route delegates to starter
    route = inspect.getsource(routes_api.urls_set)
    assert "_start_urls_task" in route
    assert "_parse_urls_locales" in route
    assert "api.urls_locales_required" in route


def test_parse_urls_locales():
    from asc.web.routes_api import _parse_urls_locales

    assert _parse_urls_locales("") == []
    assert _parse_urls_locales("   ") == []
    assert _parse_urls_locales("en-US") == ["en-US"]
    assert _parse_urls_locales("en-US, zh-Hans") == ["en-US", "zh-Hans"]
    assert _parse_urls_locales("en-US,, ,zh-Hans,") == ["en-US", "zh-Hans"]


def test_urls_set_rejects_empty_locales(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    from asc.web.server import create_app
    from asc.web.tasks import TaskStore
    from asc.web import routes_api

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    client = TestClient(create_app())
    client.cookies.set("asc_profile", "testapp")
    client.cookies.set("asc_lang", "en")

    with patch("asc.web.routes_api._start_urls_task") as starter:
        resp = client.post(
            "/api/urls/set",
            data={
                "field": "supportUrl",
                "url": "https://example.com/support",
                "locales": "",
            },
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "Select at least one target locale"
    starter.assert_not_called()

    with patch("asc.web.routes_api._start_urls_task") as starter:
        resp = client.post(
            "/api/urls/set",
            data={
                "field": "supportUrl",
                "url": "https://example.com/support",
                "locales": "  ,  ",
            },
        )
    assert resp.status_code == 400
    starter.assert_not_called()


def test_urls_set_passes_selected_locales(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    from asc.web.server import create_app
    from asc.web.tasks import TaskStore
    from asc.web import routes_api

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    client = TestClient(create_app())
    client.cookies.set("asc_profile", "testapp")

    with patch("asc.web.routes_api._start_urls_task", return_value="task-1") as starter:
        resp = client.post(
            "/api/urls/set",
            data={
                "field": "marketingUrl",
                "url": "https://example.com",
                "locales": "en-US, zh-Hans",
                "dry_run": "on",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "task-1"
    starter.assert_called_once()
    kwargs = starter.call_args.kwargs
    assert kwargs["profile"] == "testapp"
    assert kwargs["field"] == "marketingUrl"
    assert kwargs["url"] == "https://example.com"
    assert kwargs["locales"] == ["en-US", "zh-Hans"]
    assert kwargs["dry_run"] is True


def test_urls_page_has_locale_checkbox_ui():
    from fastapi.testclient import TestClient

    from asc.web.server import create_app

    client = TestClient(create_app())
    resp = client.get("/urls")
    assert resp.status_code == 200
    html = resp.text
    assert "selectedLocales" in html
    assert "selectAllLocales" in html
    assert "deselectAllLocales" in html
    assert "data-locale-checkboxes" in html
    assert "urls.locales_required" in html
    assert "x-init=\"checkEnv()\"" in html
    # No longer a free-text locales input
    assert 'id="locales-input"' not in html
    assert "localesText" not in html


def test_start_urls_task_passes_locale_list_to_core(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch

    from asc.web import routes_api
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    captured = {}

    def fake_run(store_arg, *, task_id=None, run=None, **kwargs):
        reporter = MagicMock()
        reporter.failed = False
        run(reporter, MagicMock(is_set=MagicMock(return_value=False)))
        return task_id

    def fake_core(api, app_id, field, label, url, locales, dry_run, **kwargs):
        captured["locales"] = locales
        captured["field"] = field
        captured["url"] = url

    with patch("asc.web.routes_api.start_background_task", side_effect=fake_run), \
            patch("asc.web.routes_api.Config", return_value=MagicMock()), \
            patch("asc.web.routes_api.enforce_config_guard"), \
            patch(
                "asc.web.routes_api.make_api_from_config",
                return_value=(MagicMock(), "app1"),
            ), \
            patch(
                "asc.commands.metadata._update_version_field_core",
                side_effect=fake_core,
            ):
        routes_api._start_urls_task(
            profile="testapp",
            field="supportUrl",
            url="https://example.com/support",
            locales=["en-US"],
            dry_run=True,
        )

    assert captured["locales"] == ["en-US"]
    assert captured["field"] == "supportUrl"
    assert captured["url"] == "https://example.com/support"


def test_update_phase_plan_download_70_install_30():
    assert _update_phase_plan() == [
        ("download", 70, "下载"),
        ("install", 30, "安装"),
    ]


def test_update_core_maps_download_install_pct():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    commit = "a" * 40

    with patch("asc.commands.update_cmd._is_editable", return_value=False), \
            patch("asc.commands.update_cmd._current_version", return_value="0.1.0"), \
            patch("asc.commands.update_cmd._latest_version_from_github", return_value="0.1.1"), \
            patch("asc.commands.update_cmd._resolve_git_ref_commit", return_value=commit), \
            patch("asc.commands.update_cmd._install_git_ref") as install:
        installed = _update_core(version=None, branch=None, yes=True, reporter=reporter)

    assert installed
    assert installed.changed is True
    install.assert_called_once()
    pcts = [e["pct"] for e in sink.progress_events]
    assert pcts == sorted(pcts)
    download_pcts = [e["pct"] for e in sink.progress_events if e["phase"] == "download"]
    install_pcts = [e["pct"] for e in sink.progress_events if e["phase"] == "install"]
    assert download_pcts
    assert download_pcts[-1] == 70
    assert install_pcts
    assert install_pcts[0] == 70
    assert install_pcts[-1] == 100
    assert sink.progress_events[-1]["pct"] == 100
    joined = "\n".join(msg for _, msg in sink.logs)
    assert "0.1.1" in joined or "updated" in joined.lower() or "Done" in joined


def test_update_web_starter_uses_start_background_task():
    import inspect
    from asc.web import routes_api

    starter = inspect.getsource(routes_api._start_update_task)
    assert "start_background_task" in starter
    assert "schedule_restart" in starter
    assert "restarting" in starter
    assert "defer_install=True" in starter
    assert "reporter.flush()" in starter
    assert "_PROGRESS_RE" not in starter
    assert "io.StringIO" not in starter
    assert "reporter" in starter
    route = inspect.getsource(routes_api.update_run)
    assert "_start_update_task" in route


def test_update_web_starter_flushes_before_finish(tmp_path, monkeypatch):
    """Buffered logs must flush before DONE so SSE clients see the full log."""
    from unittest.mock import MagicMock, patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import routes_api
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    flush_order: list[str] = []

    def fake_run(store_arg, *, task_id=None, run=None, **kwargs):
        reporter = MagicMock()
        reporter.failed = False

        def flush(*, failed=None):
            flush_order.append("flush")

        reporter.flush.side_effect = flush
        original_finalize = routes_api.finalize_task_outcome

        def finish_wrapper(store_arg, reporter_arg, tid, status, result):
            finalized = original_finalize(store_arg, reporter_arg, tid, status, result)
            flush_order.append("finish")
            return finalized

        with patch.object(
            routes_api, "finalize_task_outcome", side_effect=finish_wrapper
        ):
            run(reporter, MagicMock(is_set=MagicMock(return_value=False)))
        return task_id

    with patch("asc.web.routes_api.start_background_task", side_effect=fake_run), \
            patch(
                "asc.commands.update_cmd._update_core",
                return_value=UpdateResult(changed=False),
            ):
        routes_api._start_update_task()

    assert flush_order == ["flush", "finish"]


def test_update_web_starter_schedules_restart_after_install(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    order: list[str] = []
    marker_calls: list[str] = []
    marker_kwargs: list[dict] = []

    def fake_run(store_arg, *, task_id=None, run=None, **kwargs):
        reporter = MagicMock()
        reporter.failed = False
        run(reporter, MagicMock(is_set=MagicMock(return_value=False)))
        return task_id

    original_finalize = routes_api.finalize_task_outcome

    def tracked_finish(store_arg, reporter_arg, tid, status, result):
        finalized = original_finalize(store_arg, reporter_arg, tid, status, result)
        order.append("finish")
        return finalized

    def tracked_restart(**kwargs):
        order.append("restart")
        return {
            "status": "scheduled",
            "delay": kwargs.get("delay", 1.5),
            "url": "http://127.0.0.1:8080",
        }

    def tracked_marker(task_id, **kwargs):
        order.append("marker")
        marker_calls.append(task_id)
        marker_kwargs.append(kwargs)
        return tmp_path / "update_restart.json"

    outcome = UpdateResult(
        changed=True,
        deferred=True,
        install_ref="v0.1.25",
        commit="a" * 40,
    )
    with patch("asc.web.routes_api.start_background_task", side_effect=fake_run), \
            patch("asc.commands.update_cmd._update_core", return_value=outcome) as update_core, \
            patch.object(
                routes_api, "finalize_task_outcome", side_effect=tracked_finish
            ), \
            patch("asc.web.daemon.schedule_restart", side_effect=tracked_restart) as restart, \
            patch("asc.web.daemon.write_update_restart_marker", side_effect=tracked_marker), \
            patch("time.sleep"):
        task_id = routes_api._start_update_task(version="0.1.25")

    update_core.assert_called_once()
    assert update_core.call_args.kwargs.get("defer_install") is True
    restart.assert_called_once_with(
        delay=1.5,
        install_ref="v0.1.25",
        commit="a" * 40,
        task_id=task_id,
    )
    assert order == ["finish", "marker", "restart"]
    assert marker_calls == [task_id]
    assert marker_kwargs[0]["pending_install"] is True
    assert marker_kwargs[0]["installed"] is False
    task = store.get(task_id)
    assert task["status"] == TaskStatus.DONE
    assert task["result"]["success"] is True
    assert task["result"]["installed"] is False
    assert task["result"]["pending_install"] is True
    assert task["result"]["restarting"] is True


def test_update_web_starter_blocks_restart_when_terminal_write_fails(tmp_path, monkeypatch):
    """Restart side effects require a durable result and terminal status."""
    from unittest.mock import MagicMock, patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import routes_api
    from asc.web.task_runner import (
        TerminalWriteOutcome,
        TerminalWriteState,
    )
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    order: list[str] = []

    def fake_run(store_arg, *, task_id=None, run=None, **kwargs):
        reporter = MagicMock()
        reporter.failed = False
        result = run(reporter, MagicMock(is_set=MagicMock(return_value=False)))
        assert result["success"] is True
        assert result.get("restart_blocked") is not True
        assert result.get("restarting") is True
        return task_id

    def failed_finalize(*args, **kwargs):
        order.append("finish")
        return TerminalWriteOutcome(
            state=TerminalWriteState.BLOCKED,
            status=TaskStatus.DONE,
            detail="injected terminal write failure",
        )

    def tracked_restart(**kwargs):
        order.append("restart")
        return {"status": "scheduled", "delay": 1.5, "url": "http://127.0.0.1:8080"}

    def tracked_marker(task_id, **kwargs):
        order.append("marker")
        return tmp_path / "update_restart.json"

    outcome = UpdateResult(
        changed=True,
        deferred=True,
        install_ref="v0.1.25",
        commit="b" * 40,
    )
    with patch("asc.web.routes_api.start_background_task", side_effect=fake_run), \
            patch("asc.commands.update_cmd._update_core", return_value=outcome), \
            patch.object(
                routes_api, "finalize_task_outcome", side_effect=failed_finalize
            ), \
            patch("asc.web.daemon.schedule_restart", side_effect=tracked_restart) as restart, \
            patch("asc.web.daemon.write_update_restart_marker", side_effect=tracked_marker), \
            patch("time.sleep"):
        routes_api._start_update_task(version="0.1.25")

    restart.assert_not_called()
    assert order == ["finish", "finish"]


def test_unchanged_update_commit_failure_recovers_done_without_side_effects(
    tmp_path, monkeypatch
):
    import sqlite3
    from contextlib import contextmanager
    from unittest.mock import MagicMock, patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus, TaskStore

    db_path = tmp_path / "unchanged-update.db"
    store = TaskStore(db_path)
    monkeypatch.setattr(routes_api, "_task_store", store)
    original_connection = store._connection

    class TrackingConnection:
        def __init__(self, connection):
            self._connection = connection
            self.terminal_status_written = False

        def execute(self, sql, parameters=()):
            if sql.lstrip().startswith("UPDATE task_runs SET status ="):
                self.terminal_status_written = True
            return self._connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self._connection, name)

    @contextmanager
    def fail_terminal_commit(*, write=False):
        with original_connection(write=write) as connection:
            tracked = TrackingConnection(connection)
            yield tracked
            if tracked.terminal_status_written:
                raise sqlite3.OperationalError("injected update terminal commit failure")

    def run_inline(store_arg, *, task_id=None, run=None, **kwargs):
        reporter = MagicMock()
        reporter.failed = False
        reporter.flush.return_value = True
        run(reporter, MagicMock(is_set=MagicMock(return_value=False)))
        return task_id

    monkeypatch.setattr(store, "_connection", fail_terminal_commit)
    with patch("asc.web.routes_api.start_background_task", side_effect=run_inline), \
            patch(
                "asc.commands.update_cmd._update_core",
                return_value=UpdateResult(changed=False),
            ), \
            patch.object(routes_api, "_notify_task_finished") as notify, \
            patch("asc.web.daemon.write_update_restart_marker") as marker, \
            patch("asc.web.daemon.schedule_restart") as restart:
        task_id = routes_api._start_update_task()

    current = store.get_state(task_id)
    assert current["status"] == TaskStatus.PENDING
    assert current["result"]["success"] is True
    assert current["result"]["installed"] is False
    assert current["result"]["pending_install"] is False
    assert current["result"]["_asc_terminal_recovery"]["status"] == "done"
    notify.assert_not_called()
    marker.assert_not_called()
    restart.assert_not_called()

    monkeypatch.setattr(store, "_connection", original_connection)
    store.close()
    recovered = TaskStore(db_path)
    task = recovered.get(task_id)
    assert task["status"] == TaskStatus.DONE
    assert task["result"]["success"] is True
    assert task["result"]["installed"] is False
    assert task["result"]["pending_install"] is False
    assert task["result"].get("restarted") is not True
    recovered.close()


def test_update_retries_done_after_transient_final_flush(tmp_path, monkeypatch):
    """Successful update + soft final flush must retry to DONE, not ERROR."""
    from unittest.mock import patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import routes_api
    from asc.web.task_runner import _execute_task
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "update-flush-retry.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    original_append_logs = store.append_logs
    soft_failed = False

    def soft_fail_once(task_id, lines):
        nonlocal soft_failed
        if not soft_failed:
            soft_failed = True
            return False
        return original_append_logs(task_id, lines)

    monkeypatch.setattr(store, "append_logs", soft_fail_once)

    def run_inline(
        store_arg, *, task_id=None, run=None, kind=None, verbose=False, **kwargs
    ):
        _execute_task(store_arg, task_id, kind, run, verbose=verbose)
        return task_id

    outcome = UpdateResult(
        changed=True,
        deferred=True,
        install_ref="v0.1.25",
        commit="c" * 40,
    )
    with patch("asc.web.routes_api.start_background_task", side_effect=run_inline), \
            patch("asc.commands.update_cmd._update_core", return_value=outcome), \
            patch("asc.web.daemon.write_update_restart_marker") as marker, \
            patch(
                "asc.web.daemon.schedule_restart",
                return_value={
                    "status": "scheduled",
                    "delay": 1.5,
                    "url": "http://127.0.0.1:8080",
                },
            ) as restart, \
            patch("time.sleep"):
        task_id = routes_api._start_update_task(version="0.1.25")

    task = store.get(task_id)
    assert soft_failed is True
    assert task["status"] == TaskStatus.DONE
    assert task["result"]["success"] is True
    assert task["result"].get("restart_blocked") is not True
    assert task["result"]["pending_install"] is True
    assert task["result"]["install_ref"] == "v0.1.25"
    assert task["result"]["commit"] == "c" * 40
    marker.assert_called_once()
    restart.assert_called_once()
    store.close()


def test_update_finalize_soft_block_stays_non_terminal_without_restart(
    tmp_path, monkeypatch
):
    """Soft finalize BLOCKED must not fabricate ERROR/restart_blocked or restart."""
    from unittest.mock import patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import routes_api
    from asc.web.task_runner import (
        TerminalWriteOutcome,
        TerminalWriteState,
        _execute_task,
    )
    from asc.web.tasks import TaskStatus, TaskStore

    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    monkeypatch.setattr(routes_api, "_task_store", store)

    def run_inline(store_arg, *, task_id=None, run=None, kind=None, verbose=False, **kwargs):
        _execute_task(store_arg, task_id, kind, run, verbose=verbose)
        return task_id

    outcome = UpdateResult(
        changed=True,
        deferred=False,
        install_ref="v0.1.25",
        commit="c" * 40,
    )
    blocked_outcome = TerminalWriteOutcome(
        state=TerminalWriteState.BLOCKED,
        status=TaskStatus.DONE,
        detail="injected terminal write failure",
    )
    with patch("asc.web.routes_api.start_background_task", side_effect=run_inline), \
            patch("asc.commands.update_cmd._update_core", return_value=outcome), \
            patch.object(
                routes_api, "finalize_task_outcome", return_value=blocked_outcome
            ), \
            patch("asc.web.daemon.write_update_restart_marker") as marker, \
            patch("asc.web.daemon.schedule_restart") as restart:
        task_id = routes_api._start_update_task(version="0.1.25")

    task = store.get(task_id)
    # Update's finalize stayed soft-blocked (no side effects). Worker may still
    # publish DONE via its own finalize; never ERROR/restart_blocked.
    assert task["status"] != TaskStatus.ERROR
    assert task["result"]["success"] is True
    assert task["result"].get("restart_blocked") is not True
    assert task["result"]["install_ref"] == "v0.1.25"
    marker.assert_not_called()
    restart.assert_not_called()

    store.close()
    recovered = TaskStore(db_path)
    recovered_task = recovered.get(task_id)
    assert recovered_task["status"] != TaskStatus.ERROR
    assert recovered_task["result"]["success"] is True
    assert recovered_task["result"].get("restart_blocked") is not True
    recovered.close()


def test_update_restart_exception_keeps_done_and_persists_failure_details(
    tmp_path, monkeypatch
):
    from unittest.mock import patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import routes_api
    from asc.web.task_runner import _execute_task
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)

    def run_inline(store_arg, *, task_id=None, run=None, kind=None, verbose=False, **kwargs):
        _execute_task(store_arg, task_id, kind, run, verbose=verbose)
        return task_id

    outcome = UpdateResult(
        changed=True,
        deferred=True,
        install_ref="v0.1.25",
        commit="d" * 40,
    )
    with patch("asc.web.routes_api.start_background_task", side_effect=run_inline), \
            patch("asc.commands.update_cmd._update_core", return_value=outcome), \
            patch("asc.web.daemon.write_update_restart_marker") as marker, \
            patch(
                "asc.web.daemon.schedule_restart",
                side_effect=RuntimeError("restart exploded"),
            ), \
            patch("asc.web.daemon.clear_update_restart_marker") as clear_marker, \
            patch("time.sleep"):
        task_id = routes_api._start_update_task(version="0.1.25")

    task = store.get(task_id)
    assert task["status"] == TaskStatus.DONE
    assert task["result"]["success"] is True
    assert task["result"]["restarting"] is False
    assert task["result"]["pending_install"] is False
    assert "restart exploded" in task["result"]["restart_error"]
    assert any("restart exploded" in line for line in task["logs"])
    assert any("Traceback" in line for line in task["logs"])
    marker.assert_called_once()
    clear_marker.assert_called_once()


def test_update_timeout_after_status_update_still_runs_restart_side_effects(
    tmp_path, monkeypatch
):
    import threading
    from unittest.mock import patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import routes_api, task_runner
    from asc.web.task_runner import _execute_task
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    store._WRITE_WAIT_TIMEOUT_SEC = 0.08
    monkeypatch.setattr(task_runner, "TERMINAL_STATUS_CONFIRM_TIMEOUT_SEC", 0.04)
    original_apply = store._apply_op
    update_executed = threading.Event()

    def block_after_done_update(conn, op):
        result = original_apply(conn, op)
        if (
            op.kind == "set_status"
            and op.payload.get("status") == TaskStatus.DONE.value
        ):
            update_executed.set()
            threading.Event().wait(0.15)
        return result

    monkeypatch.setattr(store, "_apply_op", block_after_done_update)

    def run_inline(
        store_arg,
        *,
        task_id=None,
        run=None,
        kind=None,
        verbose=False,
        **kwargs,
    ):
        _execute_task(store_arg, task_id, kind, run, verbose=verbose)
        return task_id

    outcome = UpdateResult(
        changed=True,
        deferred=False,
        install_ref="v0.1.25",
        commit="e" * 40,
    )
    with patch("asc.web.routes_api.start_background_task", side_effect=run_inline), \
            patch("asc.commands.update_cmd._update_core", return_value=outcome), \
            patch("asc.web.daemon.write_update_restart_marker") as marker, \
            patch(
                "asc.web.daemon.schedule_restart",
                return_value={
                    "status": "scheduled",
                    "delay": 1.5,
                    "url": "http://127.0.0.1:8080",
                },
            ) as restart, \
            patch("time.sleep"):
        task_id = routes_api._start_update_task(version="0.1.25")

    task = store.get(task_id)
    assert update_executed.is_set()
    assert task["status"] == TaskStatus.DONE
    assert "terminal_write_uncertainty" not in task["result"]
    marker.assert_called_once()
    restart.assert_called_once()
    store.close()


def test_update_pending_commit_runs_restart_side_effects_exactly_once(
    tmp_path, monkeypatch
):
    """DONE committing after the settle window must still schedule the restart."""
    import threading
    from unittest.mock import patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import routes_api, task_runner
    from asc.web.task_runner import _execute_task
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    store._WRITE_WAIT_TIMEOUT_SEC = 0.08
    monkeypatch.setattr(task_runner, "TERMINAL_STATUS_CONFIRM_TIMEOUT_SEC", 0.04)
    original_apply = store._apply_op
    update_executed = threading.Event()

    def block_after_done_update(conn, op):
        result = original_apply(conn, op)
        if (
            op.kind == "set_status"
            and op.payload.get("status") == TaskStatus.DONE.value
            and not update_executed.is_set()
        ):
            update_executed.set()
            # Beyond the bounded 0.45s confirm/settle window.
            threading.Event().wait(0.6)
        return result

    monkeypatch.setattr(store, "_apply_op", block_after_done_update)

    def run_inline(
        store_arg,
        *,
        task_id=None,
        run=None,
        kind=None,
        verbose=False,
        **kwargs,
    ):
        _execute_task(store_arg, task_id, kind, run, verbose=verbose)
        return task_id

    outcome = UpdateResult(
        changed=True,
        deferred=True,
        install_ref="v0.1.25",
        commit="f" * 40,
    )
    with patch("asc.web.routes_api.start_background_task", side_effect=run_inline), \
            patch("asc.commands.update_cmd._update_core", return_value=outcome), \
            patch("asc.web.daemon.write_update_restart_marker") as marker, \
            patch(
                "asc.web.daemon.schedule_restart",
                return_value={
                    "status": "scheduled",
                    "delay": 1.5,
                    "url": "http://127.0.0.1:8080",
                },
            ) as restart, \
            patch("time.sleep"):
        task_id = routes_api._start_update_task(version="0.1.25")

    store.flush()
    task = store.get(task_id)
    assert update_executed.is_set()
    marker.assert_called_once()
    restart.assert_called_once()
    assert task["status"] == TaskStatus.DONE
    assert task["result"]["success"] is True
    assert task["result"].get("restart_blocked") is not True
    assert "terminal_write_uncertainty" not in task["result"]
    store.close()


def test_update_pending_commit_recovers_via_marker_after_process_restart(
    tmp_path, monkeypatch
):
    """A never-committed DONE must still finish through the durable restart marker."""
    import sqlite3
    import threading
    from unittest.mock import patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import daemon, routes_api, task_runner
    from asc.web.task_runner import _execute_task
    from asc.web.tasks import TaskStatus, TaskStore

    monkeypatch.setattr(daemon, "_STATE_DIR", tmp_path)
    db_path = tmp_path / "tasks.db"
    store = TaskStore(db_path)
    monkeypatch.setattr(routes_api, "_task_store", store)
    store._WRITE_WAIT_TIMEOUT_SEC = 0.08
    monkeypatch.setattr(task_runner, "TERMINAL_STATUS_CONFIRM_TIMEOUT_SEC", 0.04)
    original_apply = store._apply_op
    update_executed = threading.Event()

    def block_then_lose_commit(conn, op):
        if (
            op.kind == "set_status"
            and op.payload.get("status") == TaskStatus.DONE.value
        ):
            result = original_apply(conn, op)
            if not update_executed.is_set():
                update_executed.set()
                threading.Event().wait(0.6)
            # Commit never lands: emulate the process dying mid-transaction.
            raise sqlite3.OperationalError("disk I/O error")
        return original_apply(conn, op)

    monkeypatch.setattr(store, "_apply_op", block_then_lose_commit)

    def run_inline(
        store_arg,
        *,
        task_id=None,
        run=None,
        kind=None,
        verbose=False,
        **kwargs,
    ):
        _execute_task(store_arg, task_id, kind, run, verbose=verbose)
        return task_id

    outcome = UpdateResult(
        changed=True,
        deferred=True,
        install_ref="v0.1.25",
        commit="a" * 40,
    )
    with patch("asc.web.routes_api.start_background_task", side_effect=run_inline), \
            patch("asc.commands.update_cmd._update_core", return_value=outcome), \
            patch(
                "asc.web.daemon.schedule_restart",
                return_value={
                    "status": "scheduled",
                    "delay": 1.5,
                    "url": "http://127.0.0.1:8080",
                },
            ) as restart, \
            patch("time.sleep"):
        task_id = routes_api._start_update_task(version="0.1.25")

    store.flush()
    restart.assert_called_once()
    marker = daemon.read_update_restart_marker()
    assert marker is not None
    assert marker["task_id"] == task_id
    assert marker["pending_install"] is True
    assert marker["install_ref"] == "v0.1.25"
    interrupted = store.get(task_id)
    assert interrupted["status"] != TaskStatus.ERROR
    assert interrupted["result"]["success"] is True
    assert interrupted["result"].get("restart_blocked") is not True
    store.close()

    recovered_store = TaskStore(db_path)
    recovered = recovered_store.get(task_id)
    assert recovered["status"] == TaskStatus.DONE
    assert recovered["result"]["success"] is True
    assert recovered["result"]["restarted"] is True
    assert recovered["result"]["restarting"] is False
    assert recovered["result"].get("restart_blocked") is not True
    # Marker still reports the deferred install, so it stays visible as pending
    # instead of being lost with the never-committed DONE status.
    assert recovered["result"]["pending_install"] is True
    assert recovered["result"]["install_ref"] == "v0.1.25"
    recovered_store.close()


def test_update_web_starter_skips_restart_when_not_installed(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)

    def fake_run(store_arg, *, task_id=None, run=None, **kwargs):
        reporter = MagicMock()
        reporter.failed = False
        run(reporter, MagicMock(is_set=MagicMock(return_value=False)))
        return task_id

    with patch("asc.web.routes_api.start_background_task", side_effect=fake_run), \
            patch(
                "asc.commands.update_cmd._update_core",
                return_value=UpdateResult(changed=False),
            ), \
            patch("asc.web.daemon.schedule_restart") as restart:
        task_id = routes_api._start_update_task()

    restart.assert_not_called()
    task = store.get(task_id)
    assert task["status"] == TaskStatus.DONE
    assert task["result"]["installed"] is False
    assert task["result"].get("restarting") is not True


def test_url_core_fail_raises_runtime_error():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    api = UrlFakeAPI()
    api.get_editable_version = lambda app_id: None  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        _update_version_field_core(
            api,
            "app1",
            "supportUrl",
            "Support URL",
            "https://example.com/support",
            reporter=reporter,
        )

    error_logs = [msg for level, msg in sink.logs if level == "error"]
    assert error_logs
    assert sink.progress_events[-1]["pct"] == 0


def test_update_already_latest_calls_done():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)

    with patch("asc.commands.update_cmd._is_editable", return_value=False), \
            patch("asc.commands.update_cmd._current_version", return_value="0.1.1"), \
            patch("asc.commands.update_cmd._latest_version_from_github", return_value="0.1.1"), \
            patch("asc.commands.update_cmd._install_git_ref") as install:
        installed = _update_core(version=None, branch=None, yes=True, reporter=reporter)

    assert not installed
    assert installed.changed is False
    install.assert_not_called()
    assert sink.progress_events[-1]["pct"] == 100
    joined = "\n".join(msg for _, msg in sink.logs)
    assert "up to date" in joined


def test_update_cancelled_confirm_calls_done():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)

    with patch("asc.commands.update_cmd._is_editable", return_value=False), \
            patch("asc.commands.update_cmd._current_version", return_value="0.1.0"), \
            patch("asc.commands.update_cmd._latest_version_from_github", return_value="0.1.1"), \
            patch("asc.commands.update_cmd.typer.confirm", return_value=False), \
            patch("asc.commands.update_cmd._install_git_ref") as install:
        installed = _update_core(
            version=None, branch=None, yes=False, reporter=reporter, confirm=True
        )

    assert not installed
    assert installed.changed is False
    install.assert_not_called()
    assert sink.progress_events[-1]["pct"] == 100
    joined = "\n".join(msg for _, msg in sink.logs)
    assert "cancelled" in joined.lower() or "cancel" in joined.lower()


def test_update_error_fails_once_in_core_not_starter():
    """UpdateError path: core fails once; starter must not call reporter.fail again."""
    import inspect
    from asc.web import routes_api

    starter = inspect.getsource(routes_api._start_update_task)
    assert "except UpdateError" in starter
    block = starter.split("except UpdateError")[1].split("except Exception")[0]
    assert "reporter.fail(" not in block
