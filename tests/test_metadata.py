"""Tests for src/asc/commands/metadata.py"""
from __future__ import annotations

import pytest

from asc.commands.metadata import _update_version_field_core, _upload_metadata_core


class MetaFakeAPI:
    """最小化 FakeAPI，覆盖 metadata 命令所需端点。"""

    def __init__(self):
        self.calls = []
        self.app_info_id = "appinfo_1"
        self.version_id = "ver_1"
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
        return [{"id": self.app_info_id}]

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

def test_metadata_dry_run_no_api_calls():
    api = MetaFakeAPI()
    metadata = [{"语言": "zh-Hans", "应用名称": "测试", "长描述": "描述"}]
    _upload_metadata_core(api, "app1", metadata, dry_run=True)
    write_calls = [c for c in api.calls if c[0].startswith(("update_", "create_"))]
    assert write_calls == []


def test_metadata_updates_existing_info_localization():
    api = MetaFakeAPI()
    metadata = [{"语言": "zh-Hans", "应用名称": "新名称", "副标题": "新副标题"}]
    _upload_metadata_core(api, "app1", metadata)
    assert "iloc_zh" in api.updated_info_locs
    assert api.updated_info_locs["iloc_zh"]["name"] == "新名称"


def test_metadata_creates_new_info_localization():
    api = MetaFakeAPI()
    # en-US 不在 info_locs 中，应该创建
    metadata = [{"语言": "en-US", "应用名称": "New Name"}]
    _upload_metadata_core(api, "app1", metadata)
    assert len(api.created_info_locs) == 1
    assert api.created_info_locs[0]["locale"] == "en-US"
    assert api.created_info_locs[0]["attrs"]["name"] == "New Name"


def test_metadata_updates_version_localization():
    api = MetaFakeAPI()
    metadata = [{"语言": "zh-Hans", "长描述": "新描述", "关键子": "关键词1,关键词2"}]
    _upload_metadata_core(api, "app1", metadata)
    assert "vloc_zh" in api.updated_ver_locs
    assert api.updated_ver_locs["vloc_zh"]["description"] == "新描述"
    assert api.updated_ver_locs["vloc_zh"]["keywords"] == "关键词1,关键词2"


def test_metadata_include_version_fields_keywords_only():
    api = MetaFakeAPI()
    metadata = [{"语言": "zh-Hans", "长描述": "描述", "关键子": "kw1"}]
    _upload_metadata_core(api, "app1", metadata, include_version_fields={"keywords"})
    assert "vloc_zh" in api.updated_ver_locs
    assert "keywords" in api.updated_ver_locs["vloc_zh"]
    assert "description" not in api.updated_ver_locs["vloc_zh"]


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
