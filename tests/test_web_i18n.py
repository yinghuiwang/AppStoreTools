from __future__ import annotations

import os

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


def test_resolve_via_middleware_sets_html_lang_attr(client, monkeypatch):
    monkeypatch.delenv("ASC_LANG", raising=False)
    resp = client.get("/", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert resp.status_code == 200
    assert 'lang="en"' in resp.text
    client.cookies.set(COOKIE_NAME, "zh")
    resp2 = client.get("/", headers={"Accept-Language": "en-US"})
    assert resp2.status_code == 200
    assert 'lang="zh-CN"' in resp2.text


def test_nav_renders_english_with_en_cookie(client, monkeypatch):
    monkeypatch.delenv("ASC_LANG", raising=False)
    client.cookies.set(COOKIE_NAME, "en")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text
    assert "Settings" in resp.text
    assert "window.__I18N" in resp.text


def test_nav_renders_chinese_with_zh_cookie(client, monkeypatch):
    monkeypatch.delenv("ASC_LANG", raising=False)
    client.cookies.set(COOKIE_NAME, "zh")
    resp = client.get("/")
    assert "仪表盘" in resp.text
    assert "设置" in resp.text


def test_settings_language_select_marks_current(client, monkeypatch):
    client.cookies.set(COOKIE_NAME, "en")
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert 'value="en"' in resp.text
    assert "selected" in resp.text


def test_homepage_feature_chrome_switches_with_lang_cookie(client, monkeypatch):
    monkeypatch.delenv("ASC_LANG", raising=False)
    client.cookies.set(COOKIE_NAME, "en")
    en = client.get("/")
    assert en.status_code == 200
    assert "Release Console" in en.text
    assert "Check environment" in en.text
    assert "Task overview" in en.text

    client.cookies.set(COOKIE_NAME, "zh")
    zh = client.get("/")
    assert zh.status_code == 200
    assert "发布控制台" in zh.text
    assert "检查环境" in zh.text
    assert "任务概览" in zh.text


def test_settings_and_metadata_pages_switch_with_lang_cookie(client, monkeypatch):
    monkeypatch.delenv("ASC_LANG", raising=False)
    client.cookies.set(COOKIE_NAME, "en")
    settings_en = client.get("/settings")
    metadata_en = client.get("/metadata")
    assert "Language" in settings_en.text
    assert "LLM translation config" in settings_en.text
    assert "Metadata upload" in metadata_en.text
    assert "CSV file path" in metadata_en.text

    client.cookies.set(COOKIE_NAME, "zh")
    settings_zh = client.get("/settings")
    metadata_zh = client.get("/metadata")
    assert "语言" in settings_zh.text
    assert "LLM 翻译配置" in settings_zh.text
    assert "元数据上传" in metadata_zh.text
    assert "CSV 文件路径" in metadata_zh.text


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


def test_agent_attach_i18n_keys():
    load_catalog.cache_clear()
    assert t("agent.attach", lang="zh") == "添加上下文"
    assert t("agent.attach_task", lang="zh").startswith("绑定失败任务")
    assert "optional" in t("agent.attach_task", lang="en").lower()
    assert t("agent.close", lang="en") == "Close Agent panel"
    assert "optional" in t("agent.empty", lang="en").lower()
