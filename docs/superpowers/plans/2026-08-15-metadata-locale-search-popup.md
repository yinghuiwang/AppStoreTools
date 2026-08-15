# Metadata Locale Search Popup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only App Store Connect locale-code search popup on `/metadata` so users can search the static 50-locale catalog and copy a `code` (for example `zh-Hans`) without changing CSV, upload selection, or listings.

**Architecture:** Ship a packaged JSON catalog at `src/asc/data/asc_locales.json`. `src/asc/locales_catalog.py` reads and validates it on every call (no process cache, no network). `GET /api/metadata/locales` (sync handler in `src/asc/web/routes_api.py`) returns the full catalog plus a `present` overlay from the current editable version’s version localizations. The `/metadata` Alpine page opens a `fixed inset-0` modal, filters client-side, and copies `code` to the clipboard.

**Tech Stack:** Python 3.9+, FastAPI, Jinja2, Alpine.js, existing Web i18n (`src/asc/web/locales/{zh,en}.json`, `window.t`), pytest + FastAPI TestClient.

## Global Constraints

- Read-only lookup: never mutate CSV, `locales_json` / `fields_by_locale_json` / `screenshot_scopes_json`, upload checkboxes, listing save/pull, or App Store Connect localizations/versions.
- Search source of truth is the packaged JSON catalog, not Apple’s runtime enum and not `CSV_LOCALE_TO_ASC`.
- Click copies the row `code` verbatim (not `DisplayName(code)`); keep the modal open.
- Web i18n only. Do not add keys to CLI `src/asc/i18n.py`. Do not add a CLI locale picker.
- Leave `CSV_LOCALE_TO_ASC` and `SCREENSHOT_FOLDER_TO_LOCALE` unchanged. Do not modify `_upload_metadata_core`.
- `GET /api/metadata/locales` is `sync def` (same reason as `metadata_check`: keep ASC I/O off the event loop). No `q` query parameter.
- `list_locales()` reads disk and validates on every call; no process-level cache.
- Tests mock ASC. Do not enable `ASC_TEST_LIVE`. No Playwright/Selenium.
- Catalog load failure → HTTP 500 with `{ "error": <t("metadata.locales_catalog_unavailable")> }`. Never return `locales: []` to mean “catalog missing”.
- Presence fetch failure → HTTP 200 + full catalog + all `present: false` + `presenceAvailable: false`. Guard conflicts must not become HTTP 409.
- Python 3.9+ (`from __future__ import annotations`, `importlib.resources.files`).

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `src/asc/data/asc_locales.json` | Static 50-locale array (`code`, `name_en`, `name_zh`). Not a Python package; no `__init__.py`. |
| `src/asc/locales_catalog.py` | `LocaleCatalogError`, `list_locales(path=None)`, `filter_locales(query, items)`. No network. |
| `src/asc/web/routes_api.py` | `GET /metadata/locales` (mounted at `/api/metadata/locales`) + presence overlay helper. |
| `src/asc/web/locales/zh.json` | Chinese popup copy. |
| `src/asc/web/locales/en.json` | English popup copy. |
| `src/asc/web/templates/metadata.html` | Toolbar button, Alpine `localeCatalog` state/methods, modal markup. |
| `tests/test_locales_catalog.py` | Catalog load, validation, filter algorithm. |
| `tests/test_web_metadata_locales.py` | API presence/degrade/500/CSV-unchanged + GET `/metadata` HTML assertions. |

**Do not create or modify:** `src/asc/constants.py`, `src/asc/i18n.py`, `src/asc/commands/metadata.py`, `src/asc/web/routes_listing.py`, `pyproject.toml` (hatchling `packages = ["src/asc"]` already ships non-Python files under the package, same as `src/asc/web/locales/*.json`).

### Code-path notes (spec wins; these are file-accurate)

1. Router is `APIRouter()` included with `prefix="/api"` in `src/asc/web/server.py`. Declare `@router.get("/metadata/locales")` next to `metadata_check` (`src/asc/web/routes_api.py` around line 416).
2. `_get_available_locales(api, app_id)` (line 2173) itself calls `get_editable_version` and returns `[]` when there is no editable version. The handler **must** call `api.get_editable_version(app_id)` first and treat `None` as `presenceAvailable: false`. After a version exists, calling `_get_available_locales` again is acceptable (one extra `get_editable_version`).
3. `_enforce_web_profile_guard` raises `HTTPException(status_code=409)`. **Do not call it.** Presence overlay should call `enforce_config_guard(config, interactive=False)` and catch `GuardViolationError`.
4. `make_api_from_config` (`src/asc/utils.py:312`) raises `typer.Exit` (a `RuntimeError`) when credentials are missing. Catch `Exception` in the presence helper so that becomes degrade-not-500. Do not catch `LocaleCatalogError` there.
5. Alpine root is `#metadata-page-state` (`metadata.html` line 17). The `x-data="{ ... }"` object ends at line 997 (`}">`). Add `localeCatalog` state near the top of that object and methods just before the closing `}">`. The screenshot lightbox (line 1532, `z-[60]`) is inside this root; `#filebrowser-modal` (line 1626) is **outside** it — put the locale modal **inside** `#metadata-page-state`, beside the lightbox, using the What’s New edit modal / filebrowser visual pattern (`fixed inset-0`, `z-50`, `background: rgba(0,0,0,0.6)`, `@click.self` to close).
6. `window.t` and `window.__ASC_LANG` are already injected in `src/asc/web/templates/base.html`. Do not hardcode new Chinese/English strings in Alpine.
7. `src/asc/web/i18n.py` `load_catalog` is `@lru_cache`. New keys are picked up in a new pytest process; no need to call `cache_clear` if tests start after the JSON files are saved.
8. Toolbar target: first `.listing-wb-bar__end` (around line 1117), sibling of “加载预览” / “加载 Diff”. No `x-show` on `wb.tab` — button visible on both tabs.

---

### Task 1: Static locale catalog module

**Files:**
- Create: `src/asc/data/asc_locales.json`
- Create: `src/asc/locales_catalog.py`
- Test: `tests/test_locales_catalog.py`

**Interfaces:**
- Consumes: packaged JSON at `asc/data/asc_locales.json` via `importlib.resources.files("asc").joinpath("data/asc_locales.json")`.
- Produces:
  - `class LocaleCatalogError(Exception)`
  - `def list_locales(path: str | Path | None = None) -> list[dict[str, str]]` — each dict is exactly `{"code", "name_en", "name_zh"}` with stripped non-empty strings; `code` unique. Raises `LocaleCatalogError` on missing file, invalid JSON, non-list root, non-object item, missing/blank fields, or duplicate `code`. Ignores unknown fields. Does not call `normalize_locale_code`. Does not cache. Default `path=None` reads the packaged file; tests pass a temp path.
  - `def filter_locales(query: str, items: list[dict[str, str]]) -> list[dict[str, str]]` — `q = query.strip()`; empty `q` keeps all; otherwise case-insensitive substring match on `code` / `name_en` / `name_zh` using `str.casefold()`; result sorted with `sorted(..., key=lambda x: x["code"])`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_locales_catalog.py`:

```python
from __future__ import annotations

import json

import pytest

from asc.locales_catalog import LocaleCatalogError, filter_locales, list_locales

REQUIRED_V1 = {"en-US", "zh-Hans", "zh-Hant", "ja"}

SAMPLE = [
    {"code": "zh-Hans", "name_en": "Chinese (Simplified)", "name_zh": "简体中文"},
    {"code": "zh-Hant", "name_en": "Chinese (Traditional)", "name_zh": "繁体中文"},
    {"code": "en-US", "name_en": "English (U.S.)", "name_zh": "英语（美国）"},
    {"code": "ja", "name_en": "Japanese", "name_zh": "日语"},
]


def test_list_locales_loads_packaged_catalog():
    items = list_locales()
    assert len(items) == 50
    codes = [row["code"] for row in items]
    assert len(codes) == len(set(codes))
    assert REQUIRED_V1 <= set(codes)
    for row in items:
        assert set(row) == {"code", "name_en", "name_zh"}
        assert row["code"].strip() == row["code"] != ""
        assert row["name_en"].strip() == row["name_en"] != ""
        assert row["name_zh"].strip() == row["name_zh"] != ""


def test_list_locales_reads_override_path(tmp_path):
    p = tmp_path / "catalog.json"
    p.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")
    items = list_locales(p)
    assert [row["code"] for row in items] == ["zh-Hans", "zh-Hant", "en-US", "ja"]


def test_list_locales_strips_and_drops_unknown_fields(tmp_path):
    p = tmp_path / "catalog.json"
    p.write_text(
        json.dumps(
            [
                {
                    "code": "  ja  ",
                    "name_en": " Japanese ",
                    "name_zh": " 日语 ",
                    "extra": "ignore-me",
                }
            ]
        ),
        encoding="utf-8",
    )
    items = list_locales(p)
    assert items == [{"code": "ja", "name_en": "Japanese", "name_zh": "日语"}]


@pytest.mark.parametrize(
    "payload",
    [
        {"locales": SAMPLE},
        [{"name_en": "Japanese", "name_zh": "日语"}],
        [{"code": "", "name_en": "Japanese", "name_zh": "日语"}],
        [{"code": "ja", "name_en": "   ", "name_zh": "日语"}],
        [{"code": "ja", "name_en": "Japanese", "name_zh": "日语"}, {"code": "ja", "name_en": "J", "name_zh": "日"}],
        ["ja"],
    ],
)
def test_list_locales_rejects_corrupt_catalog(tmp_path, payload):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(LocaleCatalogError):
        list_locales(p)


def test_list_locales_rejects_missing_and_invalid_json(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(LocaleCatalogError):
        list_locales(missing)
    p = tmp_path / "not.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(LocaleCatalogError):
        list_locales(p)


def test_filter_locales_empty_query_returns_all_sorted():
    out = filter_locales("  ", SAMPLE)
    assert [row["code"] for row in out] == ["en-US", "ja", "zh-Hans", "zh-Hant"]


def test_filter_locales_hans_simplified_chinese():
    items = filter_locales("hans", SAMPLE)
    assert [row["code"] for row in items] == ["zh-Hans"]
    items = filter_locales("简体", SAMPLE)
    assert [row["code"] for row in items] == ["zh-Hans"]
    items = filter_locales("chinese", SAMPLE)
    assert [row["code"] for row in items] == ["zh-Hans", "zh-Hant"]
    items = filter_locales("CHINESE", SAMPLE)
    assert [row["code"] for row in items] == ["zh-Hans", "zh-Hant"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_locales_catalog.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'asc.locales_catalog'` (or import error for `list_locales`).

- [ ] **Step 3: Write minimal implementation**

Create `src/asc/data/asc_locales.json` as a JSON **array** (not `{"locales":[...]}`) with exactly these 50 objects, UTF-8, no `zh-HK`:

```json
[
  {"code": "ar-SA", "name_en": "Arabic", "name_zh": "阿拉伯语"},
  {"code": "bn-BD", "name_en": "Bengali", "name_zh": "孟加拉语"},
  {"code": "ca", "name_en": "Catalan", "name_zh": "加泰罗尼亚语"},
  {"code": "cs", "name_en": "Czech", "name_zh": "捷克语"},
  {"code": "da", "name_en": "Danish", "name_zh": "丹麦语"},
  {"code": "de-DE", "name_en": "German", "name_zh": "德语"},
  {"code": "el", "name_en": "Greek", "name_zh": "希腊语"},
  {"code": "en-AU", "name_en": "English (Australia)", "name_zh": "英语（澳大利亚）"},
  {"code": "en-CA", "name_en": "English (Canada)", "name_zh": "英语（加拿大）"},
  {"code": "en-GB", "name_en": "English (U.K.)", "name_zh": "英语（英国）"},
  {"code": "en-US", "name_en": "English (U.S.)", "name_zh": "英语（美国）"},
  {"code": "es-ES", "name_en": "Spanish (Spain)", "name_zh": "西班牙语（西班牙）"},
  {"code": "es-MX", "name_en": "Spanish (Mexico)", "name_zh": "西班牙语（墨西哥）"},
  {"code": "fi", "name_en": "Finnish", "name_zh": "芬兰语"},
  {"code": "fr-CA", "name_en": "French (Canada)", "name_zh": "法语（加拿大）"},
  {"code": "fr-FR", "name_en": "French", "name_zh": "法语"},
  {"code": "gu-IN", "name_en": "Gujarati", "name_zh": "古吉拉特语"},
  {"code": "he", "name_en": "Hebrew", "name_zh": "希伯来语"},
  {"code": "hi", "name_en": "Hindi", "name_zh": "印地语"},
  {"code": "hr", "name_en": "Croatian", "name_zh": "克罗地亚语"},
  {"code": "hu", "name_en": "Hungarian", "name_zh": "匈牙利语"},
  {"code": "id", "name_en": "Indonesian", "name_zh": "印度尼西亚语"},
  {"code": "it", "name_en": "Italian", "name_zh": "意大利语"},
  {"code": "ja", "name_en": "Japanese", "name_zh": "日语"},
  {"code": "kn-IN", "name_en": "Kannada", "name_zh": "卡纳达语"},
  {"code": "ko", "name_en": "Korean", "name_zh": "韩语"},
  {"code": "ml-IN", "name_en": "Malayalam", "name_zh": "马拉雅拉姆语"},
  {"code": "mr-IN", "name_en": "Marathi", "name_zh": "马拉地语"},
  {"code": "ms", "name_en": "Malay", "name_zh": "马来语"},
  {"code": "nl-NL", "name_en": "Dutch", "name_zh": "荷兰语"},
  {"code": "no", "name_en": "Norwegian", "name_zh": "挪威语"},
  {"code": "or-IN", "name_en": "Oriya", "name_zh": "奥里亚语"},
  {"code": "pa-IN", "name_en": "Punjabi", "name_zh": "旁遮普语"},
  {"code": "pl", "name_en": "Polish", "name_zh": "波兰语"},
  {"code": "pt-BR", "name_en": "Portuguese (Brazil)", "name_zh": "葡萄牙语（巴西）"},
  {"code": "pt-PT", "name_en": "Portuguese (Portugal)", "name_zh": "葡萄牙语（葡萄牙）"},
  {"code": "ro", "name_en": "Romanian", "name_zh": "罗马尼亚语"},
  {"code": "ru", "name_en": "Russian", "name_zh": "俄语"},
  {"code": "sk", "name_en": "Slovak", "name_zh": "斯洛伐克语"},
  {"code": "sl-SI", "name_en": "Slovenian", "name_zh": "斯洛文尼亚语"},
  {"code": "sv", "name_en": "Swedish", "name_zh": "瑞典语"},
  {"code": "ta-IN", "name_en": "Tamil", "name_zh": "泰米尔语"},
  {"code": "te-IN", "name_en": "Telugu", "name_zh": "泰卢固语"},
  {"code": "th", "name_en": "Thai", "name_zh": "泰语"},
  {"code": "tr", "name_en": "Turkish", "name_zh": "土耳其语"},
  {"code": "uk", "name_en": "Ukrainian", "name_zh": "乌克兰语"},
  {"code": "ur-PK", "name_en": "Urdu", "name_zh": "乌尔都语"},
  {"code": "vi", "name_en": "Vietnamese", "name_zh": "越南语"},
  {"code": "zh-Hans", "name_en": "Chinese (Simplified)", "name_zh": "简体中文"},
  {"code": "zh-Hant", "name_en": "Chinese (Traditional)", "name_zh": "繁体中文"}
]
```

Create `src/asc/locales_catalog.py`:

```python
from __future__ import annotations

import importlib.resources
import json
from pathlib import Path
from typing import Any


class LocaleCatalogError(Exception):
    """Raised when the static App Store Connect locale catalog cannot be loaded."""


def _default_catalog_resource():
    return importlib.resources.files("asc").joinpath("data/asc_locales.json")


def _read_text(path: str | Path | None) -> str:
    if path is None:
        resource = _default_catalog_resource()
        try:
            return resource.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise LocaleCatalogError("locale catalog is unavailable") from exc
    catalog_path = Path(path)
    try:
        return catalog_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError) as exc:
        raise LocaleCatalogError("locale catalog is unavailable") from exc


def _require_nonempty_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise LocaleCatalogError(f"locale field {field} must be a string")
    text = value.strip()
    if not text:
        raise LocaleCatalogError(f"locale field {field} must be non-empty")
    return text


def list_locales(path: str | Path | None = None) -> list[dict[str, str]]:
    raw = _read_text(path)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LocaleCatalogError("locale catalog is not valid JSON") from exc
    if not isinstance(payload, list):
        raise LocaleCatalogError("locale catalog root must be a list")

    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            raise LocaleCatalogError("locale catalog entries must be objects")
        code = _require_nonempty_str(entry.get("code"), "code")
        name_en = _require_nonempty_str(entry.get("name_en"), "name_en")
        name_zh = _require_nonempty_str(entry.get("name_zh"), "name_zh")
        if code in seen:
            raise LocaleCatalogError(f"duplicate locale code: {code}")
        seen.add(code)
        items.append({"code": code, "name_en": name_en, "name_zh": name_zh})
    return items


def filter_locales(query: str, items: list[dict[str, str]]) -> list[dict[str, str]]:
    q = (query or "").strip().casefold()
    if not q:
        matched = list(items)
    else:
        matched = []
        for item in items:
            haystacks = (
                str(item.get("code") or ""),
                str(item.get("name_en") or ""),
                str(item.get("name_zh") or ""),
            )
            if any(q in field.casefold() for field in haystacks):
                matched.append(item)
    return sorted(matched, key=lambda row: row["code"])
```

Do not add `src/asc/data/__init__.py`. Do not change `pyproject.toml`. Do not import `normalize_locale_code`. Runtime validation does **not** require the four v1 codes or a count of 50 on override paths (those are properties of the packaged file, covered by `test_list_locales_loads_packaged_catalog`).

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `pytest tests/test_locales_catalog.py -v`

Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/asc/data/asc_locales.json src/asc/locales_catalog.py tests/test_locales_catalog.py
git commit -m "$(cat <<'EOF'
feat(web): add static ASC locale catalog

EOF
)"
```

---

### Task 2: Web i18n keys and `GET /api/metadata/locales`

**Files:**
- Modify: `src/asc/web/locales/zh.json` (insert the new `metadata.locales_*` keys immediately before `"urls.title"`, after `"metadata.diff_shots_confirm"`)
- Modify: `src/asc/web/locales/en.json` (same key order)
- Modify: `src/asc/web/routes_api.py` — add import; add `_metadata_locale_presence`; add `@router.get("/metadata/locales")` immediately after `metadata_check` (after line 423)
- Test: `tests/test_web_metadata_locales.py`

**Interfaces:**
- Consumes: `list_locales()` / `LocaleCatalogError` from Task 1; `_cookie_profile`, `_lang`, `_get_available_locales`, `Config`, `make_api_from_config`, `enforce_config_guard` already in `routes_api.py`.
- Produces: `GET /api/metadata/locales` with no query params. Success JSON: `{"locales": [{"code", "name_en", "name_zh", "present"}], "presenceAvailable": bool}`. Catalog error JSON: `{"error": <translated metadata.locales_catalog_unavailable>}` HTTP 500. Profile cookie is `asc_profile` only.

Presence overlay rules (implement in `_metadata_locale_presence(profile: str, catalog: list[dict[str, str]]) -> tuple[list[dict], bool]`):

1. If `profile` is empty → all `present: false`, `presenceAvailable: false`.
2. Else try, in order: `Config(app_name=profile)` → `make_api_from_config(config)` → `enforce_config_guard(config, interactive=False)` → `api.get_editable_version(app_id)`.
3. If version is missing/`None` → degrade (`presenceAvailable: false`). Do **not** infer availability from `_get_available_locales` returning `[]`.
4. If version exists → build a set of localization `locale` strings (via `_get_available_locales(api, app_id)` or `api.get_version_localizations(version["id"])`). Catalog `code` **string-equals** a set member → `present: true`. ASC codes absent from the catalog are dropped (do not insert extra rows). Empty localization list → `presenceAvailable: true`, all `present: false`.
5. Any `GuardViolationError`, `typer.Exit` / missing config, timeout, 401/403, or other exception in this helper → degrade to HTTP 200 catalog with `presenceAvailable: false`. Never re-raise as 409.
6. Only `list_locales()` failure becomes 500, using `JSONResponse` with `{"error": ...}` (not FastAPI `{"detail": ...}`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_metadata_locales.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_metadata_locales.py -v`

Expected: FAIL with `404` on `GET /api/metadata/locales` (route missing). Catalog-error test cannot pass until the route and i18n keys exist.

- [ ] **Step 3: Write minimal implementation**

Insert these keys into `src/asc/web/locales/zh.json` immediately after `"metadata.diff_shots_confirm"` and before `"urls.title"`:

```json
  "metadata.locales_btn": "语言码",
  "metadata.locales_title": "App Store Connect 语言码",
  "metadata.locales_search": "搜索语言码或名称",
  "metadata.locales_copied": "已复制",
  "metadata.locales_copy_failed": "复制失败，请手动选择",
  "metadata.locales_empty": "无匹配语言码",
  "metadata.locales_catalog_unavailable": "语言码目录不可用",
  "metadata.locales_presence_unavailable": "无法标记当前版本已有语言",
  "metadata.locales_present": "已有",
  "metadata.locales_refresh": "刷新",
  "metadata.locales_hint": "点击一行复制语言码，不会改动 CSV 或上传范围",
  "metadata.locales_close": "关闭",
```

Insert the English pair into `src/asc/web/locales/en.json` at the same position:

```json
  "metadata.locales_btn": "Locale codes",
  "metadata.locales_title": "App Store Connect locale codes",
  "metadata.locales_search": "Search codes or names",
  "metadata.locales_copied": "Copied",
  "metadata.locales_copy_failed": "Copy failed. Select the code manually.",
  "metadata.locales_empty": "No matching locale codes",
  "metadata.locales_catalog_unavailable": "Locale catalog is unavailable",
  "metadata.locales_presence_unavailable": "Could not mark locales already on this version",
  "metadata.locales_present": "On version",
  "metadata.locales_refresh": "Refresh",
  "metadata.locales_hint": "Click a row to copy the locale code. This does not change the CSV or upload selection.",
  "metadata.locales_close": "Close",
```

In `src/asc/web/routes_api.py`, add this import next to the other `asc.*` imports (around line 28):

```python
from asc.locales_catalog import LocaleCatalogError, list_locales
```

Add `GuardViolationError` to the existing guard import:

```python
from asc.guard import (
    GuardViolationError,
    enforce_bundle_guard,
    enforce_config_guard,
    read_ipa_bundle_id,
)
```

Immediately after `metadata_check` (after the `return _run_metadata_check(...)` function, before `@router.post("/metadata/run")`), insert:

```python
def _absent_locales(catalog: list[dict[str, str]]) -> list[dict]:
    return [
        {
            "code": row["code"],
            "name_en": row["name_en"],
            "name_zh": row["name_zh"],
            "present": False,
        }
        for row in catalog
    ]


def _metadata_locale_presence(
    profile: str,
    catalog: list[dict[str, str]],
) -> tuple[list[dict], bool]:
    """Overlay present flags. Never raises; failures degrade presence only."""
    if not profile:
        return _absent_locales(catalog), False
    try:
        config = Config(app_name=profile)
        api, app_id = make_api_from_config(config)
        enforce_config_guard(config, interactive=False)
        version = api.get_editable_version(app_id)
        if not version:
            return _absent_locales(catalog), False
        present_codes = {
            item["locale"] for item in _get_available_locales(api, app_id)
        }
        locales = [
            {
                "code": row["code"],
                "name_en": row["name_en"],
                "name_zh": row["name_zh"],
                "present": row["code"] in present_codes,
            }
            for row in catalog
        ]
        return locales, True
    except (GuardViolationError, Exception):
        return _absent_locales(catalog), False


@router.get("/metadata/locales")
def metadata_locales(request: Request):
    """Return the static locale catalog with optional version-presence overlay.

    Sync ``def`` so ASC presence checks stay off the event loop.
    """
    lang = _lang(request)
    try:
        catalog = list_locales()
    except LocaleCatalogError:
        return JSONResponse(
            {"error": t("metadata.locales_catalog_unavailable", lang=lang)},
            status_code=500,
        )
    locales, presence_available = _metadata_locale_presence(
        _cookie_profile(request),
        catalog,
    )
    return {"locales": locales, "presenceAvailable": presence_available}
```

Do not call `_enforce_web_profile_guard`. Do not read CSV paths. Do not accept a `q` parameter. Do not change `metadata_run` / listing handlers.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `pytest tests/test_web_metadata_locales.py -v`

Expected: PASS.

If `test_metadata_locales_catalog_error_is_500_localized` still sees the raw key `metadata.locales_catalog_unavailable`, the JSON files were not saved or `load_catalog` was cached in a long-lived process — keys must exist in both `zh.json` and `en.json`.

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/locales/zh.json src/asc/web/locales/en.json src/asc/web/routes_api.py tests/test_web_metadata_locales.py
git commit -m "$(cat <<'EOF'
feat(web): add metadata locale catalog API

EOF
)"
```

---

### Task 3: `/metadata` toolbar button, Alpine modal, HTML assertions

**Files:**
- Modify: `src/asc/web/templates/metadata.html`
  - Alpine state: inside `#metadata-page-state` `x-data` (starts line 17)
  - Alpine methods: just before the `x-data` closer at line 997
  - Toolbar button: first `.listing-wb-bar__end` (around line 1117)
  - Modal markup: inside `#metadata-page-state`, immediately before the screenshot lightbox (line 1532)
- Test: `tests/test_web_metadata_locales.py` (append HTML + i18n + regression tests)

**Interfaces:**
- Consumes: `GET /api/metadata/locales` from Task 2; i18n keys from Task 2; `window.t` / `window.__ASC_LANG` from `base.html`.
- Produces: toolbar button + modal behavior described below. No new JS files. No localStorage for the catalog (form localStorage at `_METADATA_STORE_KEY` is unrelated and must stay untouched).

UI rules to implement exactly:

- Button label: `t("metadata.locales_btn")`. Always enabled; does not require CSV/Diff loaded or an App selected.
- Opening sets `localeCatalog.open = true` and fetches only when `!loaded && !loading`. Repeat open with `loaded` must not fetch.
- Refresh calls fetch with force=true and **does not** clear `query`.
- Search: client-side only. `q = query.trim()`; empty → all rows; else `code` / `name_en` / `name_zh` via `String.prototype.toLowerCase()` + `includes`; then sort by `code` using `<` / `>` (Unicode code unit order matches Python `sorted(..., key=lambda x: x["code"])` for this ASCII-code catalog).
- Display name: `window.__ASC_LANG === 'zh' ? row.name_zh : row.name_en`.
- `present` → `badge badge-info` with `metadata.locales_present`. Not a separate tab. Do not sort present rows first.
- If `presenceAvailable === false` after a successful load, show `metadata.locales_presence_unavailable` as a weak banner.
- Loading: list region shows `common.loading`.
- HTTP 500 / catalog error: list region shows `metadata.locales_catalog_unavailable` plus refresh; **do not** render an empty table. `loaded` stays false.
- Browser fetch failure: error state, `loaded` false, refresh allowed.
- No matches: `metadata.locales_empty`; keep `locales` in memory.
- Click row copies `code` only. Prefer `navigator.clipboard.writeText`; fallback temporary `textarea` + `document.execCommand('copy')`. Success: row shows `metadata.locales_copied` for 2000ms, modal stays open. Failure: row shows `metadata.locales_copy_failed`. The copy function must not write `#locales-json-input` / listing save / `/api/listing/` / `/api/metadata/run`.
- Esc closes (`@keydown.escape.window` when open). Click dimmed overlay closes (`@click.self`). `z-50`. Lightbox remains `z-[60]`.
- Autofocus the search input when opening (`x-ref` + `$nextTick(...focus())`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_metadata_locales.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_metadata_locales.py::test_metadata_page_has_locale_search_popup_markup tests/test_web_metadata_locales.py::test_metadata_page_locale_button_localized -v`

Expected: FAIL because `localeCatalogOpen` / `/api/metadata/locales` are not yet in `metadata.html` (the API string may already appear if you grep routes, but the template will not contain `localeCatalogOpen`).

- [ ] **Step 3: Write minimal implementation**

**3a. Alpine state.** In `src/asc/web/templates/metadata.html`, inside the `#metadata-page-state` `x-data` object, immediately after the `diff: { ... },` block (around line 35), add:

```javascript
    localeCatalog: {
      open: false,
      loaded: false,
      loading: false,
      error: '',
      locales: [],
      presenceAvailable: false,
      query: '',
      copiedCode: '',
      copyFailedCode: '',
      copyTimer: null,
    },
```

**3b. Alpine methods.** Immediately before the `x-data` closer (`    },\n  }">` that currently ends `wbDiffPullScreenshots`, around line 996–997), add a comma after the previous method and insert:

```javascript
    localeCatalogOpen() {
      this.localeCatalog.open = true;
      this.localeCatalog.copyFailedCode = '';
      this.$nextTick(() => {
        const el = this.$refs.localeSearch;
        if (el && typeof el.focus === 'function') el.focus();
      });
      this.localeCatalogEnsureLoaded(false);
    },

    localeCatalogClose() {
      this.localeCatalog.open = false;
    },

    localeCatalogRefresh() {
      this.localeCatalogEnsureLoaded(true);
    },

    localeCatalogEnsureLoaded(force) {
      if (!force && (this.localeCatalog.loaded || this.localeCatalog.loading)) return;
      this.localeCatalog.loading = true;
      this.localeCatalog.error = '';
      fetch('/api/metadata/locales')
        .then(async r => {
          const data = await r.json().catch(() => ({}));
          if (!r.ok) {
            throw new Error(data.error || window.t('metadata.locales_catalog_unavailable'));
          }
          this.localeCatalog.locales = data.locales || [];
          this.localeCatalog.presenceAvailable = !!data.presenceAvailable;
          this.localeCatalog.loaded = true;
          this.localeCatalog.error = '';
        })
        .catch(e => {
          this.localeCatalog.loaded = false;
          this.localeCatalog.locales = [];
          this.localeCatalog.presenceAvailable = false;
          this.localeCatalog.error = e.message || window.t('metadata.locales_catalog_unavailable');
        })
        .finally(() => { this.localeCatalog.loading = false; });
    },

    localeCatalogFiltered() {
      const items = this.localeCatalog.locales || [];
      const q = (this.localeCatalog.query || '').trim().toLowerCase();
      const matched = !q ? items.slice() : items.filter(row => {
        const code = String(row.code || '').toLowerCase();
        const en = String(row.name_en || '').toLowerCase();
        const zh = String(row.name_zh || '').toLowerCase();
        return code.indexOf(q) !== -1 || en.indexOf(q) !== -1 || zh.indexOf(q) !== -1;
      });
      return matched.slice().sort((a, b) => {
        const left = String(a.code || '');
        const right = String(b.code || '');
        if (left < right) return -1;
        if (left > right) return 1;
        return 0;
      });
    },

    localeCatalogDisplayName(row) {
      return window.__ASC_LANG === 'zh' ? row.name_zh : row.name_en;
    },

    localeCatalogCopy(code) {
      const value = String(code || '');
      const markOk = () => {
        this.localeCatalog.copyFailedCode = '';
        this.localeCatalog.copiedCode = value;
        if (this.localeCatalog.copyTimer) clearTimeout(this.localeCatalog.copyTimer);
        this.localeCatalog.copyTimer = setTimeout(() => {
          if (this.localeCatalog.copiedCode === value) this.localeCatalog.copiedCode = '';
        }, 2000);
      };
      const markFail = () => {
        this.localeCatalog.copiedCode = '';
        this.localeCatalog.copyFailedCode = value;
      };
      const fallbackCopy = () => {
        const ta = document.createElement('textarea');
        ta.value = value;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        let ok = false;
        try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
        ta.remove();
        return ok;
      };
      const done = (ok) => { if (ok) markOk(); else markFail(); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(() => done(true)).catch(() => {
          done(fallbackCopy());
        });
        return;
      }
      done(fallbackCopy());
    },
```

**3c. Toolbar button.** In the first `.listing-wb-bar__end` (the one that contains load-preview / load-diff), add the locale button **before** the unsaved span so it stays visible on both tabs:

```html
                <div class="listing-wb-bar__end">
                  <button type="button" class="btn-ghost" @click="localeCatalogOpen()" x-text="window.t('metadata.locales_btn')"></button>
                  <span x-show="wb.dirty" class="listing-wb-msg" style="color: var(--accent);">{{ t("metadata.unsaved") }}</span>
                  <button type="button" class="btn-ghost" x-show="wb.tab === 'local'" :disabled="wb.loading" @click="wbLoadPreview()">
```

**3d. Modal.** Immediately before `<!-- Screenshot lightbox -->` (line 1532), still inside `#metadata-page-state`, insert:

```html
    <div x-show="localeCatalog.open" x-cloak
         class="fixed inset-0 flex items-center justify-center z-50"
         style="background: rgba(0,0,0,0.6); backdrop-filter: blur(4px);"
         @keydown.escape.window="if (localeCatalog.open) localeCatalogClose()"
         @click.self="localeCatalogClose()">
      <div class="card w-[520px] max-w-[calc(100vw-32px)]" @click.stop>
        <div class="card-header flex items-center justify-between gap-3">
          <h3 class="text-xs uppercase tracking-widest text-obsidian-400 font-medium" x-text="window.t('metadata.locales_title')"></h3>
          <div class="flex items-center gap-2">
            <button type="button" class="btn-ghost" :disabled="localeCatalog.loading" @click="localeCatalogRefresh()" x-text="window.t('metadata.locales_refresh')"></button>
            <button type="button"
                    class="text-obsidian-500 hover:text-obsidian-300 cursor-pointer transition-colors duration-150 p-1 rounded focus-ring"
                    :title="window.t('metadata.locales_close')"
                    @click="localeCatalogClose()">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12"/></svg>
            </button>
          </div>
        </div>
        <div class="card-body space-y-3">
          <p class="listing-wb-hint"
             x-show="localeCatalog.loaded && !localeCatalog.presenceAvailable"
             x-text="window.t('metadata.locales_presence_unavailable')"></p>
          <input type="search"
                 x-ref="localeSearch"
                 x-model="localeCatalog.query"
                 class="field-input w-full"
                 :placeholder="window.t('metadata.locales_search')"
                 autocomplete="off">
          <div class="max-h-[min(60vh,420px)] overflow-y-auto">
            <p class="listing-wb-hint" x-show="localeCatalog.loading" x-text="window.t('common.loading')"></p>
            <p class="listing-wb-msg" style="color: var(--error);"
               x-show="!localeCatalog.loading && localeCatalog.error"
               x-text="localeCatalog.error"></p>
            <p class="listing-wb-hint"
               x-show="!localeCatalog.loading && !localeCatalog.error && localeCatalog.loaded && localeCatalogFiltered().length === 0"
               x-text="window.t('metadata.locales_empty')"></p>
            <div class="flex flex-col gap-1"
                 x-show="!localeCatalog.loading && !localeCatalog.error && localeCatalog.loaded">
              <template x-for="row in localeCatalogFiltered()" :key="row.code">
                <button type="button"
                        class="w-full text-left px-2 py-1.5 rounded hover:bg-obsidian-800/80 flex items-center gap-2"
                        @click="localeCatalogCopy(row.code)">
                  <span class="font-mono text-sm text-obsidian-100" x-text="row.code"></span>
                  <span class="text-xs text-obsidian-400 truncate" x-text="localeCatalogDisplayName(row)"></span>
                  <span class="badge badge-info ml-auto"
                        x-show="row.present && localeCatalog.copiedCode !== row.code && localeCatalog.copyFailedCode !== row.code"
                        x-text="window.t('metadata.locales_present')"></span>
                  <span class="text-xs ml-auto" style="color: var(--success);"
                        x-show="localeCatalog.copiedCode === row.code"
                        x-text="window.t('metadata.locales_copied')"></span>
                  <span class="text-xs ml-auto" style="color: var(--error);"
                        x-show="localeCatalog.copyFailedCode === row.code"
                        x-text="window.t('metadata.locales_copy_failed')"></span>
                </button>
              </template>
            </div>
          </div>
          <p class="listing-wb-hint" x-text="window.t('metadata.locales_hint')"></p>
        </div>
      </div>
    </div>
```

Error-state refresh: the header Refresh button is always visible, including when `localeCatalog.error` is set. Do not render a `<table>` on catalog failure. Do not add a second copy button per row.

Do not reference `locales-json-input` inside `localeCatalogCopy`. Do not write `localStorage` inside any `localeCatalog*` method.

- [ ] **Step 4: Run the tests and make sure they pass**

Run:

```bash
pytest tests/test_web_metadata_locales.py tests/test_locales_catalog.py tests/test_web_listing.py tests/test_web_i18n.py -v
```

Expected: PASS. `tests/test_web_listing.py` must still pass (`/api/metadata/run`, listing save/pull unchanged). `tests/test_web_i18n.py` confirms `/metadata` still switches language via `asc_lang`.

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/templates/metadata.html tests/test_web_metadata_locales.py
git commit -m "$(cat <<'EOF'
feat(web): add metadata locale search popup

EOF
)"
```

---

## Self-review (author)

**Spec coverage**

| Spec section | Task |
|--------------|------|
| Static JSON 50 locales + validation | Task 1 |
| `list_locales` / `filter_locales` / no network / no cache | Task 1 |
| `GET /api/metadata/locales` contract, presence overlay, Guard/ASC degrade, 500 on catalog error | Task 2 |
| i18n keys (zh/en pair) | Task 2 |
| Toolbar button both tabs, modal, search, copy, cache, Esc, refresh | Task 3 |
| HTML assertions, no Playwright, listing regression | Task 3 |
| Non-goals (CSV/upload/CLI/`CSV_LOCALE_TO_ASC`/`_upload_metadata_core`) | Global Constraints + “Do not modify” |

**Placeholder scan:** none. Task 3 copies the full Alpine methods and modal markup rather than “similar to filebrowser”.

**Type consistency:** `list_locales` → `list[dict[str, str]]` with `code`/`name_en`/`name_zh`; API adds `present: bool` and `presenceAvailable: bool`; Alpine `localeCatalog.locales` is that API array. Filter helpers take `(query, items)` in Python and read `localeCatalog.query` in JS.
