from __future__ import annotations

from pathlib import Path
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


def test_locale_picker_uses_catalog_then_presence():
    src = Path("frontend/src/views/listing/LocalePicker.vue").read_text(encoding="utf-8")
    catalog = src.index("/api/metadata/locales")
    presence = src.index("/api/metadata/locales/presence")
    assert catalog < presence
    assert "presenceAvailable" in src
    assert "navigator.clipboard.writeText" in src
    assert "/api/listing/" not in src
    assert "/api/metadata/run" not in src
    for key in I18N_KEYS:
        assert t(key, lang="zh") != key
        assert t(key, lang="en") != key


def test_locale_picker_stays_usable_when_presence_fails():
    src = Path("frontend/src/views/listing/LocalePicker.vue").read_text(encoding="utf-8")
    assert "presenceAvailable.value = false" in src
    assert "el-dialog" in src
    assert "metadata.locales_presence_unavailable" in src


def test_locale_button_uses_catalog():
    src = Path("frontend/src/views/listing/LocalTab.vue").read_text(encoding="utf-8")
    assert "metadata.locales_btn" in src
    assert t("metadata.locales_btn", lang="zh") == "语言码"
    assert t("metadata.locales_btn", lang="en") == "Locale codes"
