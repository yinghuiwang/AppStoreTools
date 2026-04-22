# asc CLI Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the current script-based tool into a pip-installable CLI package named `asc` with multi-app configuration support and PyPI auto-publishing.

**Architecture:** Standard Python package with src-layout, typer for CLI, TOML for config (global ~/.config/asc/ + local .asc/), and GitHub Actions for PyPI releases.

**Tech Stack:** Python 3.9+, typer, hatchling, PyJWT, requests, Pillow, python-dotenv

---

## File Structure Overview

```
src/asc/
  __init__.py           # __version__ = "0.1.0"
  __main__.py           # python -m asc entry
  cli.py                # typer app, command registration
  api.py                # AppStoreConnectAPI class
  config.py             # Config loading (global/local/env priority)
  constants.py          # Display types, locale mappings
  commands/
    __init__.py
    metadata.py         # upload, metadata, keywords, URL commands
    screenshots.py      # screenshots command
    iap.py              # iap command
    whats_new.py        # whats-new command
    app_config.py       # app add/list/remove commands

pyproject.toml          # Package metadata, dependencies, entry point
.github/workflows/
  publish.yml           # PyPI auto-publish on tag
```

---

### Task 1: Create Package Structure

**Files:**
- Create: `src/asc/__init__.py`
- Create: `src/asc/__main__.py`
- Create: `src/asc/commands/__init__.py`

- [ ] **Step 1: Create src/asc directory structure**

```bash
mkdir -p src/asc/commands
```

- [ ] **Step 2: Write src/asc/__init__.py**

```python
"""asc - App Store Connect CLI tool"""

__version__ = "0.1.0"
```

- [ ] **Step 3: Write src/asc/__main__.py**

```python
"""Entry point for python -m asc"""

from asc.cli import app

if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Write src/asc/commands/__init__.py**

```python
"""Command modules for asc CLI"""
```

- [ ] **Step 5: Verify structure**

Run: `find src/asc -type f`
Expected: All four files listed

- [ ] **Step 6: Commit**

```bash
git add src/
git commit -m "$(cat <<'EOF'
feat: create asc package structure

Initialize src-layout package structure for asc CLI.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Migrate Constants

**Files:**
- Create: `src/asc/constants.py`
- Read: `upload_to_appstore.py:48-103`

- [ ] **Step 1: Extract constants from upload_to_appstore.py**

Read lines 48-103 to get DISPLAY_TYPE_BY_SIZE, SCREENSHOT_FOLDER_TO_LOCALE, CSV_LOCALE_TO_ASC

- [ ] **Step 2: Write src/asc/constants.py**

```python
"""Constants for App Store Connect API"""

BASE_URL = "https://api.appstoreconnect.apple.com"

DISPLAY_TYPE_BY_SIZE = {
    (1320, 2868): "APP_IPHONE_67",
    (2868, 1320): "APP_IPHONE_67",
    (1290, 2796): "APP_IPHONE_67",
    (2796, 1290): "APP_IPHONE_67",
    (1284, 2778): "APP_IPHONE_65",
    (2778, 1284): "APP_IPHONE_65",
    (1242, 2688): "APP_IPHONE_65",
    (2688, 1242): "APP_IPHONE_65",
    (1179, 2556): "APP_IPHONE_61",
    (2556, 1179): "APP_IPHONE_61",
    (1170, 2532): "APP_IPHONE_61",
    (2532, 1170): "APP_IPHONE_61",
    (1125, 2436): "APP_IPHONE_58",
    (2436, 1125): "APP_IPHONE_58",
    (1242, 2208): "APP_IPHONE_55",
    (2208, 1242): "APP_IPHONE_55",
    (750, 1334): "APP_IPHONE_47",
    (1334, 750): "APP_IPHONE_47",
    (2048, 2732): "APP_IPAD_PRO_3GEN_129",
    (2732, 2048): "APP_IPAD_PRO_3GEN_129",
    (1668, 2388): "APP_IPAD_PRO_3GEN_11",
    (2388, 1668): "APP_IPAD_PRO_3GEN_11",
    (2064, 2752): "APP_IPAD_PRO_129",
    (2752, 2064): "APP_IPAD_PRO_129",
}

SCREENSHOT_FOLDER_TO_LOCALE = {
    "cn": "zh-Hans",
    "zh": "zh-Hans",
    "zh-hans": "zh-Hans",
    "en": "en-US",
    "ja": "ja",
    "ko": "ko",
    "fr": "fr-FR",
    "de": "de-DE",
    "es": "es-ES",
    "pt": "pt-BR",
}

CSV_LOCALE_TO_ASC = {
    "en": "en-US",
    "ar": "ar-SA",
    "zh-Hans": "zh-Hans",
    "zh-Hant": "zh-Hant",
    "ja": "ja",
    "ko": "ko",
    "fr": "fr-FR",
    "de": "de-DE",
    "es": "es-ES",
    "pt-BR": "pt-BR",
    "pt": "pt-BR",
}


def normalize_locale_code(locale_code: str) -> str:
    """标准化 locale，兼容 CSV 中常见简写/大小写差异"""
    code = (locale_code or "").strip().strip('"').strip("'")
    if not code:
        return code
    code = code.replace("_", "-")
    lowered = code.lower()
    if lowered == "zh-hans":
        return "zh-Hans"
    if lowered == "zh-hant":
        return "zh-Hant"
    if len(code) == 2:
        return lowered
    if "-" in code:
        lang, region = code.split("-", 1)
        if len(lang) == 2 and len(region) == 2:
            return f"{lang.lower()}-{region.upper()}"
    return code
```

- [ ] **Step 3: Verify import**

Run: `python -c "from asc.constants import DISPLAY_TYPE_BY_SIZE; print(len(DISPLAY_TYPE_BY_SIZE))"`
Expected: 24

- [ ] **Step 4: Commit**

```bash
git add src/asc/constants.py
git commit -m "$(cat <<'EOF'
feat: add constants module

Migrate display types, locale mappings, and normalization function.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Migrate API Client

**Files:**
- Create: `src/asc/api.py`
- Read: `upload_to_appstore.py:126-414`

- [ ] **Step 1: Write src/asc/api.py (part 1: imports and class init)**

```python
"""App Store Connect API client"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import requests

from asc.constants import BASE_URL


class AppStoreConnectAPI:
    """App Store Connect API 客户端"""

    def __init__(self, issuer_id: str, key_id: str, key_file: str):
        self.issuer_id = issuer_id
        self.key_id = key_id
        with open(key_file, "r") as f:
            self.private_key = f.read()
        self._token = None
        self._token_expiry = None

    @property
    def token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._token and self._token_expiry and now < self._token_expiry:
            return self._token

        expiry = now + timedelta(minutes=15)
        payload = {
            "iss": self.issuer_id,
            "iat": int(now.timestamp()),
            "exp": int(expiry.timestamp()),
            "aud": "appstoreconnect-v1",
        }
        self._token = jwt.encode(
            payload, self.private_key, algorithm="ES256", headers={"kid": self.key_id}
        )
        self._token_expiry = expiry - timedelta(minutes=1)
        return self._token

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{BASE_URL}{path}" if path.startswith("/") else path
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        for attempt in range(3):
            resp = requests.request(method, url, headers=headers, **kwargs)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                print(f"  ⏳ 速率限制，等待 {retry_after} 秒...")
                time.sleep(retry_after)
                continue

            if resp.status_code >= 400:
                error_detail = ""
                try:
                    err = resp.json()
                    errors = err.get("errors", [])
                    error_detail = "; ".join(
                        e.get("detail", e.get("title", "")) for e in errors
                    )
                except Exception:
                    error_detail = resp.text[:500]
                raise Exception(
                    f"API 错误 [{resp.status_code}] {method} {url}: {error_detail}"
                )

            if resp.status_code == 204:
                return {}
            return resp.json()

        raise Exception(f"请求失败，已达最大重试次数: {method} {path}")

    def get(self, path: str, **params) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, data: dict) -> dict:
        return self._request("POST", path, json=data)

    def patch(self, path: str, data: dict) -> dict:
        return self._request("PATCH", path, json=data)

    def delete(self, path: str) -> dict:
        return self._request("DELETE", path)
```

- [ ] **Step 2: Add app info methods to api.py**

```python
    # ── App 信息 ──

    def get_app(self, app_id: str) -> dict:
        return self.get(f"/v1/apps/{app_id}")

    def get_app_infos(self, app_id: str) -> list:
        resp = self.get(f"/v1/apps/{app_id}/appInfos")
        return resp.get("data", [])

    def get_app_info_localizations(self, app_info_id: str) -> list:
        resp = self.get(f"/v1/appInfos/{app_info_id}/appInfoLocalizations")
        return resp.get("data", [])

    def update_app_info_localization(self, loc_id: str, attributes: dict) -> dict:
        return self.patch(
            f"/v1/appInfoLocalizations/{loc_id}",
            {
                "data": {
                    "type": "appInfoLocalizations",
                    "id": loc_id,
                    "attributes": attributes,
                }
            },
        )

    def create_app_info_localization(
        self, app_info_id: str, locale: str, attributes: dict
    ) -> dict:
        return self.post(
            "/v1/appInfoLocalizations",
            {
                "data": {
                    "type": "appInfoLocalizations",
                    "attributes": {"locale": locale, **attributes},
                    "relationships": {
                        "appInfo": {"data": {"type": "appInfos", "id": app_info_id}}
                    },
                }
            },
        )
```

- [ ] **Step 3: Add version methods to api.py**

```python
    # ── 版本信息 ──

    def get_editable_version(self, app_id: str, platform: str = "IOS") -> dict | None:
        resp = self.get(
            f"/v1/apps/{app_id}/appStoreVersions", **{"filter[platform]": platform}
        )
        versions = resp.get("data", [])
        editable_states = {
            "PREPARE_FOR_SUBMISSION",
            "DEVELOPER_REJECTED",
            "REJECTED",
            "METADATA_REJECTED",
            "WAITING_FOR_REVIEW",
            "IN_REVIEW",
        }
        for v in versions:
            state = v["attributes"].get("appStoreState") or v["attributes"].get(
                "appVersionState", ""
            )
            if state in editable_states:
                return v
        return versions[0] if versions else None

    def get_version_localizations(self, version_id: str) -> list:
        resp = self.get(
            f"/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations"
        )
        return resp.get("data", [])

    def update_version_localization(self, loc_id: str, attributes: dict) -> dict:
        return self.patch(
            f"/v1/appStoreVersionLocalizations/{loc_id}",
            {
                "data": {
                    "type": "appStoreVersionLocalizations",
                    "id": loc_id,
                    "attributes": attributes,
                }
            },
        )

    def create_version_localization(
        self, version_id: str, locale: str, attributes: dict
    ) -> dict:
        return self.post(
            "/v1/appStoreVersionLocalizations",
            {
                "data": {
                    "type": "appStoreVersionLocalizations",
                    "attributes": {"locale": locale, **attributes},
                    "relationships": {
                        "appStoreVersion": {
                            "data": {"type": "appStoreVersions", "id": version_id}
                        }
                    },
                }
            },
        )
```

- [ ] **Step 4: Add screenshot methods to api.py**

```python
    # ── 截图 ──

    def get_screenshot_sets(self, localization_id: str) -> dict:
        return self.get(
            f"/v1/appStoreVersionLocalizations/{localization_id}/appScreenshotSets",
            **{"include": "appScreenshots"},
        )

    def create_screenshot_set(self, localization_id: str, display_type: str) -> dict:
        return self.post(
            "/v1/appScreenshotSets",
            {
                "data": {
                    "type": "appScreenshotSets",
                    "attributes": {"screenshotDisplayType": display_type},
                    "relationships": {
                        "appStoreVersionLocalization": {
                            "data": {
                                "type": "appStoreVersionLocalizations",
                                "id": localization_id,
                            }
                        }
                    },
                }
            },
        )

    def get_screenshots_in_set(self, screenshot_set_id: str) -> list:
        resp = self.get(f"/v1/appScreenshotSets/{screenshot_set_id}/appScreenshots")
        return resp.get("data", [])

    def delete_screenshot(self, screenshot_id: str):
        return self.delete(f"/v1/appScreenshots/{screenshot_id}")

    def reserve_screenshot(
        self, screenshot_set_id: str, filename: str, filesize: int
    ) -> dict:
        return self.post(
            "/v1/appScreenshots",
            {
                "data": {
                    "type": "appScreenshots",
                    "attributes": {
                        "fileName": filename,
                        "fileSize": filesize,
                    },
                    "relationships": {
                        "appScreenshotSet": {
                            "data": {"type": "appScreenshotSets", "id": screenshot_set_id}
                        }
                    },
                }
            },
        )

    def upload_screenshot_asset(self, upload_operations: list, file_path: Path):
        file_data = file_path.read_bytes()
        for op in upload_operations:
            url = op["url"]
            offset = op["offset"]
            length = op["length"]
            req_headers = {h["name"]: h["value"] for h in op["requestHeaders"]}
            chunk = file_data[offset : offset + length]
            resp = requests.put(url, headers=req_headers, data=chunk)
            if resp.status_code not in (200, 201):
                raise Exception(f"截图上传失败 [{resp.status_code}]: {resp.text[:200]}")

    def commit_screenshot(self, screenshot_id: str, md5_checksum: str) -> dict:
        return self.patch(
            f"/v1/appScreenshots/{screenshot_id}",
            {
                "data": {
                    "type": "appScreenshots",
                    "id": screenshot_id,
                    "attributes": {
                        "uploaded": True,
                        "sourceFileChecksum": md5_checksum,
                    },
                }
            },
        )
```

- [ ] **Step 5: Add IAP methods to api.py**

```python
    # ── IAP ──

    def list_in_app_purchases(self, app_id: str) -> list:
        endpoints = [
            f"/v1/apps/{app_id}/inAppPurchasesV2",
            f"/v2/apps/{app_id}/inAppPurchasesV2",
        ]
        last_error = None
        for endpoint in endpoints:
            try:
                resp = self.get(endpoint, limit=200)
                return resp.get("data", [])
            except Exception as e:
                last_error = e
                continue
        raise Exception(f"获取 IAP 列表失败: {last_error}")

    def create_in_app_purchase(self, app_id: str, attributes: dict) -> dict:
        return self.post(
            "/v2/inAppPurchases",
            {
                "data": {
                    "type": "inAppPurchases",
                    "attributes": attributes,
                    "relationships": {
                        "app": {"data": {"type": "apps", "id": app_id}}
                    },
                }
            },
        )

    def update_in_app_purchase(self, iap_id: str, attributes: dict) -> dict:
        return self.patch(
            f"/v2/inAppPurchases/{iap_id}",
            {
                "data": {
                    "type": "inAppPurchases",
                    "id": iap_id,
                    "attributes": attributes,
                }
            },
        )

    def get_in_app_purchase_localizations(self, iap_id: str) -> list:
        resp = self.get(f"/v2/inAppPurchases/{iap_id}/inAppPurchaseLocalizations")
        return resp.get("data", [])

    def create_in_app_purchase_localization(
        self, iap_id: str, locale: str, attributes: dict
    ) -> dict:
        return self.post(
            "/v1/inAppPurchaseLocalizations",
            {
                "data": {
                    "type": "inAppPurchaseLocalizations",
                    "attributes": {"locale": locale, **attributes},
                    "relationships": {
                        "inAppPurchaseV2": {
                            "data": {"type": "inAppPurchases", "id": iap_id}
                        }
                    },
                }
            },
        )

    def update_in_app_purchase_localization(
        self, loc_id: str, attributes: dict
    ) -> dict:
        return self.patch(
            f"/v1/inAppPurchaseLocalizations/{loc_id}",
            {
                "data": {
                    "type": "inAppPurchaseLocalizations",
                    "id": loc_id,
                    "attributes": attributes,
                }
            },
        )
```

- [ ] **Step 6: Verify API module imports**

Run: `python -c "from asc.api import AppStoreConnectAPI; print('OK')"`
Expected: OK

- [ ] **Step 7: Commit**

```bash
git add src/asc/api.py
git commit -m "$(cat <<'EOF'
feat: add API client module

Migrate AppStoreConnectAPI class with JWT auth, retry logic, and all
endpoint methods for app info, versions, screenshots, and IAP.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Create Config System

**Files:**
- Create: `src/asc/config.py`

- [ ] **Step 1: Write config.py with TOML loading**

```python
"""Configuration management for asc CLI"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from dotenv import load_dotenv


class Config:
    """Configuration with priority: CLI args > local .asc/config.toml > global profile > env"""

    def __init__(self, app_name: str | None = None):
        self.app_name = app_name
        self._global_dir = Path.home() / ".config" / "asc"
        self._local_dir = Path.cwd() / ".asc"
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self):
        # Load from environment variables first (lowest priority)
        load_dotenv(Path.cwd() / "config" / ".env")

        # Load global profile
        if self.app_name:
            global_profile = self._global_dir / "profiles" / f"{self.app_name}.toml"
            if global_profile.exists():
                with open(global_profile, "rb") as f:
                    self._data = tomllib.load(f)

        # Load local config (can override default_app)
        local_config = self._local_dir / "config.toml"
        if local_config.exists():
            with open(local_config, "rb") as f:
                local_data = tomllib.load(f)
                if "default_app" in local_data and not self.app_name:
                    self.app_name = local_data["default_app"]
                    # Reload with the default app
                    global_profile = (
                        self._global_dir / "profiles" / f"{self.app_name}.toml"
                    )
                    if global_profile.exists():
                        with open(global_profile, "rb") as f:
                            self._data = tomllib.load(f)

    def get(self, key: str, default: Any = None, section: str | None = None) -> Any:
        """Get config value with fallback to environment variable"""
        # Check TOML data first
        if section and section in self._data:
            value = self._data[section].get(key)
            if value is not None:
                return value
        elif key in self._data:
            return self._data[key]

        # Fallback to environment variable (uppercase)
        env_key = key.upper()
        env_value = os.getenv(env_key)
        if env_value:
            return env_value

        return default

    @property
    def issuer_id(self) -> str | None:
        return self.get("issuer_id", section="credentials")

    @property
    def key_id(self) -> str | None:
        return self.get("key_id", section="credentials")

    @property
    def key_file(self) -> str | None:
        key_file = self.get("key_file", section="credentials")
        if key_file and key_file.startswith("~"):
            return str(Path(key_file).expanduser())
        return key_file

    @property
    def app_id(self) -> str | None:
        return self.get("app_id", section="credentials")

    @property
    def csv_path(self) -> str:
        return self.get("csv", default="data/appstore_info.csv", section="defaults")

    @property
    def screenshots_path(self) -> str:
        return self.get("screenshots", default="data/screenshots", section="defaults")

    def list_apps(self) -> list[str]:
        """List all configured app profiles"""
        profiles_dir = self._global_dir / "profiles"
        if not profiles_dir.exists():
            return []
        return [p.stem for p in profiles_dir.glob("*.toml")]

    def save_app_profile(
        self,
        app_name: str,
        issuer_id: str,
        key_id: str,
        key_file: str,
        app_id: str,
    ):
        """Save a new app profile to global config"""
        profiles_dir = self._global_dir / "profiles"
        profiles_dir.mkdir(parents=True, exist_ok=True)

        profile_path = profiles_dir / f"{app_name}.toml"
        content = f"""[credentials]
issuer_id = "{issuer_id}"
key_id = "{key_id}"
key_file = "{key_file}"
app_id = "{app_id}"

[defaults]
csv = "data/appstore_info.csv"
screenshots = "data/screenshots"
"""
        profile_path.write_text(content)

    def remove_app_profile(self, app_name: str):
        """Remove an app profile from global config"""
        profile_path = self._global_dir / "profiles" / f"{app_name}.toml"
        if profile_path.exists():
            profile_path.unlink()
```

- [ ] **Step 2: Add tomli to dependencies check**

Run: `python -c "import tomli; print('tomli available')" 2>/dev/null || python -c "import tomllib; print('tomllib available')"`
Expected: Either "tomli available" or "tomllib available"

- [ ] **Step 3: Verify config module**

Run: `python -c "from asc.config import Config; c = Config(); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add src/asc/config.py
git commit -m "$(cat <<'EOF'
feat: add configuration system

Support global profiles (~/.config/asc/), local overrides (.asc/),
and environment variable fallback with priority handling.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Create pyproject.toml

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore` updates

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "asc-appstore-tools"
version = "0.1.0"
description = "CLI tool for bulk-uploading App Store Connect metadata"
readme = "README.md"
requires-python = ">=3.9"
license = { text = "MIT" }
authors = [
    { name = "Your Name", email = "your.email@example.com" }
]
keywords = ["app-store", "app-store-connect", "cli", "metadata", "screenshots"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]

dependencies = [
    "typer>=0.12.0",
    "PyJWT>=2.8.0",
    "cryptography>=41.0.0",
    "requests>=2.31.0",
    "Pillow>=10.0.0",
    "python-dotenv>=1.0.0",
    "tomli>=2.0.0; python_version<'3.11'",
]

[project.optional-dependencies]
dev = [
    "build>=1.0.0",
    "twine>=4.0.0",
]

[project.scripts]
asc = "asc.cli:app"

[project.urls]
Homepage = "https://github.com/yourusername/asc-appstore-tools"
Repository = "https://github.com/yourusername/asc-appstore-tools"
Issues = "https://github.com/yourusername/asc-appstore-tools/issues"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatchling.version]
path = "src/asc/__init__.py"

[tool.hatchling.build.targets.wheel]
packages = ["src/asc"]
```

- [ ] **Step 2: Update .gitignore**

```bash
echo "
# asc CLI
.asc/
*.egg-info/
dist/
build/
" >> .gitignore
```

- [ ] **Step 3: Verify pyproject.toml syntax**

Run: `python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('Valid TOML')"`
Expected: Valid TOML

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .gitignore
git commit -m "$(cat <<'EOF'
feat: add pyproject.toml for pip packaging

Configure package metadata, dependencies, and build system with
hatchling for dynamic version reading.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

---

### Task 6: Create CLI Entry Point

**Files:**
- Create: `src/asc/cli.py`

- [ ] **Step 1: Write src/asc/cli.py**

```python
"""Main CLI entry point for asc"""

from __future__ import annotations

from typing import Optional

import typer

from asc import __version__

app = typer.Typer(
    name="asc",
    help="App Store Connect CLI tool",
    no_args_is_help=True,
)
app_cmd = typer.Typer(help="Manage app profiles", no_args_is_help=True)
app.add_typer(app_cmd, name="app")


def version_callback(value: bool):
    if value:
        typer.echo(f"asc version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", callback=version_callback, is_eager=True
    ),
):
    """App Store Connect CLI — upload metadata, screenshots, IAP, and more."""


# Import and register all subcommands
from asc.commands.metadata import (
    cmd_upload,
    cmd_metadata,
    cmd_keywords,
    cmd_support_url,
    cmd_marketing_url,
    cmd_privacy_policy_url,
    cmd_set_support_url,
    cmd_set_marketing_url,
    cmd_set_privacy_policy_url,
    cmd_check,
)
from asc.commands.screenshots import cmd_screenshots
from asc.commands.iap import cmd_iap
from asc.commands.whats_new import cmd_whats_new
from asc.commands.app_config import cmd_app_add, cmd_app_list, cmd_app_remove

app.command("upload")(cmd_upload)
app.command("metadata")(cmd_metadata)
app.command("keywords")(cmd_keywords)
app.command("support-url")(cmd_support_url)
app.command("marketing-url")(cmd_marketing_url)
app.command("privacy-policy-url")(cmd_privacy_policy_url)
app.command("set-support-url")(cmd_set_support_url)
app.command("set-marketing-url")(cmd_set_marketing_url)
app.command("set-privacy-policy-url")(cmd_set_privacy_policy_url)
app.command("screenshots")(cmd_screenshots)
app.command("iap")(cmd_iap)
app.command("whats-new")(cmd_whats_new)
app.command("check")(cmd_check)
app_cmd.command("add")(cmd_app_add)
app_cmd.command("list")(cmd_app_list)
app_cmd.command("remove")(cmd_app_remove)
```

- [ ] **Step 2: Commit skeleton (commands not yet implemented)**

```bash
git add src/asc/cli.py
git commit -m "$(cat <<'EOF'
feat: add CLI entry point with typer

Register all subcommands via typer app; command implementations follow.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Create Helper Utilities

**Files:**
- Create: `src/asc/utils.py`

- [ ] **Step 1: Write src/asc/utils.py**

```python
"""Shared utility functions used across command modules"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

from asc.constants import CSV_LOCALE_TO_ASC, normalize_locale_code


def extract_locale(raw_lang: str) -> str:
    """从 '简体中文(zh-Hans)' 或 '英文(en-US)' 格式中提取 locale 代码"""
    m = re.search(r"\(([^)]+)\)", raw_lang)
    if m:
        return normalize_locale_code(m.group(1))
    return normalize_locale_code(raw_lang.strip())


def parse_csv(csv_path: str) -> list[dict]:
    """解析 CSV 元数据文件，返回每个语言的元数据字典列表"""
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        raw_headers = reader.fieldnames or []
        clean_headers = []
        for h in raw_headers:
            stripped = h.strip().strip('"')
            if stripped:
                clean_headers.append((h, stripped))

        results = []
        for row in reader:
            mapped = {}
            for orig_key, clean_key in clean_headers:
                val = row.get(orig_key)
                if val and val.strip():
                    mapped[clean_key] = val.strip()
            if "语言" not in mapped or not mapped["语言"]:
                continue
            mapped["语言"] = extract_locale(mapped["语言"])
            results.append(mapped)

    return results


def resolve_locale(csv_locale: str, existing_locales: list[str]) -> str | None:
    """将 CSV 中的语言代码映射到 ASC 中实际存在的 locale"""
    csv_locale = normalize_locale_code(csv_locale)

    if csv_locale in existing_locales:
        return csv_locale

    asc_locale = CSV_LOCALE_TO_ASC.get(csv_locale)
    if asc_locale and asc_locale in existing_locales:
        return asc_locale

    for existing in existing_locales:
        if existing.startswith(csv_locale):
            return existing

    return asc_locale or csv_locale


def md5_of_file(file_path: Path) -> str:
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def make_api_from_config(config, app_id_override: str | None = None):
    """Build an AppStoreConnectAPI instance from config, validating required fields"""
    from asc.api import AppStoreConnectAPI

    issuer_id = config.issuer_id
    key_id = config.key_id
    key_file = config.key_file
    app_id = app_id_override or config.app_id

    missing = []
    if not issuer_id:
        missing.append("ISSUER_ID / issuer_id")
    if not key_id:
        missing.append("KEY_ID / key_id")
    if not key_file:
        missing.append("KEY_FILE / key_file")
    if not app_id:
        missing.append("APP_ID / app_id")
    if missing:
        raise typer.BadParameter(
            f"Missing required config: {', '.join(missing)}\n"
            "Run 'asc app add <name>' to configure an app profile."
        )

    return AppStoreConnectAPI(issuer_id, key_id, key_file), app_id
```

- [ ] **Step 2: Fix import in utils.py (typer not imported)**

Add `import typer` at the top of `src/asc/utils.py`:

```python
"""Shared utility functions used across command modules"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

import typer

from asc.constants import CSV_LOCALE_TO_ASC, normalize_locale_code
```

- [ ] **Step 3: Commit**

```bash
git add src/asc/utils.py
git commit -m "$(cat <<'EOF'
feat: add shared utilities module

CSV parsing, locale resolution, MD5 checksum, and API factory.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Create Metadata Commands

**Files:**
- Create: `src/asc/commands/metadata.py`

- [ ] **Step 1: Write src/asc/commands/metadata.py**

```python
"""Metadata upload commands"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from asc.config import Config
from asc.utils import make_api_from_config, parse_csv


def _upload_metadata_core(
    api,
    app_id: str,
    metadata_list: list[dict],
    dry_run: bool = False,
    include_version_fields: set[str] | None = None,
):
    """Core metadata upload logic (migrated from upload_to_appstore.py)"""
    from asc.utils import resolve_locale

    print("\n" + "=" * 60)
    print("📝 上传元数据")
    print("=" * 60)

    app_infos = api.get_app_infos(app_id)
    if not app_infos:
        print("❌ 找不到 App 信息")
        return
    app_info = app_infos[0]
    app_info_id = app_info["id"]
    print(f"  App Info ID: {app_info_id}")

    version = api.get_editable_version(app_id)
    if not version:
        print("❌ 找不到可编辑的 App Store 版本")
        return
    version_id = version["id"]
    version_string = version["attributes"].get("versionString", "?")
    version_state = version["attributes"].get("appStoreState") or version[
        "attributes"
    ].get("appVersionState", "?")
    print(f"  版本: {version_string} (状态: {version_state})")
    print(f"  版本 ID: {version_id}")

    info_locs = api.get_app_info_localizations(app_info_id)
    info_loc_map = {loc["attributes"]["locale"]: loc for loc in info_locs}
    existing_info_locales = list(info_loc_map.keys())
    print(f"  已有 App Info 语言: {existing_info_locales}")

    ver_locs = api.get_version_localizations(version_id)
    ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}
    existing_ver_locales = list(ver_loc_map.keys())
    print(f"  已有版本语言: {existing_ver_locales}")

    for meta in metadata_list:
        csv_locale = meta["语言"]
        info_locale = resolve_locale(csv_locale, existing_info_locales)
        ver_locale = resolve_locale(csv_locale, existing_ver_locales)
        print(f"\n  ── 语言: {csv_locale} → App Info: {info_locale}, 版本: {ver_locale} ──")

        name = meta.get("应用名称", "")
        subtitle = meta.get("副标题", "")
        if (name or subtitle) and include_version_fields is None:
            info_attrs = {}
            if name:
                info_attrs["name"] = name
            if subtitle:
                info_attrs["subtitle"] = subtitle
            print(f"    应用名称: {name}")
            print(f"    副标题: {subtitle}")

            if not dry_run:
                if info_locale in info_loc_map:
                    api.update_app_info_localization(info_loc_map[info_locale]["id"], info_attrs)
                    print("    ✅ 已更新 App Info 本地化")
                else:
                    api.create_app_info_localization(app_info_id, info_locale, info_attrs)
                    print("    ✅ 已创建 App Info 本地化")
                    existing_info_locales.append(info_locale)

        description = meta.get("长描述", "")
        keywords = meta.get("关键词", "") or meta.get("关键子", "")
        support_url = meta.get("技术支持网址", "") or meta.get("技术支持链接", "")
        marketing_url = meta.get("营销网站", "") or meta.get("营销网址", "")
        privacy_policy_url = (
            meta.get("隐私政策网址", "")
            or meta.get("隐私政策链接", "")
            or meta.get("隐私政策URL", "")
        )

        ver_attrs = {}
        if description and (include_version_fields is None or "description" in include_version_fields):
            ver_attrs["description"] = description
        if keywords and (include_version_fields is None or "keywords" in include_version_fields):
            ver_attrs["keywords"] = keywords
        if support_url and (include_version_fields is None or "supportUrl" in include_version_fields):
            ver_attrs["supportUrl"] = support_url
        if marketing_url and (include_version_fields is None or "marketingUrl" in include_version_fields):
            ver_attrs["marketingUrl"] = marketing_url
        if privacy_policy_url and (include_version_fields is None or "privacyPolicyUrl" in include_version_fields):
            ver_attrs["privacyPolicyUrl"] = privacy_policy_url

        if ver_attrs:
            desc_preview = description[:60] + "..." if len(description) > 60 else description
            print(f"    描述: {desc_preview}")
            if keywords:
                print(f"    关键词: {keywords[:60]}{'...' if len(keywords) > 60 else ''}")
            if support_url:
                print(f"    技术支持: {support_url}")
            if marketing_url:
                print(f"    营销网站: {marketing_url}")
            if privacy_policy_url:
                print(f"    隐私政策: {privacy_policy_url}")

            if not dry_run:
                if ver_locale in ver_loc_map:
                    api.update_version_localization(ver_loc_map[ver_locale]["id"], ver_attrs)
                    print("    ✅ 已更新版本本地化")
                else:
                    try:
                        api.create_version_localization(version_id, ver_locale, ver_attrs)
                        print("    ✅ 已创建版本本地化")
                    except Exception as e:
                        if "409" in str(e) or "already exists" in str(e):
                            print("    ⚠️  版本本地化已存在，重新获取后更新...")
                            ver_locs = api.get_version_localizations(version_id)
                            ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}
                            if ver_locale in ver_loc_map:
                                api.update_version_localization(ver_loc_map[ver_locale]["id"], ver_attrs)
                                print("    ✅ 已更新版本本地化")
                            else:
                                print(f"    ❌ 无法处理版本本地化: {e}")
                        else:
                            raise

    print("\n✅ 元数据上传完成")


def _update_version_field_core(
    api,
    app_id: str,
    field_key: str,
    field_label: str,
    field_value: str,
    locales: list[str] | None = None,
    dry_run: bool = False,
):
    """Core implementation for set-*-url commands"""
    print("\n" + "=" * 60)
    print(f"🔧 更新版本字段 ({field_label})")
    print("=" * 60)

    version = api.get_editable_version(app_id)
    if not version:
        print("❌ 找不到可编辑的 App Store 版本")
        return
    version_id = version["id"]
    version_string = version["attributes"].get("versionString", "?")
    version_state = version["attributes"].get("appStoreState") or version[
        "attributes"
    ].get("appVersionState", "?")
    print(f"  版本: {version_string} (状态: {version_state})")

    ver_locs = api.get_version_localizations(version_id)
    if not ver_locs:
        print("❌ 该版本没有本地化信息")
        return

    target_locs = ver_locs
    if locales:
        target_locs = [loc for loc in ver_locs if loc["attributes"]["locale"] in locales]
        if not target_locs:
            available = [loc["attributes"]["locale"] for loc in ver_locs]
            print(f"❌ 指定的语言不存在，可用语言: {available}")
            return

    preview = field_value[:80] + "..." if len(field_value) > 80 else field_value
    print(f"  {field_label}: {preview}")
    print(f"  目标语言: {[loc['attributes']['locale'] for loc in target_locs]}")

    if dry_run:
        print("  ⚠️  预览模式，不实际更新")
        return

    for loc in target_locs:
        locale = loc["attributes"]["locale"]
        loc_id = loc["id"]
        api.update_version_localization(loc_id, {field_key: field_value})
        print(f"  ✅ {locale}: 已更新")

    print(f"\n✅ {field_label} 更新完成")


# ── typer command functions ──

def cmd_upload(
    app: Optional[str] = typer.Option(None, "--app", help="App profile name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without uploading"),
    csv: Optional[str] = typer.Option(None, "--csv", help="CSV metadata file path"),
    screenshots: Optional[str] = typer.Option(None, "--screenshots", help="Screenshots directory"),
    display_type: Optional[str] = typer.Option(None, "--display-type"),
):
    """Upload all (metadata + screenshots)"""
    from asc.commands.screenshots import _upload_screenshots_core
    config = Config(app)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    if csv_path.exists():
        metadata_list = parse_csv(str(csv_path))
        print(f"\n📄 从 CSV 读取了 {len(metadata_list)} 个语言的元数据")
        _upload_metadata_core(api, app_id, metadata_list, dry_run=dry_run)
    screenshots_path = Path(screenshots or config.screenshots_path)
    if screenshots_path.exists():
        _upload_screenshots_core(api, app_id, str(screenshots_path), display_type, dry_run)
    print("\n" + "=" * 60)
    print("🎉 全部完成！")
    print("=" * 60)


def cmd_metadata(
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    csv: Optional[str] = typer.Option(None, "--csv"),
):
    """Upload metadata only (name, subtitle, description, keywords, URLs)"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    _upload_metadata_core(api, app_id, metadata_list, dry_run=dry_run)


def cmd_keywords(
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    csv: Optional[str] = typer.Option(None, "--csv"),
):
    """Upload keywords only"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    _upload_metadata_core(api, app_id, metadata_list, dry_run=dry_run, include_version_fields={"keywords"})


def cmd_support_url(
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    csv: Optional[str] = typer.Option(None, "--csv"),
):
    """Upload support URL from CSV"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    _upload_metadata_core(api, app_id, metadata_list, dry_run=dry_run, include_version_fields={"supportUrl"})


def cmd_marketing_url(
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    csv: Optional[str] = typer.Option(None, "--csv"),
):
    """Upload marketing URL from CSV"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    _upload_metadata_core(api, app_id, metadata_list, dry_run=dry_run, include_version_fields={"marketingUrl"})


def cmd_privacy_policy_url(
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    csv: Optional[str] = typer.Option(None, "--csv"),
):
    """Upload privacy policy URL from CSV"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    _upload_metadata_core(api, app_id, metadata_list, dry_run=dry_run, include_version_fields={"privacyPolicyUrl"})


def cmd_set_support_url(
    url: str = typer.Option(..., "--text", help="Support URL"),
    locales: Optional[str] = typer.Option(None, "--locales", help="Comma-separated locales"),
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Directly set support URL for all (or specific) locales"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    locale_list = [l.strip() for l in locales.split(",")] if locales else None
    _update_version_field_core(api, app_id, "supportUrl", "Support URL", url, locale_list, dry_run)


def cmd_set_marketing_url(
    url: str = typer.Option(..., "--text", help="Marketing URL"),
    locales: Optional[str] = typer.Option(None, "--locales"),
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Directly set marketing URL for all (or specific) locales"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    locale_list = [l.strip() for l in locales.split(",")] if locales else None
    _update_version_field_core(api, app_id, "marketingUrl", "Marketing URL", url, locale_list, dry_run)


def cmd_set_privacy_policy_url(
    url: str = typer.Option(..., "--text", help="Privacy Policy URL"),
    locales: Optional[str] = typer.Option(None, "--locales"),
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Directly set privacy policy URL for all (or specific) locales"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    locale_list = [l.strip() for l in locales.split(",")] if locales else None
    _update_version_field_core(api, app_id, "privacyPolicyUrl", "Privacy Policy URL", url, locale_list, dry_run)


def cmd_check(
    app: Optional[str] = typer.Option(None, "--app"),
):
    """Verify environment and API configuration"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    print("\n🔐 验证 API 连接...")
    try:
        app_resp = api.get_app(app_id)
        app_name = app_resp["data"]["attributes"]["name"]
        bundle_id = app_resp["data"]["attributes"]["bundleId"]
        print(f"  ✅ 已连接: {app_name} ({bundle_id})")
    except Exception as e:
        typer.echo(f"  ❌ API 连接失败: {e}", err=True)
        raise typer.Exit(1)
```

- [ ] **Step 2: Commit**

```bash
git add src/asc/commands/metadata.py
git commit -m "$(cat <<'EOF'
feat: add metadata upload commands

upload, metadata, keywords, support-url, marketing-url,
privacy-policy-url, set-*-url, and check commands.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Create Screenshots Command

**Files:**
- Create: `src/asc/commands/screenshots.py`

- [ ] **Step 1: Write src/asc/commands/screenshots.py**

```python
"""Screenshots upload command"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

import typer
from PIL import Image

from asc.config import Config
from asc.constants import DISPLAY_TYPE_BY_SIZE, SCREENSHOT_FOLDER_TO_LOCALE
from asc.utils import make_api_from_config, resolve_locale


def _detect_display_type(image_path: Path) -> str | None:
    with Image.open(image_path) as img:
        size = img.size
    display_type = DISPLAY_TYPE_BY_SIZE.get(size)
    if display_type:
        return display_type
    print(f"  ⚠️  无法从尺寸 {size} 自动识别设备类型")
    return None


def _get_sorted_screenshots(folder: Path) -> list[Path]:
    extensions = {".png", ".jpg", ".jpeg"}
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in extensions]

    def sort_key(p: Path):
        nums = re.findall(r"\d+", p.stem)
        return int(nums[-1]) if nums else 0

    return sorted(files, key=sort_key)


def _upload_screenshots_core(
    api,
    app_id: str,
    screenshots_dir: str,
    display_type_override: str | None = None,
    dry_run: bool = False,
):
    """Core screenshots upload logic"""
    from asc.utils import md5_of_file

    print("\n" + "=" * 60)
    print("🖼️  上传截图")
    print("=" * 60)

    screenshots_path = Path(screenshots_dir)
    if not screenshots_path.exists():
        print(f"❌ 截图目录不存在: {screenshots_dir}")
        return

    version = api.get_editable_version(app_id)
    if not version:
        print("❌ 找不到可编辑的 App Store 版本")
        return
    version_id = version["id"]

    ver_locs = api.get_version_localizations(version_id)
    ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}
    existing_locales = list(ver_loc_map.keys())

    folders = [f for f in screenshots_path.iterdir() if f.is_dir()]
    if not folders:
        print("  截图目录中没有子文件夹")
        return

    locale_to_folder: dict[str, Path] = {}
    for folder in sorted(folders):
        folder_name = folder.name.lower()
        locale = SCREENSHOT_FOLDER_TO_LOCALE.get(folder_name, folder_name)
        resolved = resolve_locale(locale, existing_locales)
        locale_to_folder[resolved] = folder

    en_us_folder = locale_to_folder.get("en-US")
    if en_us_folder is None:
        for folder in folders:
            if folder.name.lower() in ("en", "en-us"):
                en_us_folder = folder
                break

    for resolved, loc_data in sorted(ver_loc_map.items()):
        folder = locale_to_folder.get(resolved)
        if folder is None:
            if en_us_folder is None:
                print(f"\n  ── locale: {resolved} → 无截图文件夹且无 en-US 可回退，跳过 ──")
                continue
            print(f"\n  ── locale: {resolved} → 无截图文件夹，使用 en-US 截图回退 ──")
            folder = en_us_folder
        else:
            print(f"\n  ── 文件夹: {folder.name} → locale: {resolved} ──")

        localization_id = loc_data["id"]
        files = _get_sorted_screenshots(folder)
        if not files:
            print("    没有找到截图文件，跳过")
            continue

        print(f"    找到 {len(files)} 张截图: {[f.name for f in files]}")

        display_type = display_type_override
        if not display_type:
            display_type = _detect_display_type(files[0])
        if not display_type:
            print("    ❌ 无法确定设备类型，请使用 --display-type 手动指定")
            continue
        print(f"    设备类型: {display_type}")

        if dry_run:
            for f in files:
                print(f"    [预览] 将上传: {f.name} ({f.stat().st_size / 1024:.0f} KB)")
            continue

        sets_resp = api.get_screenshot_sets(localization_id)
        sets_data = sets_resp.get("data", [])
        included = sets_resp.get("included", [])

        target_set = None
        for s in sets_data:
            if s["attributes"]["screenshotDisplayType"] == display_type:
                target_set = s
                break

        if target_set:
            set_id = target_set["id"]
            existing_shots = [
                inc
                for inc in included
                if inc["type"] == "appScreenshots"
                and inc.get("relationships", {})
                .get("appScreenshotSet", {})
                .get("data", {})
                .get("id")
                == set_id
            ]
            if not existing_shots:
                existing_shots = api.get_screenshots_in_set(set_id)

            if existing_shots:
                print(f"    🗑️  删除 {len(existing_shots)} 张已有截图...")
                for shot in existing_shots:
                    api.delete_screenshot(shot["id"])
                time.sleep(1)
        else:
            print("    创建截图集...")
            resp = api.create_screenshot_set(localization_id, display_type)
            set_id = resp["data"]["id"]

        print(f"    截图集 ID: {set_id}")

        for idx, file_path in enumerate(files, 1):
            filesize = file_path.stat().st_size
            filename = file_path.name
            print(f"    [{idx}/{len(files)}] 上传: {filename} ({filesize / 1024:.0f} KB)")

            reserve_resp = api.reserve_screenshot(set_id, filename, filesize)
            screenshot_data = reserve_resp["data"]
            screenshot_id = screenshot_data["id"]
            upload_ops = screenshot_data["attributes"]["uploadOperations"]

            api.upload_screenshot_asset(upload_ops, file_path)

            checksum = md5_of_file(file_path)
            api.commit_screenshot(screenshot_id, checksum)

            for retry in range(30):
                time.sleep(2)
                check = api.get(f"/v1/appScreenshots/{screenshot_id}")
                state = check["data"]["attributes"]["assetDeliveryState"]["state"]
                if state == "COMPLETE":
                    print("         ✅ 上传完成")
                    break
                elif state == "FAILED":
                    errors = check["data"]["attributes"]["assetDeliveryState"].get("errors", [])
                    print(f"         ❌ 上传失败: {errors}")
                    break
                else:
                    if retry % 5 == 4:
                        print(f"         ⏳ 处理中 ({state})...")
            else:
                print("         ⚠️  处理超时，请在 App Store Connect 中检查状态")

    print("\n✅ 截图上传完成")


def cmd_screenshots(
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    screenshots: Optional[str] = typer.Option(None, "--screenshots"),
    display_type: Optional[str] = typer.Option(None, "--display-type"),
):
    """Upload screenshots"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    screenshots_dir = screenshots or config.screenshots_path
    _upload_screenshots_core(api, app_id, screenshots_dir, display_type, dry_run)
```

- [ ] **Step 2: Commit**

```bash
git add src/asc/commands/screenshots.py
git commit -m "$(cat <<'EOF'
feat: add screenshots upload command

Auto-detect device type from pixel dimensions, delete before re-upload,
en-US fallback for missing locale folders.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Create IAP Command

**Files:**
- Create: `src/asc/commands/iap.py`

- [ ] **Step 1: Write src/asc/commands/iap.py**

```python
"""IAP upload command"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from asc.config import Config
from asc.utils import make_api_from_config


def _load_iap_package(file_path: str) -> list[dict]:
    raw = Path(file_path).read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    if isinstance(data, dict):
        items = data.get("items", [])
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("IAP 配置格式错误：应为数组或包含 items 数组的对象")

    if not isinstance(items, list) or not items:
        raise ValueError("IAP 配置为空，请至少提供一个 IAP 项")
    return items


def _upload_iap_core(api, app_id: str, iap_items: list[dict], dry_run: bool = False):
    print("\n" + "=" * 60)
    print("🛍️  上传 IAP 包")
    print("=" * 60)

    existing_iaps = api.list_in_app_purchases(app_id)
    existing_by_product_id = {}
    for iap in existing_iaps:
        product_id = iap.get("attributes", {}).get("productId")
        if product_id:
            existing_by_product_id[product_id] = iap

    for item in iap_items:
        product_id = str(item.get("productId", "")).strip()
        if not product_id:
            print("  ❌ 跳过：缺少 productId")
            continue

        name = str(item.get("name", "")).strip()
        iap_type = str(item.get("inAppPurchaseType", "")).strip()
        review_note = str(item.get("reviewNote", "")).strip()
        available_all = item.get("availableInAllTerritories", True)
        localizations = item.get("localizations", {})

        print(f"\n  ── IAP: {product_id} ──")
        existing = existing_by_product_id.get(product_id)

        attrs = {"productId": product_id, "availableInAllTerritories": bool(available_all)}
        if name:
            attrs["name"] = name
        if iap_type:
            attrs["inAppPurchaseType"] = iap_type
        if review_note:
            attrs["reviewNote"] = review_note

        if existing:
            iap_id = existing["id"]
            print(f"    已存在，ID: {iap_id}，执行更新")
            if not dry_run:
                update_attrs = {k: v for k, v in attrs.items() if k != "productId"}
                if update_attrs:
                    api.update_in_app_purchase(iap_id, update_attrs)
        else:
            print("    不存在，执行创建")
            if not dry_run:
                create_resp = api.create_in_app_purchase(app_id, attrs)
                iap_id = create_resp["data"]["id"]
                print(f"    ✅ 已创建，ID: {iap_id}")
            else:
                iap_id = "DRY_RUN_ID"

        if not isinstance(localizations, dict) or not localizations:
            print("    ⚠️  无本地化配置，跳过本地化上传")
            continue

        if dry_run:
            print(f"    [预览] 将更新本地化: {list(localizations.keys())}")
            continue

        existing_locs = api.get_in_app_purchase_localizations(iap_id)
        loc_map = {loc["attributes"]["locale"]: loc for loc in existing_locs}

        for locale, loc_data in localizations.items():
            if not isinstance(loc_data, dict):
                print(f"    ⚠️  locale={locale} 配置格式错误，已跳过")
                continue
            loc_attrs = {}
            display_name = str(loc_data.get("name") or loc_data.get("displayName") or "").strip()
            description = str(loc_data.get("description") or "").strip()
            if display_name:
                loc_attrs["name"] = display_name
            if description:
                loc_attrs["description"] = description
            if not loc_attrs:
                print(f"    ⚠️  locale={locale} 无有效字段（name/description），已跳过")
                continue

            if locale in loc_map:
                api.update_in_app_purchase_localization(loc_map[locale]["id"], loc_attrs)
                print(f"    ✅ {locale}: 已更新本地化")
            else:
                api.create_in_app_purchase_localization(iap_id, locale, loc_attrs)
                print(f"    ✅ {locale}: 已创建本地化")

    print("\n✅ IAP 上传完成")


def cmd_iap(
    iap_file: str = typer.Option(..., "--iap-file", help="IAP JSON config file path"),
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Upload in-app purchases from JSON file"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    iap_path = Path(iap_file)
    if not iap_path.exists():
        typer.echo(f"❌ IAP 配置文件不存在: {iap_path}", err=True)
        raise typer.Exit(1)
    iap_items = _load_iap_package(str(iap_path))
    print(f"\n📦 从 IAP 配置读取 {len(iap_items)} 项")
    _upload_iap_core(api, app_id, iap_items, dry_run)
```

- [ ] **Step 2: Commit**

```bash
git add src/asc/commands/iap.py
git commit -m "$(cat <<'EOF'
feat: add IAP upload command

Create or patch IAP products with localizations from JSON config.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Create What's New Command

**Files:**
- Create: `src/asc/commands/whats_new.py`

- [ ] **Step 1: Write src/asc/commands/whats_new.py**

```python
"""What's New (release notes) upload command"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from asc.config import Config
from asc.utils import make_api_from_config, resolve_locale


def _parse_whats_new_file(file_path: str) -> dict[str, str]:
    """Parse multi-locale whats_new.txt file"""
    content = Path(file_path).read_text(encoding="utf-8-sig").strip()
    entries = {}
    current_locale = None
    current_lines = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if current_locale and current_lines:
                entries[current_locale] = "\n".join(current_lines).strip()
            current_locale = None
            current_lines = []
        elif current_locale is None and stripped.endswith(":"):
            current_locale = stripped[:-1].strip()
        elif current_locale is None and ":" in stripped and len(stripped.split(":")[0]) < 20:
            parts = stripped.split(":", 1)
            current_locale = parts[0].strip()
            if parts[1].strip():
                current_lines.append(parts[1].strip())
        elif current_locale:
            current_lines.append(line.rstrip())

    if current_locale and current_lines:
        entries[current_locale] = "\n".join(current_lines).strip()

    return entries


def cmd_whats_new(
    text: Optional[str] = typer.Option(None, "--text", help="Release notes text (all locales)"),
    file: Optional[str] = typer.Option(None, "--file", help="Path to multi-locale whats_new.txt"),
    locales: Optional[str] = typer.Option(None, "--locales", help="Comma-separated locales"),
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Update What's New (release notes)"""
    if not text and not file:
        typer.echo("❌ 请指定 --text 或 --file", err=True)
        raise typer.Exit(1)

    config = Config(app)
    api, app_id = make_api_from_config(config)

    version = api.get_editable_version(app_id)
    if not version:
        typer.echo("❌ 找不到可编辑的 App Store 版本", err=True)
        raise typer.Exit(1)
    version_id = version["id"]
    version_string = version["attributes"].get("versionString", "?")
    print(f"\n📋 更新版本描述 (What's New)")
    print(f"  版本: {version_string}")

    ver_locs = api.get_version_localizations(version_id)
    if not ver_locs:
        typer.echo("❌ 该版本没有本地化信息", err=True)
        raise typer.Exit(1)
    ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}
    existing_locales = list(ver_loc_map.keys())

    if file:
        file_path = Path(file)
        if not file_path.exists():
            typer.echo(f"❌ 文件不存在: {file_path}", err=True)
            raise typer.Exit(1)
        entries = _parse_whats_new_file(str(file_path))
        if not entries:
            typer.echo(f"❌ 未从文件中解析到更新描述: {file_path}", err=True)
            raise typer.Exit(1)

        for locale, content in entries.items():
            resolved = resolve_locale(locale, existing_locales)
            preview = content[:60] + "..." if len(content) > 60 else content
            print(f"\n  ── {locale} → {resolved} ──")
            print(f"    内容: {preview}")
            if resolved not in ver_loc_map:
                print(f"    ⚠️  locale '{resolved}' 不存在，跳过")
                continue
            if not dry_run:
                api.update_version_localization(ver_loc_map[resolved]["id"], {"whatsNew": content})
                print("    ✅ 已更新")
    else:
        locale_list = None
        if locales:
            locale_list = [l.strip() for l in locales.split(",")]

        target_locs = ver_locs
        if locale_list:
            target_locs = [loc for loc in ver_locs if loc["attributes"]["locale"] in locale_list]
            if not target_locs:
                typer.echo(f"❌ 指定的语言不存在，可用语言: {existing_locales}", err=True)
                raise typer.Exit(1)

        preview = text[:80] + "..." if len(text) > 80 else text
        print(f"  更新内容: {preview}")
        print(f"  目标语言: {[loc['attributes']['locale'] for loc in target_locs]}")

        if dry_run:
            print("  ⚠️  预览模式，不实际更新")
            return

        for loc in target_locs:
            locale = loc["attributes"]["locale"]
            loc_id = loc["id"]
            api.update_version_localization(loc_id, {"whatsNew": text})
            print(f"  ✅ {locale}: 已更新")

    print("\n✅ 版本描述更新完成")
```

- [ ] **Step 2: Commit**

```bash
git add src/asc/commands/whats_new.py
git commit -m "$(cat <<'EOF'
feat: add whats-new command

Support --text (all locales), --file (multi-locale format), and
--locales (locale filter).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Create App Config Commands

**Files:**
- Create: `src/asc/commands/app_config.py`

- [ ] **Step 1: Write src/asc/commands/app_config.py**

```python
"""App profile management commands"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import typer

from asc.config import Config


def cmd_app_add(
    name: str = typer.Argument(..., help="Profile name for this app"),
):
    """Interactively add a new app profile"""
    typer.echo(f"Adding app profile: {name}")
    typer.echo("Enter your App Store Connect credentials:")

    issuer_id = typer.prompt("  Issuer ID")
    key_id = typer.prompt("  Key ID")
    key_file_input = typer.prompt("  Path to .p8 private key file")
    app_id = typer.prompt("  App ID (numeric)")

    key_path = Path(key_file_input).expanduser()
    if not key_path.exists():
        typer.echo(f"❌ Key file not found: {key_path}", err=True)
        raise typer.Exit(1)

    # Copy key file to global config dir
    global_keys_dir = Path.home() / ".config" / "asc" / "keys"
    global_keys_dir.mkdir(parents=True, exist_ok=True)
    dest_key = global_keys_dir / key_path.name
    if not dest_key.exists():
        shutil.copy2(key_path, dest_key)
        typer.echo(f"  ✅ Key file copied to {dest_key}")

    config = Config()
    config.save_app_profile(name, issuer_id, key_id, str(dest_key), app_id)
    typer.echo(f"\n✅ App profile '{name}' saved.")
    typer.echo(f"   Use: asc --app {name} upload")


def cmd_app_list():
    """List all configured app profiles"""
    config = Config()
    apps = config.list_apps()
    if not apps:
        typer.echo("No app profiles configured.")
        typer.echo("Run: asc app add <name>")
        return
    typer.echo("Configured app profiles:")
    for app_name in apps:
        typer.echo(f"  • {app_name}")


def cmd_app_remove(
    name: str = typer.Argument(..., help="Profile name to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove an app profile"""
    if not yes:
        confirmed = typer.confirm(f"Remove app profile '{name}'?")
        if not confirmed:
            raise typer.Abort()
    config = Config()
    config.remove_app_profile(name)
    typer.echo(f"✅ App profile '{name}' removed.")
```

- [ ] **Step 2: Commit**

```bash
git add src/asc/commands/app_config.py
git commit -m "$(cat <<'EOF'
feat: add app profile management commands

asc app add/list/remove for managing multi-app credentials.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Install and Smoke Test

**Files:**
- Read: `pyproject.toml`

- [ ] **Step 1: Install package in editable mode**

```bash
pip install -e ".[dev]"
```

Expected: Successfully installed asc-appstore-tools

- [ ] **Step 2: Verify asc command is available**

Run: `asc --version`
Expected: `asc version 0.1.0`

- [ ] **Step 3: Verify help output**

Run: `asc --help`
Expected: Subcommand list including upload, metadata, keywords, screenshots, iap, whats-new, check, app

- [ ] **Step 4: Verify app subcommand help**

Run: `asc app --help`
Expected: add, list, remove subcommands

- [ ] **Step 5: Verify check command (dry)**

Run: `asc check --help`
Expected: Help text without errors

- [ ] **Step 6: Test imports are clean**

Run: `python -c "from asc.cli import app; print('imports OK')"`
Expected: `imports OK`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat: install and verify asc CLI package

All commands import cleanly; asc --version and --help work.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Add GitHub Actions Publish Workflow

**Files:**
- Create: `.github/workflows/publish.yml`

- [ ] **Step 1: Create workflows directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Write .github/workflows/publish.yml**

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - "v*.*.*"

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install build tools
        run: pip install build twine

      - name: Build package
        run: python -m build

      - name: Publish to PyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: twine upload dist/*
```

- [ ] **Step 3: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/publish.yml')); print('Valid YAML')"`
(Install pyyaml if needed: `pip install pyyaml`)

Expected: `Valid YAML`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/publish.yml
git commit -m "$(cat <<'EOF'
feat: add GitHub Actions PyPI publish workflow

Triggers on v*.*.* tags. Requires PYPI_API_TOKEN repository secret.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: Deprecate run.sh and Update README

**Files:**
- Modify: `run.sh` (add deprecation notice at top)
- Modify: `README.md`

- [ ] **Step 1: Add deprecation notice to run.sh**

Edit `run.sh`, add after the `set -euo pipefail` line:

```bash
echo "⚠️  run.sh is deprecated. Install the pip package instead:"
echo "    pip install asc-appstore-tools"
echo "    asc --help"
echo ""
```

- [ ] **Step 2: Update README.md installation section**

Add at the top of the Installation section:

```markdown
## Installation

```bash
pip install asc-appstore-tools
```

Then configure your first app:

```bash
asc app add myapp
# (interactive: enter Issuer ID, Key ID, key file path, App ID)
```

## Usage

```bash
asc --app myapp upload
asc --app myapp metadata
asc --app myapp keywords
asc --app myapp screenshots --display-type APP_IPHONE_67
asc --app myapp whats-new --text "Bug fixes."
asc --app myapp check
```

For multi-locale release notes, use a file:

```bash
asc --app myapp whats-new --file data/whats_new.txt
```
```

- [ ] **Step 3: Commit**

```bash
git add run.sh README.md
git commit -m "$(cat <<'EOF'
docs: deprecate run.sh and update README for pip install

Add deprecation notice to run.sh; add pip install and asc app add
getting started guide to README.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage check:**

| Spec Requirement | Task |
|---|---|
| pip install asc-appstore-tools | Task 5 (pyproject.toml) |
| `asc` command name | Task 5 + Task 6 |
| typer framework | Task 6, 7, 8, 9, 10, 11, 12 |
| All existing subcommands (upload, metadata, keywords, support-url, marketing-url, privacy-policy-url, set-*-url, screenshots, iap, whats-new, check) | Task 8, 9, 10, 11 |
| `--app NAME` global option | Task 8–12 (all commands accept `--app`) |
| `asc app add/list/remove` | Task 12 |
| Global config ~/.config/asc/ | Task 4 |
| Local config .asc/config.toml | Task 4 |
| Env var fallback (backward compat) | Task 4 |
| GitHub Actions PyPI publish | Task 14 |
| Single version source in __init__.py | Task 1 |

**Placeholder scan:** No TBDs, TODOs, or vague steps found.

**Type consistency:** `make_api_from_config` returns `(AppStoreConnectAPI, str)` and is imported the same way in all command files. `_upload_screenshots_core` is imported from `screenshots.py` in `cmd_upload` inside `metadata.py`.

**Note for implementer:** In `pyproject.toml` Task 5, replace `"Your Name"` and `"your.email@example.com"` and the GitHub URLs with real values before publishing to PyPI.

