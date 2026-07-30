"""Tests for src/asc/commands/metadata.py"""
from __future__ import annotations

from pathlib import Path

import pytest

from asc.commands.metadata import _select_app_info_id, _update_version_field_core, _upload_metadata_core
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


class MetaFakeAPI:
    """最小化 FakeAPI，覆盖 metadata 命令所需端点。"""

    def __init__(self):
        self.calls = []
        self.app_info_id = "appinfo_1"
        self.version_id = "ver_1"
        self.app_infos = [
            {
                "id": "appinfo_old",
                "attributes": {"state": "READY_FOR_SALE"},
                "relationships": {"appStoreVersions": {"data": [{"id": "ver_old"}]}},
            },
            {
                "id": self.app_info_id,
                "attributes": {"state": "PREPARE_FOR_SUBMISSION"},
                "relationships": {"appStoreVersions": {"data": [{"id": self.version_id}]}},
            },
        ]
        self.info_locs = {
            "zh-Hans": {"id": "iloc_zh", "attributes": {"locale": "zh-Hans"}},
        }
        self.ver_locs = {
            "zh-Hans": {"id": "vloc_zh", "attributes": {"locale": "zh-Hans"}},
            "en-US": {"id": "vloc_en", "attributes": {"locale": "en-US"}},
        }
        self.updated_info_locs: dict[str, dict] = {}
        self.created_info_locs: list = []
        self.updated_ver_locs: dict[str, dict] = {}
        self.created_ver_locs: list = []

    def get_app_infos(self, app_id):
        self.calls.append(("get_app_infos", app_id))
        return self.app_infos

    def get_editable_version(self, app_id):
        self.calls.append(("get_editable_version", app_id))
        return {
            "id": self.version_id,
            "attributes": {"versionString": "1.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
        }

    def get_app_info_localizations(self, app_info_id):
        self.calls.append(("get_app_info_localizations", app_info_id))
        return [
            {"id": loc["id"], "attributes": {"locale": locale}}
            for locale, loc in self.info_locs.items()
        ]

    def get_version_localizations(self, version_id):
        self.calls.append(("get_version_localizations", version_id))
        return [
            {"id": loc["id"], "attributes": {"locale": locale}}
            for locale, loc in self.ver_locs.items()
        ]

    def update_app_info_localization(self, loc_id, attrs):
        self.calls.append(("update_app_info_localization", loc_id, attrs))
        self.updated_info_locs[loc_id] = attrs

    def create_app_info_localization(self, app_info_id, locale, attrs):
        self.calls.append(("create_app_info_localization", app_info_id, locale, attrs))
        self.created_info_locs.append({"locale": locale, "attrs": attrs})

    def update_version_localization(self, loc_id, attrs):
        self.calls.append(("update_version_localization", loc_id, attrs))
        self.updated_ver_locs[loc_id] = attrs

    def create_version_localization(self, version_id, locale, attrs):
        self.calls.append(("create_version_localization", version_id, locale, attrs))
        self.created_ver_locs.append({"locale": locale, "attrs": attrs})


# ── _upload_metadata_core ──

def test_metadata_no_editable_version_raises():
    api = MetaFakeAPI()
    api.get_editable_version = lambda app_id: None  # type: ignore[method-assign]
    metadata = [{"locale": "zh-Hans", "name": "测试"}]
    with pytest.raises(RuntimeError):
        _upload_metadata_core(api, "app1", metadata)


def test_metadata_no_app_info_raises():
    api = MetaFakeAPI()
    api.app_infos = []
    metadata = [{"locale": "zh-Hans", "name": "测试"}]
    with pytest.raises(RuntimeError):
        _upload_metadata_core(api, "app1", metadata)


def test_metadata_dry_run_no_api_calls():
    api = MetaFakeAPI()
    metadata = [{"locale": "zh-Hans", "name": "测试", "description": "描述"}]
    _upload_metadata_core(api, "app1", metadata, dry_run=True)
    write_calls = [c for c in api.calls if c[0].startswith(("update_", "create_"))]
    assert write_calls == []


def test_metadata_updates_existing_info_localization():
    api = MetaFakeAPI()
    metadata = [{"locale": "zh-Hans", "name": "新名称", "subtitle": "新副标题"}]
    _upload_metadata_core(api, "app1", metadata)
    assert "iloc_zh" in api.updated_info_locs
    assert api.updated_info_locs["iloc_zh"]["name"] == "新名称"


def test_metadata_creates_new_info_localization():
    api = MetaFakeAPI()
    # en-US 不在 info_locs 中，应该创建
    metadata = [{"locale": "en-US", "name": "New Name"}]
    _upload_metadata_core(api, "app1", metadata)
    assert len(api.created_info_locs) == 1
    assert api.created_info_locs[0]["locale"] == "en-US"
    assert api.created_info_locs[0]["attrs"]["name"] == "New Name"


def test_metadata_updates_version_localization():
    api = MetaFakeAPI()
    metadata = [{"locale": "zh-Hans", "description": "新描述", "keywords": "关键词1,关键词2"}]
    _upload_metadata_core(api, "app1", metadata)
    assert "vloc_zh" in api.updated_ver_locs
    assert api.updated_ver_locs["vloc_zh"]["description"] == "新描述"
    assert api.updated_ver_locs["vloc_zh"]["keywords"] == "关键词1,关键词2"


def test_metadata_include_version_fields_keywords_only():
    api = MetaFakeAPI()
    metadata = [{"locale": "zh-Hans", "description": "描述", "keywords": "kw1"}]
    _upload_metadata_core(api, "app1", metadata, include_version_fields={"keywords"})
    assert "vloc_zh" in api.updated_ver_locs
    assert "keywords" in api.updated_ver_locs["vloc_zh"]
    assert "description" not in api.updated_ver_locs["vloc_zh"]


def test_metadata_uses_app_info_for_editable_version_and_updates_version(capsys):
    api = MetaFakeAPI()
    metadata = [
        {
            "locale": "zh-Hans",
            "name": "新名称",
            "subtitle": "新副标题",
            "description": "新描述",
            "keywords": "kw1,kw2",
        }
    ]
    _upload_metadata_core(api, "app1", metadata)

    output = capsys.readouterr().out
    assert "App Info ID: appinfo_1" in output
    assert api.updated_info_locs["iloc_zh"]["name"] == "新名称"
    assert api.updated_ver_locs["vloc_zh"]["description"] == "新描述"
    assert api.updated_ver_locs["vloc_zh"]["keywords"] == "kw1,kw2"


def test_metadata_selects_app_info_by_state_when_relationship_missing():
    app_infos = [
        {"id": "appinfo_old", "attributes": {"state": "READY_FOR_SALE"}},
        {"id": "appinfo_new", "attributes": {"state": "PREPARE_FOR_SUBMISSION"}},
    ]
    assert _select_app_info_id(app_infos, "ver_1", "PREPARE_FOR_SUBMISSION") == "appinfo_new"


def test_upload_metadata_core_reports_progress_per_locale():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    api = MetaFakeAPI()
    metadata = [
        {"locale": "zh-Hans", "name": "测试", "description": "描述"},
        {"locale": "en-US", "name": "Test", "description": "desc"},
    ]
    _upload_metadata_core(api, "app1", metadata, dry_run=True, reporter=reporter)

    phases = [e["phase"] for e in sink.progress_events]
    assert "check" in phases
    assert "locales" in phases

    locale_with_msg = [
        e
        for e in sink.progress_events
        if e["phase"] == "locales" and e["msg"].startswith("元数据 ")
    ]
    assert len(locale_with_msg) == 2
    assert locale_with_msg[0]["pct"] == 5 + int(0.5 * 95)
    assert locale_with_msg[1]["pct"] == 100
    assert locale_with_msg[0]["phase_index"] == 2
    assert locale_with_msg[0]["phase_total"] == 2

    pcts = [e["pct"] for e in sink.progress_events]
    assert pcts == sorted(pcts)


def test_upload_metadata_core_logs_summaries_via_reporter():
    """Key start / per-locale / end lines go to reporter.log (Web TaskStore path)."""
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    api = MetaFakeAPI()
    metadata = [
        {"locale": "zh-Hans", "name": "测试", "description": "描述"},
        {"locale": "en-US", "name": "Test", "description": "desc"},
    ]
    _upload_metadata_core(api, "app1", metadata, dry_run=False, reporter=reporter)

    info_logs = [msg for level, msg in sink.logs if level == "info"]
    assert any("上传元数据" in msg for msg in info_logs)
    assert any("App Info ID: appinfo_1" in msg for msg in info_logs)
    assert any("语言: zh-Hans" in msg for msg in info_logs)
    assert any("已更新 App Info 本地化" in msg for msg in info_logs)
    assert any("已更新版本本地化" in msg or "已创建版本本地化" in msg for msg in info_logs)
    assert any("元数据上传完成" in msg for msg in info_logs)
    # Field-level dumps stay out of default info logs (debug or print).
    assert not any(msg.strip().startswith("应用名称:") for msg in info_logs)


def test_metadata_source_has_no_progress_protocol():
    import asc.commands.metadata as metadata_mod

    src = Path(metadata_mod.__file__).read_text(encoding="utf-8")
    assert "[PROGRESS:" not in src


def test_upload_metadata_skips_done_when_not_finalize():
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    reporter.set_phases([
        ("check", 5, "校验"),
        ("locales", 45, "元数据"),
        ("scan", 5, "扫描"),
        ("upload", 45, "截图"),
    ])
    api = MetaFakeAPI()
    metadata = [{"locale": "en-US", "name": "Test", "description": "desc"}]
    _upload_metadata_core(
        api,
        "app1",
        metadata,
        dry_run=True,
        reporter=reporter,
        manage_phases=False,
        finalize=False,
    )
    pcts = [e["pct"] for e in sink.progress_events]
    assert pcts == sorted(pcts)
    assert pcts[-1] < 100  # must not force 100 before screenshots
    info_logs = [msg for level, msg in sink.logs if level == "info"]
    assert any("元数据上传完成" in msg for msg in info_logs)


def test_metadata_web_starter_does_not_use_private_sinks():
    from pathlib import Path
    import asc.web.routes_api as routes_api

    src = Path(routes_api.__file__).read_text(encoding="utf-8")
    # Only check the metadata starter region for private sink access.
    start = src.index("def _start_metadata_task")
    end = src.index("def _start_build_task", start)
    metadata_starter = src[start:end]
    assert "reporter._sinks" not in metadata_starter
    assert 'getattr(sink, "_task_id"' not in metadata_starter


# ── _update_version_field_core ──

def test_update_version_field_all_locales():
    api = MetaFakeAPI()
    _update_version_field_core(api, "app1", "supportUrl", "Support URL", "https://example.com")
    assert "vloc_zh" in api.updated_ver_locs
    assert "vloc_en" in api.updated_ver_locs
    assert api.updated_ver_locs["vloc_zh"]["supportUrl"] == "https://example.com"


def test_update_version_field_filtered_locale():
    api = MetaFakeAPI()
    _update_version_field_core(
        api, "app1", "supportUrl", "Support URL", "https://example.com",
        locales=["en-US"]
    )
    assert "vloc_en" in api.updated_ver_locs
    assert "vloc_zh" not in api.updated_ver_locs


def test_update_version_field_nonexistent_locale_no_api_call():
    api = MetaFakeAPI()
    with pytest.raises(RuntimeError):
        _update_version_field_core(
            api, "app1", "supportUrl", "Support URL", "https://example.com",
            locales=["fr-FR"]
        )
    write_calls = [c for c in api.calls if c[0].startswith("update_")]
    assert write_calls == []


def test_update_version_field_dry_run():
    api = MetaFakeAPI()
    _update_version_field_core(
        api, "app1", "supportUrl", "Support URL", "https://example.com",
        dry_run=True
    )
    write_calls = [c for c in api.calls if c[0].startswith("update_")]
    assert write_calls == []
