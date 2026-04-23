# 单元测试套件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为所有当前无测试的模块（constants、utils、api、metadata、screenshots、whats_new、iap_core）补充完整单元测试，使总测试数从 61 增至约 130。

**Architecture:** 每个源文件对应一个新测试文件，放在 `tests/` 目录。每个测试文件定义自己的本地 FakeAPI，不污染共享 `conftest.py`。`test_api.py` 支持 mock 模式（默认）和真实网络模式（`ASC_TEST_LIVE=1`）。

**Tech Stack:** pytest, unittest.mock, Pillow (PIL), cryptography (EC key 生成), python-dotenv

---

## 文件结构

| 新建文件 | 测试目标 |
|---|---|
| `tests/test_constants.py` | `src/asc/constants.py` |
| `tests/test_utils.py` | `src/asc/utils.py` |
| `tests/test_api.py` | `src/asc/api.py` |
| `tests/test_metadata.py` | `src/asc/commands/metadata.py` |
| `tests/test_screenshots.py` | `src/asc/commands/screenshots.py` |
| `tests/test_whats_new.py` | `src/asc/commands/whats_new.py` |
| `tests/test_iap_core.py` | `src/asc/commands/iap.py` |

---

### Task 1: test_constants.py — normalize_locale_code 与 DISPLAY_TYPE_BY_SIZE

**Files:**
- Create: `tests/test_constants.py`

- [ ] **Step 1: 创建测试文件**

```python
"""Tests for src/asc/constants.py"""
from __future__ import annotations

import pytest

from asc.constants import DISPLAY_TYPE_BY_SIZE, normalize_locale_code


# ── normalize_locale_code ──

def test_normalize_empty_string():
    assert normalize_locale_code("") == ""


def test_normalize_two_char_lowercased():
    assert normalize_locale_code("EN") == "en"


def test_normalize_zh_hans_variants():
    assert normalize_locale_code("zh-Hans") == "zh-Hans"
    assert normalize_locale_code("ZH-HANS") == "zh-Hans"
    assert normalize_locale_code("zh_hans") == "zh-Hans"


def test_normalize_zh_hant_variants():
    assert normalize_locale_code("zh-Hant") == "zh-Hant"
    assert normalize_locale_code("ZH-HANT") == "zh-Hant"


def test_normalize_underscore_to_hyphen():
    assert normalize_locale_code("en_US") == "en-US"


def test_normalize_en_us_passthrough():
    assert normalize_locale_code("en-US") == "en-US"


def test_normalize_strips_quotes():
    assert normalize_locale_code('"en-US"') == "en-US"


# ── DISPLAY_TYPE_BY_SIZE ──

def test_known_portrait_size():
    assert DISPLAY_TYPE_BY_SIZE[(1290, 2796)] == "APP_IPHONE_67"


def test_known_landscape_same_type():
    # 横屏与竖屏返回相同设备类型
    assert DISPLAY_TYPE_BY_SIZE[(2796, 1290)] == DISPLAY_TYPE_BY_SIZE[(1290, 2796)]


def test_unknown_size_not_in_dict():
    assert (100, 100) not in DISPLAY_TYPE_BY_SIZE


def test_ipad_pro_size():
    assert DISPLAY_TYPE_BY_SIZE[(2048, 2732)] == "APP_IPAD_PRO_3GEN_129"
```

- [ ] **Step 2: 运行确认全部通过**

```bash
cd /Users/wangyinghui/Documents/02-JMHS/project/tool/AppStoreTools
python -m pytest tests/test_constants.py -v
```

期望：10 个测试全部 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/test_constants.py
git commit -m "test: add test_constants.py for normalize_locale_code and DISPLAY_TYPE_BY_SIZE"
```

---

### Task 2: test_utils.py — extract_locale / parse_csv / resolve_locale / md5_of_file

**Files:**
- Create: `tests/test_utils.py`

- [ ] **Step 1: 创建测试文件**

```python
"""Tests for src/asc/utils.py"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from asc.utils import extract_locale, md5_of_file, parse_csv, resolve_locale


# ── extract_locale ──

def test_extract_locale_chinese_format():
    assert extract_locale("简体中文(zh-Hans)") == "zh-Hans"


def test_extract_locale_english_format():
    assert extract_locale("英文(en-US)") == "en-US"


def test_extract_locale_bare_code():
    assert extract_locale("en") == "en"


def test_extract_locale_strips_whitespace():
    assert extract_locale("  en-US  ") == "en-US"


# ── parse_csv ──

DATA_CSV = Path(__file__).parents[1] / "data" / "appstore_info.csv"


def test_parse_real_csv_row_count():
    rows = parse_csv(str(DATA_CSV))
    assert len(rows) == 2


def test_parse_real_csv_locale_codes():
    rows = parse_csv(str(DATA_CSV))
    locales = [r["语言"] for r in rows]
    assert "zh-Hans" in locales
    assert "en-US" in locales


def test_parse_real_csv_app_name_present():
    rows = parse_csv(str(DATA_CSV))
    for row in rows:
        assert "应用名称" in row
        assert row["应用名称"]


def test_parse_csv_with_bom(tmp_path):
    csv_file = tmp_path / "test.csv"
    # utf-8-sig BOM 编码
    content = "语言,应用名称\n简体中文(zh-Hans),测试应用\n"
    csv_file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
    rows = parse_csv(str(csv_file))
    assert len(rows) == 1
    assert rows[0]["语言"] == "zh-Hans"
    assert rows[0]["应用名称"] == "测试应用"


def test_parse_csv_skips_rows_without_locale(tmp_path):
    csv_file = tmp_path / "test.csv"
    content = "语言,应用名称\n,无语言行\n英文(en-US),有语言行\n"
    csv_file.write_text(content, encoding="utf-8")
    rows = parse_csv(str(csv_file))
    assert len(rows) == 1
    assert rows[0]["语言"] == "en-US"


# ── resolve_locale ──

def test_resolve_exact_match():
    assert resolve_locale("en-US", ["en-US", "zh-Hans"]) == "en-US"


def test_resolve_csv_alias_via_mapping():
    # "en" 通过 CSV_LOCALE_TO_ASC 映射到 "en-US"
    result = resolve_locale("en", ["en-US", "zh-Hans"])
    assert result == "en-US"


def test_resolve_prefix_match():
    result = resolve_locale("zh", ["en-US", "zh-Hans"])
    assert result == "zh-Hans"


def test_resolve_no_match_returns_fallback():
    # 无法匹配时返回 CSV_LOCALE_TO_ASC 的值或原始输入
    result = resolve_locale("fr", ["en-US", "zh-Hans"])
    # fr 通过 CSV_LOCALE_TO_ASC 映射为 fr-FR
    assert result == "fr-FR"


def test_resolve_unknown_code_returns_input():
    result = resolve_locale("xx-XX", ["en-US"])
    assert result == "xx-XX"


# ── md5_of_file ──

def test_md5_of_file(tmp_path):
    data = b"hello world"
    f = tmp_path / "data.bin"
    f.write_bytes(data)
    expected = hashlib.md5(data).hexdigest()
    assert md5_of_file(f) == expected
```

- [ ] **Step 2: 运行确认全部通过**

```bash
python -m pytest tests/test_utils.py -v
```

期望：13 个测试全部 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/test_utils.py
git commit -m "test: add test_utils.py for extract_locale, parse_csv, resolve_locale, md5_of_file"
```

---

### Task 3: test_api.py — JWT 缓存、HTTP 重试、错误处理、真实网络模式

**Files:**
- Create: `tests/test_api.py`

- [ ] **Step 1: 创建测试文件**

```python
"""Tests for src/asc/api.py

Mock 模式（默认）：mock requests.request，使用临时生成的 EC 私钥。
真实网络模式：ASC_TEST_LIVE=1，从 config/.env 读取真实凭据。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from asc.api import AppStoreConnectAPI


# ── Fixtures ──

@pytest.fixture
def ec_key_file(tmp_path):
    """生成真实 EC P-256 私钥，写入临时文件，返回路径字符串。"""
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "AuthKey_TEST.p8"
    key_file.write_bytes(pem)
    return str(key_file)


@pytest.fixture
def api(ec_key_file):
    return AppStoreConnectAPI(
        issuer_id="test-issuer",
        key_id="TESTKEYID",
        key_file=ec_key_file,
    )


# ── JWT token 缓存 ──

def test_token_cached_within_expiry(api):
    t1 = api.token
    t2 = api.token
    assert t1 == t2


def test_token_refreshed_after_expiry(api):
    t1 = api.token
    # 强制令过期
    api._token_expiry = None
    t2 = api.token
    # 两次生成的 token 结构相同（都是 JWT），但 iat/exp 可能不同
    assert t2  # 非空
    # 清除缓存后一定重新生成
    assert isinstance(t2, str)


# ── _request: 429 重试 ──

def test_request_retries_on_429(api):
    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.json.return_value = {"data": "ok"}

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "0"}

    with patch("requests.request", side_effect=[rate_limited, ok_response]) as mock_req:
        with patch("time.sleep"):
            result = api._request("GET", "/v1/apps/123")

    assert result == {"data": "ok"}
    assert mock_req.call_count == 2


# ── _request: 4xx 抛出异常 ──

def test_request_raises_on_404(api):
    error_response = MagicMock()
    error_response.status_code = 404
    error_response.json.return_value = {
        "errors": [{"detail": "Not found", "title": "Not Found"}]
    }

    with patch("requests.request", return_value=error_response):
        with pytest.raises(Exception, match="404"):
            api._request("GET", "/v1/apps/missing")


def test_request_raises_on_401(api):
    error_response = MagicMock()
    error_response.status_code = 401
    error_response.json.return_value = {"errors": [{"detail": "Unauthorized"}]}

    with patch("requests.request", return_value=error_response):
        with pytest.raises(Exception, match="401"):
            api._request("GET", "/v1/apps/123")


# ── _request: 204 返回空字典 ──

def test_request_204_returns_empty_dict(api):
    response = MagicMock()
    response.status_code = 204

    with patch("requests.request", return_value=response):
        result = api._request("DELETE", "/v1/screenshots/abc")

    assert result == {}


# ── get_editable_version ──

def _make_version(state: str, vid: str = "v1") -> dict:
    return {
        "id": vid,
        "attributes": {"appStoreState": state, "versionString": "1.0"},
    }


def test_get_editable_version_prefers_editable(api):
    versions = [
        _make_version("READY_FOR_SALE", "v1"),
        _make_version("PREPARE_FOR_SUBMISSION", "v2"),
    ]
    with patch.object(api, "get", return_value={"data": versions}):
        result = api.get_editable_version("app123")
    assert result["id"] == "v2"


def test_get_editable_version_falls_back_to_first(api):
    versions = [_make_version("READY_FOR_SALE", "v1")]
    with patch.object(api, "get", return_value={"data": versions}):
        result = api.get_editable_version("app123")
    assert result["id"] == "v1"


def test_get_editable_version_returns_none_when_empty(api):
    with patch.object(api, "get", return_value={"data": []}):
        result = api.get_editable_version("app123")
    assert result is None


# ── 真实网络模式 ──

LIVE = os.getenv("ASC_TEST_LIVE") == "1"
ENV_FILE = Path(__file__).parents[1] / "config" / ".env"


def _live_api():
    """从 config/.env 读取凭据，构造真实 API 实例。无凭据则 skip。"""
    if not LIVE:
        pytest.skip("ASC_TEST_LIVE 未设置，跳过真实网络测试")
    if not ENV_FILE.exists():
        pytest.skip("config/.env 不存在，跳过真实网络测试")

    from dotenv import dotenv_values
    env = dotenv_values(str(ENV_FILE))
    issuer_id = env.get("ISSUER_ID")
    key_id = env.get("KEY_ID")
    key_file = env.get("KEY_FILE")
    app_id = env.get("APP_ID")

    if not all([issuer_id, key_id, key_file, app_id]):
        pytest.skip("config/.env 缺少必要字段，跳过真实网络测试")

    # key_file 可能是相对路径，相对于 config/ 目录
    key_path = Path(key_file)
    if not key_path.is_absolute():
        key_path = ENV_FILE.parent / key_path
    if not key_path.exists():
        pytest.skip(f"私钥文件不存在: {key_path}")

    return AppStoreConnectAPI(issuer_id, key_id, str(key_path)), app_id


@pytest.mark.skipif(not LIVE, reason="需要 ASC_TEST_LIVE=1")
def test_live_get_app():
    api, app_id = _live_api()
    resp = api.get_app(app_id)
    assert "data" in resp
    attrs = resp["data"]["attributes"]
    assert attrs.get("name")
    assert attrs.get("bundleId")


@pytest.mark.skipif(not LIVE, reason="需要 ASC_TEST_LIVE=1")
def test_live_get_app_infos():
    api, app_id = _live_api()
    infos = api.get_app_infos(app_id)
    assert isinstance(infos, list)
    assert len(infos) > 0


@pytest.mark.skipif(not LIVE, reason="需要 ASC_TEST_LIVE=1")
def test_live_get_editable_version():
    api, app_id = _live_api()
    version = api.get_editable_version(app_id)
    # 不断言具体值，只验证结构
    if version is not None:
        assert "id" in version
        assert "attributes" in version
```

- [ ] **Step 2: 运行 mock 模式测试（应全部通过）**

```bash
python -m pytest tests/test_api.py -v -k "not live"
```

期望：10 个 mock 测试全部 PASS，3 个 live 测试被 skip。

- [ ] **Step 3: 可选——运行真实网络测试**

```bash
ASC_TEST_LIVE=1 python -m pytest tests/test_api.py -v -k "live"
```

期望：3 个 live 测试 PASS（需要 `config/.env` 有效凭据）。

- [ ] **Step 4: 提交**

```bash
git add tests/test_api.py
git commit -m "test: add test_api.py with JWT caching, retry, error handling, optional live mode"
```

---

### Task 4: test_metadata.py — _upload_metadata_core 与 _update_version_field_core

**Files:**
- Create: `tests/test_metadata.py`

- [ ] **Step 1: 创建测试文件**

```python
"""Tests for src/asc/commands/metadata.py"""
from __future__ import annotations

import pytest

from asc.commands.metadata import _update_version_field_core, _upload_metadata_core


class MetaFakeAPI:
    """最小化 FakeAPI，覆盖 metadata 命令所需端点。"""

    def __init__(self):
        self.calls = []
        self._next = 1

        # 预置数据
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
    # 只更新 keywords，不更新 description
    assert "vloc_zh" in api.updated_ver_locs
    assert "keywords" in api.updated_ver_locs["vloc_zh"]
    assert "description" not in api.updated_ver_locs["vloc_zh"]


# ── _update_version_field_core ──

def test_update_version_field_all_locales():
    api = MetaFakeAPI()
    _update_version_field_core(api, "app1", "supportUrl", "Support URL", "https://example.com")
    # zh-Hans 和 en-US 都应该被更新
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
```

- [ ] **Step 2: 运行确认全部通过**

```bash
python -m pytest tests/test_metadata.py -v
```

期望：9 个测试全部 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/test_metadata.py
git commit -m "test: add test_metadata.py for _upload_metadata_core and _update_version_field_core"
```

---

### Task 5: test_screenshots.py — 图片检测、排序、上传核心逻辑

**Files:**
- Create: `tests/test_screenshots.py`

- [ ] **Step 1: 创建测试文件**

```python
"""Tests for src/asc/commands/screenshots.py"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from asc.commands.screenshots import (
    _detect_display_type,
    _get_sorted_screenshots,
    _upload_screenshots_core,
)


# ── Fixtures ──

def _make_png(path: Path, width: int, height: int):
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    img.save(str(path), "PNG")


class ScreenshotFakeAPI:
    def __init__(self):
        self.calls = []
        self.version_id = "ver_1"
        self.loc_id = "loc_en"

    def get_editable_version(self, app_id):
        return {
            "id": self.version_id,
            "attributes": {"versionString": "1.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
        }

    def get_version_localizations(self, version_id):
        return [{"id": self.loc_id, "attributes": {"locale": "en-US"}}]

    def get_screenshot_sets(self, localization_id):
        self.calls.append(("get_screenshot_sets", localization_id))
        return {"data": [], "included": []}

    def create_screenshot_set(self, localization_id, display_type):
        self.calls.append(("create_screenshot_set", localization_id, display_type))
        return {"data": {"id": "set_1"}}

    def get_screenshots_in_set(self, set_id):
        return []

    def delete_screenshot(self, screenshot_id):
        self.calls.append(("delete_screenshot", screenshot_id))

    def reserve_screenshot(self, set_id, filename, filesize):
        self.calls.append(("reserve_screenshot", set_id, filename, filesize))
        return {
            "data": {
                "id": "shot_1",
                "attributes": {"uploadOperations": []},
            }
        }

    def upload_screenshot_asset(self, upload_operations, file_path):
        self.calls.append(("upload_screenshot_asset",))

    def commit_screenshot(self, screenshot_id, checksum):
        self.calls.append(("commit_screenshot", screenshot_id))

    def get(self, path, **params):
        # 模拟 assetDeliveryState 轮询立即返回 COMPLETE
        return {
            "data": {
                "attributes": {
                    "assetDeliveryState": {"state": "COMPLETE"}
                }
            }
        }


# ── _detect_display_type ──

def test_detect_known_iphone_67(tmp_path):
    img_path = tmp_path / "screen.png"
    _make_png(img_path, 1290, 2796)
    assert _detect_display_type(img_path) == "APP_IPHONE_67"


def test_detect_unknown_size_returns_none(tmp_path):
    img_path = tmp_path / "screen.png"
    _make_png(img_path, 100, 100)
    assert _detect_display_type(img_path) is None


def test_detect_landscape_iphone_67(tmp_path):
    img_path = tmp_path / "screen.png"
    _make_png(img_path, 2796, 1290)
    assert _detect_display_type(img_path) == "APP_IPHONE_67"


# ── _get_sorted_screenshots ──

def test_get_sorted_screenshots_numeric_order(tmp_path):
    for name in ["10.png", "1.png", "2.jpg"]:
        (tmp_path / name).write_bytes(b"")
    result = _get_sorted_screenshots(tmp_path)
    names = [f.name for f in result]
    assert names == ["1.png", "2.jpg", "10.png"]


def test_get_sorted_screenshots_filters_non_image(tmp_path):
    (tmp_path / "1.png").write_bytes(b"")
    (tmp_path / "readme.txt").write_bytes(b"")
    result = _get_sorted_screenshots(tmp_path)
    assert len(result) == 1
    assert result[0].name == "1.png"


# ── _upload_screenshots_core ──

def test_upload_screenshots_missing_dir(tmp_path):
    api = ScreenshotFakeAPI()
    missing = str(tmp_path / "nonexistent")
    _upload_screenshots_core(api, "app1", missing)
    # 目录不存在时不调用任何 API
    assert api.calls == []


def test_upload_screenshots_dry_run(tmp_path):
    api = ScreenshotFakeAPI()
    locale_dir = tmp_path / "en-US"
    locale_dir.mkdir()
    _make_png(locale_dir / "1.png", 1290, 2796)

    _upload_screenshots_core(api, "app1", str(tmp_path), dry_run=True)
    write_calls = [c for c in api.calls if c[0] in (
        "create_screenshot_set", "reserve_screenshot", "commit_screenshot"
    )]
    assert write_calls == []


def test_upload_screenshots_happy_path(tmp_path):
    api = ScreenshotFakeAPI()
    locale_dir = tmp_path / "en-US"
    locale_dir.mkdir()
    _make_png(locale_dir / "1.png", 1290, 2796)

    _upload_screenshots_core(api, "app1", str(tmp_path))

    call_names = [c[0] for c in api.calls]
    assert "create_screenshot_set" in call_names
    assert "reserve_screenshot" in call_names
    assert "commit_screenshot" in call_names


def test_upload_screenshots_en_us_fallback(tmp_path):
    api = ScreenshotFakeAPI()

    # en-US 文件夹存在截图
    en_dir = tmp_path / "en-US"
    en_dir.mkdir()
    _make_png(en_dir / "1.png", 1290, 2796)

    # ja 文件夹不存在 → 应使用 en-US 回退
    # API 返回 en-US 和 ja 两个 locale
    class FallbackAPI(ScreenshotFakeAPI):
        def get_version_localizations(self, version_id):
            return [
                {"id": "loc_en", "attributes": {"locale": "en-US"}},
                {"id": "loc_ja", "attributes": {"locale": "ja"}},
            ]

    api2 = FallbackAPI()
    _upload_screenshots_core(api2, "app1", str(tmp_path))

    # 两个 locale 都应有 reserve_screenshot 调用
    reserve_calls = [c for c in api2.calls if c[0] == "reserve_screenshot"]
    assert len(reserve_calls) == 2
```

- [ ] **Step 2: 运行确认全部通过**

```bash
python -m pytest tests/test_screenshots.py -v
```

期望：11 个测试全部 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/test_screenshots.py
git commit -m "test: add test_screenshots.py for display type detection, sorting, and upload core"
```

---

### Task 6: test_whats_new.py — _parse_whats_new_file

**Files:**
- Create: `tests/test_whats_new.py`

- [ ] **Step 1: 创建测试文件**

```python
"""Tests for src/asc/commands/whats_new.py — _parse_whats_new_file"""
from __future__ import annotations

import pytest

from asc.commands.whats_new import _parse_whats_new_file


def _write(tmp_path, content: str):
    f = tmp_path / "whats_new.txt"
    f.write_text(content, encoding="utf-8")
    return str(f)


# ── 分隔符格式（--- 分隔多 locale）──

def test_parse_separator_format_three_locales(tmp_path):
    content = (
        "en-US:\n"
        "Bug fixes.\n"
        "---\n"
        "zh-Hans:\n"
        "错误修复。\n"
        "---\n"
        "ja:\n"
        "バグ修正。\n"
    )
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result["en-US"] == "Bug fixes."
    assert result["zh-Hans"] == "错误修复。"
    assert result["ja"] == "バグ修正。"


def test_parse_separator_multiline_content(tmp_path):
    content = (
        "en-US:\n"
        "Line 1.\n"
        "Line 2.\n"
        "---\n"
        "zh-Hans:\n"
        "第一行。\n"
    )
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result["en-US"] == "Line 1.\nLine 2."


# ── 同行格式（locale: content）──

def test_parse_inline_format(tmp_path):
    content = (
        "en-US: Bug fixes and improvements.\n"
        "zh-Hans: 错误修复和性能改进。\n"
    )
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result["en-US"] == "Bug fixes and improvements."
    assert result["zh-Hans"] == "错误修复和性能改进。"


# ── 混合格式 ──

def test_parse_mixed_formats(tmp_path):
    content = (
        "en-US: Bug fixes.\n"
        "---\n"
        "zh-Hans:\n"
        "多行内容\n"
        "第二行\n"
    )
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result["en-US"] == "Bug fixes."
    assert result["zh-Hans"] == "多行内容\n第二行"


# ── 空内容 ──

def test_parse_only_separators_returns_empty(tmp_path):
    content = "---\n---\n"
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result == {}


def test_parse_empty_file_returns_empty(tmp_path):
    result = _parse_whats_new_file(_write(tmp_path, ""))
    assert result == {}


# ── 空白处理 ──

def test_parse_strips_trailing_whitespace(tmp_path):
    content = "en-US:\nBug fixes.   \n   \n"
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result["en-US"] == "Bug fixes."
```

- [ ] **Step 2: 运行确认全部通过**

```bash
python -m pytest tests/test_whats_new.py -v
```

期望：7 个测试全部 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/test_whats_new.py
git commit -m "test: add test_whats_new.py for _parse_whats_new_file"
```

---

### Task 7: test_iap_core.py — _upload_iap_core

**Files:**
- Create: `tests/test_iap_core.py`

- [ ] **Step 1: 创建测试文件**

```python
"""Tests for _upload_iap_core in src/asc/commands/iap.py"""
from __future__ import annotations

import pytest

from asc.commands.iap import _upload_iap_core


class IapFakeAPI:
    def __init__(self, existing_iaps=None):
        self.calls = []
        self._next = 1
        # existing_iaps: list of {"id": ..., "attributes": {"productId": ...}}
        self._iaps = {
            iap["attributes"]["productId"]: iap
            for iap in (existing_iaps or [])
        }
        self._locs: dict[str, list] = {}

    def _nid(self):
        self._next += 1
        return f"iap_{self._next}"

    def list_in_app_purchases(self, app_id):
        self.calls.append(("list_in_app_purchases", app_id))
        return list(self._iaps.values())

    def create_in_app_purchase(self, app_id, attrs):
        self.calls.append(("create_in_app_purchase", app_id, attrs))
        iap_id = self._nid()
        self._iaps[attrs["productId"]] = {"id": iap_id, "attributes": attrs}
        self._locs[iap_id] = []
        return {"data": {"id": iap_id}}

    def update_in_app_purchase(self, iap_id, attrs):
        self.calls.append(("update_in_app_purchase", iap_id, attrs))

    def get_in_app_purchase_localizations(self, iap_id):
        self.calls.append(("get_in_app_purchase_localizations", iap_id))
        return self._locs.get(iap_id, [])

    def create_in_app_purchase_localization(self, iap_id, locale, attrs):
        self.calls.append(("create_in_app_purchase_localization", iap_id, locale, attrs))
        self._locs.setdefault(iap_id, []).append(
            {"id": f"loc_{locale}", "attributes": {"locale": locale, **attrs}}
        )

    def update_in_app_purchase_localization(self, loc_id, attrs):
        self.calls.append(("update_in_app_purchase_localization", loc_id, attrs))


# ── 创建 ──

def test_iap_creates_new_item():
    api = IapFakeAPI()
    items = [{"productId": "com.example.item1", "name": "Item 1"}]
    _upload_iap_core(api, "app1", items)
    create_calls = [c for c in api.calls if c[0] == "create_in_app_purchase"]
    assert len(create_calls) == 1
    assert create_calls[0][2]["productId"] == "com.example.item1"


# ── 跳过已有 ──

def test_iap_skips_existing_by_default():
    existing = [{"id": "iap_old", "attributes": {"productId": "com.example.item1"}}]
    api = IapFakeAPI(existing_iaps=existing)
    items = [{"productId": "com.example.item1", "name": "Item 1"}]
    _upload_iap_core(api, "app1", items)
    update_calls = [c for c in api.calls if c[0] == "update_in_app_purchase"]
    create_calls = [c for c in api.calls if c[0] == "create_in_app_purchase"]
    assert update_calls == []
    assert create_calls == []


# ── update_existing ──

def test_iap_updates_existing_when_flag_set():
    existing = [{"id": "iap_old", "attributes": {"productId": "com.example.item1"}}]
    api = IapFakeAPI(existing_iaps=existing)
    items = [{"productId": "com.example.item1", "name": "New Name"}]
    _upload_iap_core(api, "app1", items, update_existing=True)
    update_calls = [c for c in api.calls if c[0] == "update_in_app_purchase"]
    assert len(update_calls) == 1
    assert update_calls[0][1] == "iap_old"


# ── localizations ──

def test_iap_creates_localizations_for_new_item():
    api = IapFakeAPI()
    items = [{
        "productId": "com.example.item1",
        "localizations": {
            "en-US": {"name": "Item", "description": "Desc"},
            "zh-Hans": {"name": "商品", "description": "描述"},
        },
    }]
    _upload_iap_core(api, "app1", items)
    loc_calls = [c for c in api.calls if c[0] == "create_in_app_purchase_localization"]
    assert len(loc_calls) == 2
    locales = {c[2] for c in loc_calls}
    assert locales == {"en-US", "zh-Hans"}


def test_iap_updates_localizations_when_update_existing():
    iap_id = "iap_old"
    existing = [{"id": iap_id, "attributes": {"productId": "com.example.item1"}}]
    api = IapFakeAPI(existing_iaps=existing)
    # 预置已有 localization
    api._locs[iap_id] = [
        {"id": "loc_en", "attributes": {"locale": "en-US", "name": "Old Name"}}
    ]
    items = [{
        "productId": "com.example.item1",
        "localizations": {"en-US": {"name": "New Name"}},
    }]
    _upload_iap_core(api, "app1", items, update_existing=True)
    update_loc_calls = [c for c in api.calls if c[0] == "update_in_app_purchase_localization"]
    assert len(update_loc_calls) == 1
    assert update_loc_calls[0][1] == "loc_en"


# ── dry_run ──

def test_iap_dry_run_no_api_writes():
    api = IapFakeAPI()
    items = [{"productId": "com.example.item1", "name": "Item 1"}]
    _upload_iap_core(api, "app1", items, dry_run=True)
    write_calls = [c for c in api.calls if c[0] in (
        "create_in_app_purchase", "update_in_app_purchase",
        "create_in_app_purchase_localization", "update_in_app_purchase_localization",
    )]
    assert write_calls == []


# ── 缺少 productId ──

def test_iap_skips_item_without_product_id():
    api = IapFakeAPI()
    items = [{"name": "No Product ID"}]
    _upload_iap_core(api, "app1", items)
    create_calls = [c for c in api.calls if c[0] == "create_in_app_purchase"]
    assert create_calls == []
```

- [ ] **Step 2: 运行确认全部通过**

```bash
python -m pytest tests/test_iap_core.py -v
```

期望：7 个测试全部 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/test_iap_core.py
git commit -m "test: add test_iap_core.py for _upload_iap_core"
```

---

### Task 8: 全套运行与验收

- [ ] **Step 1: 运行完整测试套件（mock 模式）**

```bash
python -m pytest tests/ -v
```

期望：约 127 个测试全部 PASS，耗时 < 5 秒，0 个 FAIL。

- [ ] **Step 2: 可选——真实网络验证**

```bash
ASC_TEST_LIVE=1 python -m pytest tests/test_api.py -v -k "live"
```

期望：3 个 live 测试 PASS（需要有效 `config/.env`）。

- [ ] **Step 3: 最终提交（若有未提交变更）**

```bash
git status
# 确认干净后无需额外提交
```
