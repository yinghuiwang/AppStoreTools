#!/usr/bin/env python3
"""
App Store Connect 元数据 & 截图上传工具

用法:
  1. 复制 .env.example 为 .env 并填写你的 API 凭证
  2. pip install -r requirements.txt
  3. python upload_to_appstore.py

可选参数:
  --csv           CSV 元数据文件路径 (默认: ./appstore_info.csv)
  --screenshots   截图目录路径 (默认: ./screenshots)
  --display-type  截图设备类型 (默认: 自动检测)
  --dry-run       仅预览将要执行的操作，不实际上传
  --metadata-only 仅上传元数据，跳过截图
  --screenshots-only 仅上传截图，跳过元数据
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

try:
    import jwt
    import requests
    from PIL import Image
    from dotenv import load_dotenv
except ImportError as e:
    print(f"缺少依赖: {e}")
    print("请运行: pip install -r requirements.txt")
    sys.exit(1)

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
    "zh-Hans": "zh-Hans",
    "zh-Hant": "zh-Hant",
    "ja": "ja",
    "ko": "ko",
    "fr": "fr-FR",
    "de": "de-DE",
    "es": "es-ES",
    "pt-BR": "pt-BR",
}


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
        self._token = jwt.encode(payload, self.private_key, algorithm="ES256", headers={"kid": self.key_id})
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
                    error_detail = "; ".join(e.get("detail", e.get("title", "")) for e in errors)
                except Exception:
                    error_detail = resp.text[:500]
                raise Exception(f"API 错误 [{resp.status_code}] {method} {url}: {error_detail}")

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
        return self.patch(f"/v1/appInfoLocalizations/{loc_id}", {
            "data": {
                "type": "appInfoLocalizations",
                "id": loc_id,
                "attributes": attributes,
            }
        })

    def create_app_info_localization(self, app_info_id: str, locale: str, attributes: dict) -> dict:
        return self.post("/v1/appInfoLocalizations", {
            "data": {
                "type": "appInfoLocalizations",
                "attributes": {"locale": locale, **attributes},
                "relationships": {
                    "appInfo": {
                        "data": {"type": "appInfos", "id": app_info_id}
                    }
                },
            }
        })

    # ── 版本信息 ──

    def get_editable_version(self, app_id: str, platform: str = "IOS") -> dict | None:
        resp = self.get(
            f"/v1/apps/{app_id}/appStoreVersions",
            **{"filter[platform]": platform}
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
            state = v["attributes"].get("appStoreState") or v["attributes"].get("appVersionState", "")
            if state in editable_states:
                return v
        return versions[0] if versions else None

    def get_version_localizations(self, version_id: str) -> list:
        resp = self.get(f"/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations")
        return resp.get("data", [])

    def update_version_localization(self, loc_id: str, attributes: dict) -> dict:
        return self.patch(f"/v1/appStoreVersionLocalizations/{loc_id}", {
            "data": {
                "type": "appStoreVersionLocalizations",
                "id": loc_id,
                "attributes": attributes,
            }
        })

    def create_version_localization(self, version_id: str, locale: str, attributes: dict) -> dict:
        return self.post("/v1/appStoreVersionLocalizations", {
            "data": {
                "type": "appStoreVersionLocalizations",
                "attributes": {"locale": locale, **attributes},
                "relationships": {
                    "appStoreVersion": {
                        "data": {"type": "appStoreVersions", "id": version_id}
                    }
                },
            }
        })

    # ── 截图 ──

    def get_screenshot_sets(self, localization_id: str) -> list:
        resp = self.get(f"/v1/appStoreVersionLocalizations/{localization_id}/appScreenshotSets",
                        **{"include": "appScreenshots"})
        return resp

    def create_screenshot_set(self, localization_id: str, display_type: str) -> dict:
        return self.post("/v1/appScreenshotSets", {
            "data": {
                "type": "appScreenshotSets",
                "attributes": {"screenshotDisplayType": display_type},
                "relationships": {
                    "appStoreVersionLocalization": {
                        "data": {"type": "appStoreVersionLocalizations", "id": localization_id}
                    }
                },
            }
        })

    def get_screenshots_in_set(self, screenshot_set_id: str) -> list:
        resp = self.get(f"/v1/appScreenshotSets/{screenshot_set_id}/appScreenshots")
        return resp.get("data", [])

    def delete_screenshot(self, screenshot_id: str):
        return self.delete(f"/v1/appScreenshots/{screenshot_id}")

    def reserve_screenshot(self, screenshot_set_id: str, filename: str, filesize: int) -> dict:
        return self.post("/v1/appScreenshots", {
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
        })

    def upload_screenshot_asset(self, upload_operations: list, file_path: Path):
        file_data = file_path.read_bytes()
        for op in upload_operations:
            url = op["url"]
            offset = op["offset"]
            length = op["length"]
            req_headers = {h["name"]: h["value"] for h in op["requestHeaders"]}
            chunk = file_data[offset: offset + length]
            resp = requests.put(url, headers=req_headers, data=chunk)
            if resp.status_code not in (200, 201):
                raise Exception(f"截图上传失败 [{resp.status_code}]: {resp.text[:200]}")

    def commit_screenshot(self, screenshot_id: str, md5_checksum: str) -> dict:
        return self.patch(f"/v1/appScreenshots/{screenshot_id}", {
            "data": {
                "type": "appScreenshots",
                "id": screenshot_id,
                "attributes": {
                    "uploaded": True,
                    "sourceFileChecksum": md5_checksum,
                },
            }
        })


def extract_locale(raw_lang: str) -> str:
    """从 '简体中文(zh-Hans)' 或 '英文(en-US)' 格式中提取 locale 代码"""
    m = re.search(r"\(([^)]+)\)", raw_lang)
    if m:
        return m.group(1)
    return raw_lang.strip()


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


def detect_display_type(image_path: Path) -> str | None:
    """从截图尺寸推断 App Store Connect 设备类型"""
    with Image.open(image_path) as img:
        size = img.size
    display_type = DISPLAY_TYPE_BY_SIZE.get(size)
    if display_type:
        return display_type
    print(f"  ⚠️  无法从尺寸 {size} 自动识别设备类型")
    return None


def get_sorted_screenshots(folder: Path) -> list[Path]:
    """获取排序后的截图文件列表"""
    extensions = {".png", ".jpg", ".jpeg"}
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in extensions]

    def sort_key(p: Path):
        nums = re.findall(r"\d+", p.stem)
        return int(nums[-1]) if nums else 0

    return sorted(files, key=sort_key)


def resolve_locale(csv_locale: str, existing_locales: list[str]) -> str | None:
    """将 CSV 中的语言代码映射到 ASC 中实际存在的 locale"""
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


def upload_metadata(api: AppStoreConnectAPI, app_id: str, metadata_list: list[dict], dry_run: bool = False):
    """上传元数据（应用名称、副标题、描述、关键词等）"""
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
    version_state = version["attributes"].get("appStoreState") or version["attributes"].get("appVersionState", "?")
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
        if name or subtitle:
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
                    print(f"    ✅ 已更新 App Info 本地化")
                else:
                    api.create_app_info_localization(app_info_id, info_locale, info_attrs)
                    print(f"    ✅ 已创建 App Info 本地化")
                    existing_info_locales.append(info_locale)

        description = meta.get("长描述", "")
        keywords = meta.get("关键子", "")
        support_url = meta.get("技术支持链接", "")
        marketing_url = meta.get("营销网站", "")

        ver_attrs = {}
        if description:
            ver_attrs["description"] = description
        if keywords:
            ver_attrs["keywords"] = keywords
        if support_url:
            ver_attrs["supportUrl"] = support_url
        if marketing_url:
            ver_attrs["marketingUrl"] = marketing_url

        if ver_attrs:
            desc_preview = description[:60] + "..." if len(description) > 60 else description
            print(f"    描述: {desc_preview}")
            if keywords:
                print(f"    关键词: {keywords[:60]}{'...' if len(keywords) > 60 else ''}")
            if support_url:
                print(f"    技术支持: {support_url}")
            if marketing_url:
                print(f"    营销网站: {marketing_url}")

            if not dry_run:
                if ver_locale in ver_loc_map:
                    api.update_version_localization(ver_loc_map[ver_locale]["id"], ver_attrs)
                    print(f"    ✅ 已更新版本本地化")
                else:
                    try:
                        api.create_version_localization(version_id, ver_locale, ver_attrs)
                        print(f"    ✅ 已创建版本本地化")
                    except Exception as e:
                        if "409" in str(e) or "already exists" in str(e):
                            print(f"    ⚠️  版本本地化已存在，重新获取后更新...")
                            ver_locs = api.get_version_localizations(version_id)
                            ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}
                            if ver_locale in ver_loc_map:
                                api.update_version_localization(ver_loc_map[ver_locale]["id"], ver_attrs)
                                print(f"    ✅ 已更新版本本地化")
                            else:
                                print(f"    ❌ 无法处理版本本地化: {e}")
                        else:
                            raise

    print("\n✅ 元数据上传完成")


def upload_screenshots(
    api: AppStoreConnectAPI,
    app_id: str,
    screenshots_dir: str,
    display_type_override: str | None = None,
    dry_run: bool = False,
):
    """上传截图"""
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

    for folder in sorted(folders):
        folder_name = folder.name.lower()
        locale = SCREENSHOT_FOLDER_TO_LOCALE.get(folder_name, folder_name)
        resolved = resolve_locale(locale, existing_locales)
        print(f"\n  ── 文件夹: {folder.name} → locale: {resolved} ──")

        if resolved not in ver_loc_map:
            print(f"    ⚠️  locale '{resolved}' 在版本本地化中不存在，跳过")
            continue

        localization_id = ver_loc_map[resolved]["id"]
        files = get_sorted_screenshots(folder)
        if not files:
            print(f"    没有找到截图文件，跳过")
            continue

        print(f"    找到 {len(files)} 张截图: {[f.name for f in files]}")

        display_type = display_type_override
        if not display_type:
            display_type = detect_display_type(files[0])
        if not display_type:
            print(f"    ❌ 无法确定设备类型，请使用 --display-type 手动指定")
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
                inc for inc in included
                if inc["type"] == "appScreenshots"
                and inc.get("relationships", {}).get("appScreenshotSet", {}).get("data", {}).get("id") == set_id
            ]
            if not existing_shots:
                existing_shots = api.get_screenshots_in_set(set_id)

            if existing_shots:
                print(f"    🗑️  删除 {len(existing_shots)} 张已有截图...")
                for shot in existing_shots:
                    api.delete_screenshot(shot["id"])
                time.sleep(1)
        else:
            print(f"    创建截图集...")
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
                    print(f"         ✅ 上传完成")
                    break
                elif state == "FAILED":
                    errors = check["data"]["attributes"]["assetDeliveryState"].get("errors", [])
                    print(f"         ❌ 上传失败: {errors}")
                    break
                else:
                    if retry % 5 == 4:
                        print(f"         ⏳ 处理中 ({state})...")
            else:
                print(f"         ⚠️  处理超时，请在 App Store Connect 中检查状态")

    print("\n✅ 截图上传完成")


def update_whats_new(
    api: AppStoreConnectAPI,
    app_id: str,
    whats_new_text: str,
    locales: list[str] | None = None,
    dry_run: bool = False,
):
    """更新 App Store 版本的「更新描述」(What's New / Release Notes)"""
    print("\n" + "=" * 60)
    print("📋 更新版本描述 (What's New)")
    print("=" * 60)

    version = api.get_editable_version(app_id)
    if not version:
        print("❌ 找不到可编辑的 App Store 版本")
        return
    version_id = version["id"]
    version_string = version["attributes"].get("versionString", "?")
    version_state = version["attributes"].get("appStoreState") or version["attributes"].get("appVersionState", "?")
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

    preview = whats_new_text[:80] + "..." if len(whats_new_text) > 80 else whats_new_text
    print(f"  更新内容: {preview}")
    print(f"  目标语言: {[loc['attributes']['locale'] for loc in target_locs]}")

    if dry_run:
        print("  ⚠️  预览模式，不实际更新")
        return

    for loc in target_locs:
        locale = loc["attributes"]["locale"]
        loc_id = loc["id"]
        api.update_version_localization(loc_id, {"whatsNew": whats_new_text})
        print(f"  ✅ {locale}: 已更新")

    print("\n✅ 版本描述更新完成")


def update_whats_new_from_file(
    api: AppStoreConnectAPI,
    app_id: str,
    file_path: str,
    dry_run: bool = False,
):
    """从文件读取多语言更新描述并上传，文件格式为 locale:内容，用 --- 分隔"""
    print("\n" + "=" * 60)
    print("📋 从文件更新版本描述 (What's New)")
    print("=" * 60)

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

    if not entries:
        print(f"❌ 未从文件中解析到更新描述: {file_path}")
        return

    version = api.get_editable_version(app_id)
    if not version:
        print("❌ 找不到可编辑的 App Store 版本")
        return
    version_id = version["id"]
    version_string = version["attributes"].get("versionString", "?")
    print(f"  版本: {version_string}")

    ver_locs = api.get_version_localizations(version_id)
    ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}
    existing_locales = list(ver_loc_map.keys())

    for locale, text in entries.items():
        resolved = resolve_locale(locale, existing_locales)
        preview = text[:60] + "..." if len(text) > 60 else text
        print(f"\n  ── {locale} → {resolved} ──")
        print(f"    内容: {preview}")

        if resolved not in ver_loc_map:
            print(f"    ⚠️  locale '{resolved}' 不存在，跳过")
            continue

        if not dry_run:
            api.update_version_localization(ver_loc_map[resolved]["id"], {"whatsNew": text})
            print(f"    ✅ 已更新")

    print("\n✅ 版本描述更新完成")


def main():
    parser = argparse.ArgumentParser(
        description="上传元数据和截图到 App Store Connect",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--csv", default="./data/appstore_info.csv", help="CSV 元数据文件路径")
    parser.add_argument("--screenshots", default="./data/screenshots", help="截图目录路径")
    parser.add_argument("--display-type", help="截图设备类型 (如 APP_IPHONE_67)，不指定则自动检测")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际上传")
    parser.add_argument("--metadata-only", action="store_true", help="仅上传元数据")
    parser.add_argument("--screenshots-only", action="store_true", help="仅上传截图")
    parser.add_argument("--whats-new", help="设置更新描述 (What's New)，对所有语言生效")
    parser.add_argument("--whats-new-file", help="从文件读取多语言更新描述 (格式见 README)")
    parser.add_argument("--whats-new-locales", help="限定更新描述的语言，逗号分隔 (如 zh-Hans,en-US)")
    parser.add_argument("--app-id", help="App Apple ID (覆盖 .env 中的配置)")
    parser.add_argument("--issuer-id", help="Issuer ID (覆盖 .env 中的配置)")
    parser.add_argument("--key-id", help="Key ID (覆盖 .env 中的配置)")
    parser.add_argument("--key-file", help=".p8 私钥文件路径 (覆盖 .env 中的配置)")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    env_path = script_dir / "config" / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    issuer_id = args.issuer_id or os.getenv("ISSUER_ID")
    key_id = args.key_id or os.getenv("KEY_ID")
    key_file = args.key_file or os.getenv("KEY_FILE")
    app_id = args.app_id or os.getenv("APP_ID")

    missing = []
    if not issuer_id:
        missing.append("ISSUER_ID")
    if not key_id:
        missing.append("KEY_ID")
    if not key_file:
        missing.append("KEY_FILE")
    if not app_id:
        missing.append("APP_ID")
    if missing:
        print(f"❌ 缺少必要配置: {', '.join(missing)}")
        print("请在 .env 文件中设置，或通过命令行参数传入")
        print("参考 .env.example 获取配置模板")
        sys.exit(1)

    key_path = Path(key_file)
    if not key_path.is_absolute():
        key_path = script_dir / "config" / key_path
    if not key_path.exists():
        print(f"❌ 私钥文件不存在: {key_path}")
        sys.exit(1)

    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = script_dir / csv_path

    screenshots_path = Path(args.screenshots)
    if not screenshots_path.is_absolute():
        screenshots_path = script_dir / screenshots_path

    print("🚀 App Store Connect 上传工具")
    print(f"  App ID: {app_id}")
    print(f"  Key ID: {key_id}")
    if args.dry_run:
        print("  ⚠️  预览模式 (dry-run)")

    api = AppStoreConnectAPI(issuer_id, key_id, str(key_path))

    print("\n🔐 验证 API 连接...")
    try:
        app_resp = api.get_app(app_id)
        app_name = app_resp["data"]["attributes"]["name"]
        bundle_id = app_resp["data"]["attributes"]["bundleId"]
        print(f"  ✅ 已连接: {app_name} ({bundle_id})")
    except Exception as e:
        print(f"  ❌ API 连接失败: {e}")
        sys.exit(1)

    is_whats_new_mode = args.whats_new or args.whats_new_file

    if is_whats_new_mode:
        if args.whats_new_file:
            wn_path = Path(args.whats_new_file)
            if not wn_path.is_absolute():
                wn_path = script_dir / wn_path
            if not wn_path.exists():
                print(f"❌ 更新描述文件不存在: {wn_path}")
                sys.exit(1)
            update_whats_new_from_file(api, app_id, str(wn_path), dry_run=args.dry_run)
        else:
            locales = None
            if args.whats_new_locales:
                locales = [l.strip() for l in args.whats_new_locales.split(",")]
            update_whats_new(api, app_id, args.whats_new, locales=locales, dry_run=args.dry_run)
    else:
        if not args.screenshots_only:
            if csv_path.exists():
                metadata_list = parse_csv(str(csv_path))
                print(f"\n📄 从 CSV 读取了 {len(metadata_list)} 个语言的元数据")
                for m in metadata_list:
                    print(f"  - {m['语言']}: {m.get('应用名称', 'N/A')}")
                upload_metadata(api, app_id, metadata_list, dry_run=args.dry_run)
            else:
                print(f"\n⚠️  CSV 文件不存在: {csv_path}")

        if not args.metadata_only:
            if screenshots_path.exists():
                upload_screenshots(
                    api, app_id, str(screenshots_path),
                    display_type_override=args.display_type,
                    dry_run=args.dry_run,
                )
            else:
                print(f"\n⚠️  截图目录不存在: {screenshots_path}")

    print("\n" + "=" * 60)
    print("🎉 全部完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
