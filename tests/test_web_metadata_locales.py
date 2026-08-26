from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from asc.guard import GuardViolationError
from asc.locales_catalog import LocaleCatalogError
from asc.web.i18n import t
from asc.web.server import create_app

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"
ESBUILD = FRONTEND / "node_modules" / "esbuild" / "bin" / "esbuild"


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
    catalog_src = Path("frontend/src/composables/useLocaleCatalog.ts").read_text(encoding="utf-8")
    picker = Path("frontend/src/components/LocalePicker.vue").read_text(encoding="utf-8")
    catalog = catalog_src.index("/api/metadata/locales")
    presence = catalog_src.index("/api/metadata/locales/presence")
    assert catalog < presence
    assert "presenceAvailable" in catalog_src
    assert "name_en" in catalog_src
    assert "name_zh" in catalog_src
    assert "export function resetLocaleCatalog" in catalog_src
    assert "catalogInflight" in catalog_src
    assert "presenceInflight" in catalog_src
    assert catalog_src.index("const rows = ref") < catalog_src.index("export function useLocaleCatalog")
    assert "pinia" not in catalog_src.lower()
    assert "defineStore" not in catalog_src
    assert "useLocaleCatalog({ presence: true })" in picker
    assert "navigator.clipboard.writeText" in picker
    assert "/api/listing/" not in picker
    assert "/api/metadata/run" not in picker
    for key in I18N_KEYS:
        assert t(key, lang="zh") != key
        assert t(key, lang="en") != key


def test_locale_picker_stays_usable_when_presence_fails():
    catalog_src = Path("frontend/src/composables/useLocaleCatalog.ts").read_text(encoding="utf-8")
    picker = Path("frontend/src/components/LocalePicker.vue").read_text(encoding="utf-8")
    assert "presenceAvailable.value = false" in catalog_src
    assert "t-dialog" in picker
    assert "metadata.locales_presence_unavailable" in picker


def test_locale_button_uses_catalog():
    src = Path("frontend/src/views/listing/PreviewStep.vue").read_text(encoding="utf-8")
    assert 'from "@/components/LocalePicker.vue"' in src
    assert "metadata.locales_btn" in src
    assert t("metadata.locales_btn", lang="zh") == "语言码"
    assert t("metadata.locales_btn", lang="en") == "Locale codes"


def test_locale_catalog_cache_survives_remount_and_fills_presence(tmp_path: Path) -> None:
    if not ESBUILD.exists():
        pytest.skip("frontend esbuild is not installed")

    http_mock = tmp_path / "http-mock.mjs"
    http_mock.write_text(
        """
export function httpJson(url) {
  globalThis.__httpCalls = globalThis.__httpCalls || [];
  globalThis.__httpCalls.push(url);
  if (url.includes("/presence")) {
    if (globalThis.__presenceError) return Promise.reject(globalThis.__presenceError);
    return Promise.resolve(globalThis.__presenceResult);
  }
  if (globalThis.__catalogError) return Promise.reject(globalThis.__catalogError);
  return Promise.resolve(globalThis.__catalogResult);
}
""",
        encoding="utf-8",
    )
    i18n_mock = tmp_path / "i18n-mock.mjs"
    i18n_mock.write_text(
        """
export function useI18n() {
  return {
    t: (key) => key,
    locale: { get value() { return globalThis.__uiLocale || "en"; } },
  };
}
""",
        encoding="utf-8",
    )
    bundled = tmp_path / "useLocaleCatalog.mjs"
    bundled_run = subprocess.run(
        [
            str(ESBUILD),
            str(SRC / "composables" / "useLocaleCatalog.ts"),
            "--bundle",
            "--platform=neutral",
            "--format=esm",
            f"--alias:@/api/http={http_mock}",
            f"--alias:vue-i18n={i18n_mock}",
            f"--outfile={bundled}",
        ],
        cwd=str(FRONTEND),
        capture_output=True,
        text=True,
    )
    assert bundled_run.returncode == 0, bundled_run.stdout + bundled_run.stderr

    runner = tmp_path / "run.mjs"
    runner.write_text(
        """
import { displayNameFor, resetLocaleCatalog, useLocaleCatalog } from './useLocaleCatalog.mjs';

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

globalThis.__httpCalls = [];
globalThis.__uiLocale = "en";
globalThis.__catalogError = null;
globalThis.__presenceError = null;
globalThis.__catalogResult = {
  locales: [
    { code: "zh-Hans", name_en: "Chinese Simplified", name_zh: "简体中文" },
    { code: "en-US", name_en: "English (US)", name_zh: "英语（美国）" },
  ],
};
globalThis.__presenceResult = { codes: ["zh-Hans"], presenceAvailable: true };

resetLocaleCatalog();
const create = useLocaleCatalog({ presence: false });
const preview = useLocaleCatalog({ presence: false });
await Promise.all([create.load(), preview.load()]);
assert(globalThis.__httpCalls.filter((u) => u === "/api/metadata/locales").length === 1, "concurrent catalog loads must share inflight");
assert(!globalThis.__httpCalls.some((u) => u.includes("/presence")), "presence=false must not fetch presence");
assert(create.rows.value.length === 2, "shared rows after first load");
assert(create.labelFor("zh-Hans") === "zh-Hans Chinese Simplified", "en label follows vue-i18n locale");

globalThis.__httpCalls = [];
await useLocaleCatalog({ presence: false }).load();
assert(globalThis.__httpCalls.length === 0, "new instance first load must reuse catalog");

const picker = useLocaleCatalog({ presence: true });
await picker.load();
assert(globalThis.__httpCalls.filter((u) => u === "/api/metadata/locales").length === 0, "presence load must reuse catalog");
assert(globalThis.__httpCalls.filter((u) => u === "/api/metadata/locales/presence").length === 1, "first presence load fetches presence");
assert(picker.presenceAvailable.value === true, "presenceAvailable after merge");
assert(picker.rows.value.find((r) => r.code === "zh-Hans").present === true, "present codes merged");
assert(picker.rows.value.find((r) => r.code === "en-US").present === false, "missing codes stay false");
assert(create.rows.value.find((r) => r.code === "zh-Hans").present === true, "presence merges onto shared catalog");

globalThis.__httpCalls = [];
await useLocaleCatalog({ presence: true }).load();
assert(globalThis.__httpCalls.length === 0, "later presence=true must reuse presence cache");

globalThis.__uiLocale = "zh";
assert(create.labelFor("zh-Hans") === "zh-Hans 简体中文", "zh label follows vue-i18n locale");
assert(displayNameFor(create.rows.value[0], "zh") === "简体中文", "displayNameFor stays locale-driven");
assert(globalThis.__httpCalls.length === 0, "language switch must not refetch");

globalThis.__httpCalls = [];
await picker.load();
assert(globalThis.__httpCalls.filter((u) => u === "/api/metadata/locales").length === 1, "same-instance reload refetches catalog");
assert(globalThis.__httpCalls.filter((u) => u === "/api/metadata/locales/presence").length === 1, "same-instance reload refetches presence");

resetLocaleCatalog();
globalThis.__httpCalls = [];
globalThis.__catalogError = new Error("catalog down");
const failed = useLocaleCatalog({ presence: false });
await failed.load();
assert(failed.error.value === "catalog down", "catalog error stays on error ref");
assert(failed.rows.value.length === 0, "failed catalog leaves rows empty");

resetLocaleCatalog();
globalThis.__catalogError = null;
globalThis.__presenceError = new Error("presence down");
globalThis.__httpCalls = [];
const degr = useLocaleCatalog({ presence: true });
await degr.load();
assert(degr.rows.value.length === 2, "presence failure still keeps catalog");
assert(degr.presenceAvailable.value === false, "presence failure degrades");
assert(degr.error.value === "", "presence failure must not replace catalog error");

console.log("ok");
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(runner)],
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout
