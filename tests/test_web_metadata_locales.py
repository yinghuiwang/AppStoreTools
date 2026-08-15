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


def test_metadata_locales_marks_present_when_version_has_locales(client):
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
        response = client.get("/api/metadata/locales", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is True
    by = _by_code(data)
    assert by["zh-Hans"]["present"] is True
    assert by["en-US"]["present"] is False
    assert "xx-XX" not in by
    assert set(by["zh-Hans"]) == {"code", "name_en", "name_zh", "present"}
    assert len(data["locales"]) == 50


def test_metadata_locales_no_cookie_degrades_presence(client):
    response = client.get("/api/metadata/locales")
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert len(data["locales"]) == 50
    assert all(row["present"] is False for row in data["locales"])


def test_metadata_locales_make_api_failure_degrades_presence(client):
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", side_effect=RuntimeError("missing key")):
        response = client.get("/api/metadata/locales", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert len(data["locales"]) == 50
    assert all(row["present"] is False for row in data["locales"])


def test_metadata_locales_no_editable_version_degrades_presence(client):
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = None
    mock_api.get_version_localizations.return_value = []
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert all(row["present"] is False for row in data["locales"])


def test_metadata_locales_empty_localizations_presence_available(client):
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {}}
    mock_api.get_version_localizations.return_value = []
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is True
    assert all(row["present"] is False for row in data["locales"])


def test_metadata_locales_asc_error_degrades_presence(client):
    mock_api = MagicMock()
    mock_api.get_editable_version.side_effect = RuntimeError("401 unauthorized")
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert len(data["locales"]) == 50


def test_metadata_locales_localization_fetch_failure_degrades_presence(client):
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {}}
    mock_api.get_version_localizations.side_effect = RuntimeError("timeout")
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert len(data["locales"]) == 50
    assert all(row["present"] is False for row in data["locales"])


def test_metadata_locales_guard_error_is_200_not_409(client, monkeypatch):
    monkeypatch.setattr(
        "asc.web.routes_api.enforce_config_guard",
        MagicMock(side_effect=GuardViolationError("conflict")),
    )
    mock_api = MagicMock()
    with patch("asc.web.routes_api.Config", return_value=MagicMock()), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123")):
        response = client.get("/api/metadata/locales", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["presenceAvailable"] is False
    assert len(data["locales"]) == 50
    mock_api.get_editable_version.assert_not_called()


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
    assert "localeCatalogOpen" in html
    assert "localeCatalogCopy" in html
    assert "localeCatalogRefresh" in html
    assert "fixed inset-0" in html
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
