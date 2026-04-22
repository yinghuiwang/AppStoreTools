"""App Store Connect API client"""

from __future__ import annotations

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
                            "data": {
                                "type": "appScreenshotSets",
                                "id": screenshot_set_id,
                            }
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
                raise Exception(
                    f"截图上传失败 [{resp.status_code}]: {resp.text[:200]}"
                )

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
