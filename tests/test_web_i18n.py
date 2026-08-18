from __future__ import annotations

import os
from pathlib import Path

import pytest

from asc.web.i18n import (
    COOKIE_NAME,
    html_lang,
    load_catalog,
    normalize_lang,
    resolve_lang,
    t,
)


def test_normalize_lang_aliases():
    assert normalize_lang("zh") == "zh"
    assert normalize_lang("zh-CN") == "zh"
    assert normalize_lang("zh_Hans") == "zh"
    assert normalize_lang("en") == "en"
    assert normalize_lang("en-US") == "en"
    assert normalize_lang("fr") is None
    assert normalize_lang("") is None
    assert normalize_lang(None) is None


def test_resolve_lang_cookie_wins_over_accept_and_env(monkeypatch):
    monkeypatch.setenv("ASC_LANG", "zh")
    assert resolve_lang(
        cookie="en",
        accept_language="zh-CN,zh;q=0.9",
        env_lang="zh",
    ) == "en"


def test_resolve_lang_accept_language_when_no_cookie(monkeypatch):
    monkeypatch.delenv("ASC_LANG", raising=False)
    assert resolve_lang(cookie=None, accept_language="zh-CN,zh;q=0.9") == "zh"
    assert resolve_lang(cookie=None, accept_language="en-US,en;q=0.8") == "en"
    assert resolve_lang(cookie=None, accept_language="fr-FR,fr;q=0.9") == "en"


def test_resolve_lang_env_then_default(monkeypatch):
    monkeypatch.setenv("ASC_LANG", "zh")
    assert resolve_lang(cookie=None, accept_language=None) == "zh"
    monkeypatch.delenv("ASC_LANG", raising=False)
    assert resolve_lang(cookie=None, accept_language=None, env_lang=None) == "en"


def test_t_interpolation_and_fallback(monkeypatch):
    # Uses real catalogs once files exist; until then this fails on import/load.
    assert "仪表盘" in t("nav.dashboard", lang="zh") or t("nav.dashboard", lang="zh") == "仪表盘"
    assert t("nav.dashboard", lang="en") == "Dashboard"
    assert t("missing.key.that.does.not.exist", lang="zh") == "missing.key.that.does.not.exist"
    assert "1.2.3" in t("update.current_version", lang="en", version="1.2.3")


def test_html_lang_mapping():
    assert html_lang("zh") == "zh-CN"
    assert html_lang("en") == "en"


def test_cookie_name_constant():
    assert COOKIE_NAME == "asc_lang"


from fastapi.testclient import TestClient

from asc.web.server import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_set_lang_sets_cookie_and_rejects_invalid(client, monkeypatch):
    monkeypatch.delenv("ASC_LANG", raising=False)
    bad = client.post("/api/settings/lang", data={"lang": "fr"})
    assert bad.status_code == 400
    ok = client.post("/api/settings/lang", data={"lang": "en"})
    assert ok.status_code == 200
    assert ok.json()["lang"] == "en"
    assert COOKIE_NAME in ok.cookies
    assert ok.cookies[COOKIE_NAME] == "en"
    assert os.environ.get("ASC_LANG") == "en"


def test_resolve_via_middleware_sets_bootstrap_lang(client, monkeypatch):
    monkeypatch.delenv("ASC_LANG", raising=False)
    resp = client.get("/api/bootstrap", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert resp.status_code == 200
    assert resp.json()["lang"] == "en"
    assert resp.json()["html_lang"] == "en"
    client.cookies.set(COOKIE_NAME, "zh")
    resp2 = client.get("/api/bootstrap", headers={"Accept-Language": "en-US"})
    assert resp2.status_code == 200
    assert resp2.json()["lang"] == "zh"
    assert resp2.json()["html_lang"] == "zh-CN"


def test_nav_catalog_english_and_chinese():
    assert t("nav.dashboard", lang="en") == "Dashboard"
    assert t("nav.settings", lang="en") == "Settings"
    assert t("nav.profiles", lang="en") == "App Profiles"
    assert t("nav.guard", lang="en") == "Guard"
    assert t("nav.update", lang="en") == "Check Updates"
    assert t("nav.dashboard", lang="zh") == "仪表盘"
    assert t("nav.settings", lang="zh") == "设置"
    assert t("nav.profiles", lang="zh") == "App 管理"
    assert t("nav.guard", lang="zh") == "Guard 安全守卫"
    assert t("nav.update", lang="zh") == "检查更新"
    assert t("nav.listing", lang="en") == "Listing"
    assert t("nav.listing", lang="zh") == "商品页"
    assert t("nav.group.listing", lang="zh") == "上架"
    assert t("listing.tab.upload", lang="zh") == "上传"
    assert t("listing.tab.local", lang="zh") == "本地工作台"


def test_language_switch_updates_locale_without_reload():
    src = (Path(__file__).resolve().parents[1] / "frontend/src/components/AppTopbar.vue").read_text(encoding="utf-8")
    assert "/api/settings/lang" in src
    assert "locale.value = code" in src
    assert "location.reload" not in src


def test_homepage_feature_chrome_catalog():
    assert t("index.title", lang="en") == "Release Console"
    assert t("index.action_check", lang="en") == "Check environment"
    assert t("index.summary_aria", lang="en") == "Task overview"
    assert t("index.quick_title", lang="en") == "Quick actions"
    assert t("index.title", lang="zh") == "发布控制台"
    dash = (Path(__file__).resolve().parents[1] / "frontend/src/views/DashboardView.vue").read_text(encoding="utf-8")
    assert 't("index.title")' in dash
    assert "index.metrics_aria" in dash
    assert "index.quick_title" in dash
    assert 'action: "check"' in dash
    assert 'path: "/listing"' in dash
    assert 'path: "/build"' in dash


def test_settings_and_metadata_catalogs():
    assert t("settings.language", lang="en") == "Language"
    assert t("settings.llm_title", lang="en") == "LLM translation config"
    assert t("metadata.title", lang="en") == "Metadata upload"
    assert t("metadata.csv_path", lang="en") == "CSV file path"
    assert t("settings.language", lang="zh") == "语言"
    assert t("settings.llm_title", lang="zh") == "LLM 翻译配置"
    assert t("metadata.title", lang="zh") == "元数据上传"
    assert t("metadata.csv_path", lang="zh") == "CSV 文件路径"


def test_whats_new_check_no_profile_message_localized(client, monkeypatch):
    monkeypatch.delenv("ASC_LANG", raising=False)
    client.cookies.set(COOKIE_NAME, "en")
    resp = client.get("/api/whats-new/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["message"] == "No profile selected"

    client.cookies.set(COOKIE_NAME, "zh")
    resp_zh = client.get("/api/whats-new/check")
    assert resp_zh.json()["message"] == "未选择 App Profile"


def test_whats_new_check_no_editable_version_localized(client, monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.delenv("ASC_LANG", raising=False)
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = None
    mock_config = MagicMock()

    client.cookies.set(COOKIE_NAME, "en")
    client.cookies.set("asc_profile", "test")
    with patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")), \
         patch("asc.config.Config", return_value=mock_config):
        resp = client.get("/api/whats-new/check")
    assert resp.status_code == 200
    assert resp.json()["message"] == "No editable version"


def test_whats_new_check_version_locales_localized(client, monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.delenv("ASC_LANG", raising=False)
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "2.0.0"},
    }
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "en-US"}},
        {"id": "l2", "attributes": {"locale": "zh-Hans"}},
    ]
    mock_config = MagicMock()

    client.cookies.set(COOKIE_NAME, "en")
    client.cookies.set("asc_profile", "test")
    with patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")), \
         patch("asc.config.Config", return_value=mock_config):
        resp = client.get("/api/whats-new/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["message"] == "Version 2.0.0, found 2 locales"


def test_iap_check_missing_file_localized(client, monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.delenv("ASC_LANG", raising=False)
    mock_config = MagicMock()
    mock_config.iap_path = "missing-iap.json"
    client.cookies.set(COOKIE_NAME, "en")
    client.cookies.set("asc_profile", "testapp")
    with patch("asc.web.routes_api.Config", return_value=mock_config), \
         patch("pathlib.Path.exists", return_value=False):
        resp = client.post("/api/iap/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["message"].startswith("IAP config not found:")


def test_urls_check_env_ok_locales_localized(client, monkeypatch):
    from unittest.mock import MagicMock, patch

    monkeypatch.delenv("ASC_LANG", raising=False)
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.0"},
    }
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "en-US"}},
        {"id": "l2", "attributes": {"locale": "ja"}},
        {"id": "l3", "attributes": {"locale": "ko"}},
    ]
    client.cookies.set(COOKIE_NAME, "en")
    client.cookies.set("asc_profile", "testapp")
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app1")):
        resp = client.get("/api/urls/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["message"] == "Environment OK, found 3 locale versions"


def test_urls_locales_i18n_keys():
    assert t("urls.select_all", lang="zh") == "全选"
    assert t("urls.deselect_all", lang="zh") == "取消全选"
    assert t("urls.locales_required", lang="zh") == "请至少选择一种目标语言"
    assert t("api.urls_locales_required", lang="en") == "Select at least one target locale"
    assert "selected" in t("urls.locales_selected", lang="en", selected=2, total=5)
    assert "已选" in t("urls.locales_selected", lang="zh", selected=2, total=5)


def test_build_phase_progress_i18n_keys():
    load_catalog.cache_clear()
    assert t("build.phase_archive", lang="zh") == "归档"
    assert t("build.phase_export", lang="zh") == "导出"
    assert t("build.phase_upload", lang="zh") == "上传"
    assert t("build.phase_state_wait", lang="zh") == "等待"
    assert t("build.phase_state_running", lang="zh") == "进行中"
    assert t("build.phase_state_done", lang="zh") == "完成"
    assert t("build.phase_state_error", lang="zh") == "失败"
    assert t("build.phase_state_canceled", lang="zh") == "已终止"
    assert t("build.phase_archive", lang="en") == "Archive"
    assert t("build.phase_state_running", lang="en") == "In progress"


def test_task_page_phase_i18n_keys():
    load_catalog.cache_clear()
    assert t("task.back_to_form", lang="zh") == "返回配置"
    assert t("task.edit_and_rerun", lang="zh") == "再改再跑"
    assert t("task.back_to_form", lang="en") == "Back to configuration"
    assert t("task.edit_and_rerun", lang="en") == "Edit and run again"


def test_agent_attach_i18n_keys():
    load_catalog.cache_clear()
    assert t("agent.attach", lang="zh") == "添加上下文"
    assert t("agent.attach_task", lang="zh").startswith("绑定失败任务")
    assert "optional" in t("agent.attach_task", lang="en").lower()
    assert t("agent.close", lang="en") == "Close Agent panel"
    assert "optional" in t("agent.empty", lang="en").lower()
    assert t("agent.sessions", lang="zh") == "会话列表"
    assert t("agent.new_session", lang="zh") == "新建会话"
    assert t("agent.session_empty", lang="zh") == "还没有会话"
    assert t("agent.untitled_session", lang="zh") == "新会话"
    assert t("agent.sessions", lang="en") == "Sessions"
    assert t("agent.new_session", lang="en") == "New session"
    assert t("agent.session_empty", lang="en") == "No sessions yet"
    assert t("agent.untitled_session", lang="en") == "New chat"
