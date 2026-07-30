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
        _update_core(version=None, branch=None, yes=True, reporter=reporter)

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
    assert "_PROGRESS_RE" not in starter
    assert "io.StringIO" not in starter
    assert "reporter" in starter
    route = inspect.getsource(routes_api.update_run)
    assert "_start_update_task" in route


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
        _update_core(version=None, branch=None, yes=True, reporter=reporter)

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
        _update_core(
            version=None, branch=None, yes=False, reporter=reporter, confirm=True
        )

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
