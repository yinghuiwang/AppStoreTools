from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from asc.guard import GuardViolationError
from asc.locales_catalog import LocaleCatalogError
from asc.web.i18n import t
from asc.web.server import create_app


@pytest.fixture(autouse=True)
def isolated_web_task_guard(monkeypatch):
    monkeypatch.setattr("asc.web.routes_api.enforce_config_guard", MagicMock())


@pytest.fixture
def client():
    return TestClient(create_app())


def _by_code(payload):
    return {row["code"]: row for row in payload["locales"]}


def test_metadata_locales_catalog_skips_asc(client):
    mock_api = MagicMock()
    with patch("asc.web.routes_api.Config") as cfg, \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")) as make_api, \
         patch("asc.web.routes_api._get_available_locales") as get_locs, \
         patch("asc.web.routes_api._metadata_locale_presence") as presence:
        response = client.get("/api/metadata/locales", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert len(data["locales"]) == 50
    by = _by_code(data)
    assert by["zh-Hans"]["present"] is False
    assert by["en-US"]["present"] is False
    assert set(by["zh-Hans"]) == {"code", "name_en", "name_zh", "present"}
    cfg.assert_not_called()
    make_api.assert_not_called()
    get_locs.assert_not_called()
    presence.assert_not_called()
    mock_api.get_editable_version.assert_not_called()


def test_metadata_locales_no_cookie_returns_catalog_only(client):
    response = client.get("/api/metadata/locales")
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert len(data["locales"]) == 50
    assert all(row["present"] is False for row in data["locales"])


def test_metadata_locales_catalog_error_is_500_localized(client):
    with patch(
        "asc.web.routes_api.list_locales",
        side_effect=LocaleCatalogError("bad catalog"),
    ):
        zh = client.get("/api/metadata/locales", cookies={"asc_lang": "zh"})
        en = client.get("/api/metadata/locales", cookies={"asc_lang": "en"})
    assert zh.status_code == 500
    assert zh.json() == {"error": "语言码目录不可用"}
    assert en.status_code == 500
    assert en.json() == {"error": "Locale catalog is unavailable"}
    assert zh.json()["error"] == t("metadata.locales_catalog_unavailable", lang="zh")
    assert en.json()["error"] == t("metadata.locales_catalog_unavailable", lang="en")


def test_metadata_locales_does_not_filter_on_query_param(client):
    response = client.get("/api/metadata/locales", params={"q": "hans"})
    assert response.status_code == 200
    assert len(response.json()["locales"]) == 50


def test_metadata_locales_does_not_change_csv(client, tmp_path):
    csv_path = tmp_path / "appstore_info.csv"
    original = "locale,name\nen-US,Hello\n"
    csv_path.write_text(original, encoding="utf-8")
    before = csv_path.read_bytes()
    response = client.get("/api/metadata/locales")
    assert response.status_code == 200
    assert csv_path.read_bytes() == before
    assert csv_path.read_text(encoding="utf-8") == original


def test_metadata_locales_presence_marks_codes_when_version_has_locales(client):
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.0.0"},
    }
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "zh-Hans"}},
        {"id": "l2", "attributes": {"locale": "xx-XX"}},
    ]
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales/presence", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is True
    assert "zh-Hans" in data["codes"]
    assert "en-US" not in data["codes"]
    assert "locales" not in data
    mock_api.get_editable_version.assert_called()


def test_metadata_locales_presence_no_cookie_degrades(client):
    response = client.get("/api/metadata/locales/presence")
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert data["codes"] == []


def test_metadata_locales_presence_make_api_failure_degrades(client):
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", side_effect=RuntimeError("missing key")):
        response = client.get("/api/metadata/locales/presence", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert data["codes"] == []


def test_metadata_locales_presence_no_editable_version_degrades(client):
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = None
    mock_api.get_version_localizations.return_value = []
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales/presence", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert data["codes"] == []


def test_metadata_locales_presence_empty_localizations_available(client):
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {}}
    mock_api.get_version_localizations.return_value = []
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales/presence", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is True
    assert data["codes"] == []


def test_metadata_locales_presence_asc_error_degrades(client):
    mock_api = MagicMock()
    mock_api.get_editable_version.side_effect = RuntimeError("401 unauthorized")
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales/presence", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert data["codes"] == []


def test_metadata_locales_presence_localization_fetch_failure_degrades(client):
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {}}
    mock_api.get_version_localizations.side_effect = RuntimeError("timeout")
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales/presence", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert data["codes"] == []


def test_metadata_locales_presence_guard_error_is_200_not_409(client, monkeypatch):
    monkeypatch.setattr(
        "asc.web.routes_api.enforce_config_guard",
        MagicMock(side_effect=GuardViolationError("conflict")),
    )
    mock_api = MagicMock()
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales/presence", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert data["codes"] == []
    mock_api.get_editable_version.assert_not_called()


def test_metadata_locales_presence_ignores_catalog_error(client):
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {}}
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "zh-Hans"}},
    ]
    with patch(
        "asc.web.routes_api.list_locales",
        side_effect=LocaleCatalogError("bad catalog"),
    ), patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales/presence", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is True
    assert "zh-Hans" in data["codes"]


I18N_KEYS = [
    "metadata.locales_btn",
    "metadata.locales_title",
    "metadata.locales_search",
    "metadata.locales_copied",
    "metadata.locales_copy_failed",
    "metadata.locales_empty",
    "metadata.locales_catalog_unavailable",
    "metadata.locales_presence_unavailable",
    "metadata.locales_present",
    "metadata.locales_refresh",
    "metadata.locales_hint",
    "metadata.locales_close",
]


def test_metadata_page_has_locale_search_popup_markup(client):
    response = client.get("/metadata")
    html = response.text
    assert response.status_code == 200
    assert "/api/metadata/locales" in html
    assert "/api/metadata/locales/presence" in html
    assert "localeCatalogOpen" in html
    assert "localeCatalogCopy" in html
    assert "localeCatalogRefresh" in html
    assert "localeCatalogLoadPresence" in html
    assert "fixed inset-0" in html
    assert "locale-catalog-dialog" in html
    assert "locale-catalog-results" in html
    assert "locale-catalog-grid" in html
    assert "navigator.clipboard.writeText" in html
    assert "execCommand('copy')" in html
    for key in I18N_KEYS:
        assert key in html
    copy_at = html.index("localeCatalogCopy")
    copy_chunk = html[copy_at:copy_at + 1800]
    assert "locales-json-input" not in copy_chunk
    assert "fields-by-locale-json-input" not in copy_chunk
    assert "screenshot-scopes-json-input" not in copy_chunk
    assert "wbSaveToCsv" not in copy_chunk
    assert "/api/listing/" not in copy_chunk
    assert "/api/metadata/run" not in copy_chunk
    assert "localStorage" not in copy_chunk


def test_metadata_page_locale_popup_loads_catalog_before_presence(client):
    html = client.get("/metadata").text
    ensure_at = html.index("localeCatalogEnsureLoaded(force)")
    ensure_chunk = html[ensure_at:ensure_at + 3500]
    catalog_fetch = ensure_chunk.index("fetch('/api/metadata/locales')")
    presence_fetch = ensure_chunk.index("fetch('/api/metadata/locales/presence')")
    loaded_at = ensure_chunk.index("this.localeCatalog.loaded = true")
    assert catalog_fetch < loaded_at < presence_fetch
    assert "localeCatalogLoadPresence" in ensure_chunk
    assert "presenceLoaded" in html
    assert (
        "localeCatalog.loaded && localeCatalog.presenceLoaded && !localeCatalog.presenceAvailable"
        in html
    )


def test_metadata_page_locale_popup_multicolumn_stays_in_viewport(client):
    html = client.get("/metadata").text
    css = client.get("/static/listing-workbench.css").text
    assert "locale-catalog-dialog" in html
    assert "locale-catalog-results" in html
    assert "locale-catalog-grid" in html
    assert "x-teleport" in html
    assert "grid-cols-2" in html
    assert "sm:grid-cols-3" in html
    assert "min(920px" in html
    assert "max-height:85vh" in html.replace(" ", "")
    assert "max-height: 85vh" in css
    assert "repeat(4, minmax(0, 1fr))" in css
    grid_at = css.index(".locale-catalog-grid")
    assert "repeat(auto-fill" not in css[grid_at:grid_at + 500]
    results_at = css.index(".locale-catalog-results")
    results_chunk = css[results_at:results_at + 280]
    assert "overflow-y: auto" in results_chunk
    assert "overflow-x: hidden" in results_chunk
    dialog_html = html[html.index("locale-catalog-dialog"):html.index("locale-catalog-dialog") + 2800]
    assert "overflow-x: auto" not in dialog_html
    copy_at = html.index("localeCatalogCopy")
    copy_chunk = html[copy_at:copy_at + 1800]
    assert "wbSaveToCsv" not in copy_chunk
    assert "/api/listing/" not in copy_chunk


def test_metadata_page_locale_button_localized(client, monkeypatch):
    monkeypatch.delenv("ASC_LANG", raising=False)
    client.cookies.set("asc_lang", "zh")
    zh = client.get("/metadata")
    assert "语言码" in zh.text
    assert t("metadata.locales_btn", lang="zh") in zh.text
    client.cookies.set("asc_lang", "en")
    en = client.get("/metadata")
    assert "Locale codes" in en.text
    assert t("metadata.locales_btn", lang="en") in en.text
