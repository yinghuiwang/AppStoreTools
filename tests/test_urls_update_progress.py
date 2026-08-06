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

        def flush():
            flush_order.append("flush")

        reporter.flush.side_effect = flush
        original_finish = routes_api._finish_task

        def finish_wrapper(tid, status, result):
            flush_order.append("finish")
            return original_finish(tid, status, result)

        with patch.object(routes_api, "_finish_task", side_effect=finish_wrapper):
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

    original_finish = routes_api._finish_task

    def tracked_finish(tid, status, result):
        order.append("finish")
        return original_finish(tid, status, result)

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
            patch.object(routes_api, "_finish_task", side_effect=tracked_finish), \
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


def test_update_web_starter_continues_restart_when_finish_db_fails(tmp_path, monkeypatch):
    """Install success must not be aborted by TaskStore finalize failures."""
    from unittest.mock import MagicMock, patch

    from asc.commands.update_cmd import UpdateResult
    from asc.web import routes_api
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    order: list[str] = []

    def fake_run(store_arg, *, task_id=None, run=None, **kwargs):
        reporter = MagicMock()
        reporter.failed = False
        result = run(reporter, MagicMock(is_set=MagicMock(return_value=False)))
        assert result["success"] is True
        assert "db_finalize_error" in result
        return task_id

    def boom_finish(*args, **kwargs):
        order.append("finish")
        raise RuntimeError("unable to open database file")

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
            patch.object(routes_api, "_finish_task", side_effect=boom_finish), \
            patch("asc.web.daemon.schedule_restart", side_effect=tracked_restart) as restart, \
            patch("asc.web.daemon.write_update_restart_marker", side_effect=tracked_marker), \
            patch("time.sleep"):
        task_id = routes_api._start_update_task(version="0.1.25")

    restart.assert_called_once_with(
        delay=1.5,
        install_ref="v0.1.25",
        commit="b" * 40,
        task_id=task_id,
    )
    assert order == ["finish", "marker", "restart"]


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
