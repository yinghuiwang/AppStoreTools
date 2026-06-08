"""Tests for _upload_iap_core in src/asc/commands/iap.py"""
from __future__ import annotations

import pytest
from pathlib import Path

from asc.commands.iap import _upload_iap_core


class IapFakeAPI:
    def __init__(self, existing_iaps=None):
        self.calls = []
        self._next = 1
        self._iaps = {
            iap["attributes"]["productId"]: iap
            for iap in (existing_iaps or [])
        }
        self._locs: dict[str, list] = {}
        self._review_shots: dict[str, list] = {}

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
        self._review_shots[iap_id] = []
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

    def list_in_app_purchase_review_screenshots(self, iap_id):
        self.calls.append(("list_in_app_purchase_review_screenshots", iap_id))
        return self._review_shots.get(iap_id, [])

    def create_in_app_purchase_review_screenshot_reservation(self, iap_id, filename, filesize):
        self.calls.append(
            ("create_in_app_purchase_review_screenshot_reservation", iap_id, filename, filesize)
        )
        shot_id = f"iap_shot_{len(self._review_shots.get(iap_id, [])) + 1}"
        self._review_shots.setdefault(iap_id, []).append(
            {"id": shot_id, "attributes": {"fileName": filename, "fileSize": filesize}}
        )
        return {
            "data": {
                "id": shot_id,
                "attributes": {
                    "uploadOperations": [{
                        "url": "https://upload.example.test",
                        "offset": 0,
                        "length": filesize,
                        "requestHeaders": [],
                    }]
                },
            }
        }

    def upload_in_app_purchase_review_screenshot(self, upload_operations, file_bytes):
        self.calls.append(("upload_in_app_purchase_review_screenshot", len(file_bytes)))

    def commit_in_app_purchase_review_screenshot(self, screenshot_id, source_file_checksum):
        self.calls.append(
            ("commit_in_app_purchase_review_screenshot", screenshot_id, source_file_checksum)
        )
        for shots in self._review_shots.values():
            for shot in shots:
                if shot["id"] == screenshot_id:
                    shot["uploaded"] = True

    def delete_in_app_purchase_review_screenshot(self, screenshot_id):
        self.calls.append(("delete_in_app_purchase_review_screenshot", screenshot_id))
        for iap_id, shots in list(self._review_shots.items()):
            self._review_shots[iap_id] = [s for s in shots if s["id"] != screenshot_id]


def test_iap_creates_new_item():
    api = IapFakeAPI()
    items = [{"productId": "com.example.item1", "name": "Item 1"}]
    _upload_iap_core(api, "app1", items)
    create_calls = [c for c in api.calls if c[0] == "create_in_app_purchase"]
    assert len(create_calls) == 1
    assert create_calls[0][2]["productId"] == "com.example.item1"


def test_iap_skips_existing_by_default():
    existing = [{"id": "iap_old", "attributes": {"productId": "com.example.item1"}}]
    api = IapFakeAPI(existing_iaps=existing)
    items = [{"productId": "com.example.item1", "name": "Item 1"}]
    _upload_iap_core(api, "app1", items)
    update_calls = [c for c in api.calls if c[0] == "update_in_app_purchase"]
    create_calls = [c for c in api.calls if c[0] == "create_in_app_purchase"]
    assert update_calls == []
    assert create_calls == []


def test_iap_updates_existing_when_flag_set():
    existing = [{"id": "iap_old", "attributes": {"productId": "com.example.item1"}}]
    api = IapFakeAPI(existing_iaps=existing)
    items = [{"productId": "com.example.item1", "name": "New Name"}]
    _upload_iap_core(api, "app1", items, update_existing=True)
    update_calls = [c for c in api.calls if c[0] == "update_in_app_purchase"]
    assert len(update_calls) == 1
    assert update_calls[0][1] == "iap_old"


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


def test_iap_dry_run_no_api_writes():
    api = IapFakeAPI()
    items = [{"productId": "com.example.item1", "name": "Item 1"}]
    _upload_iap_core(api, "app1", items, dry_run=True)
    write_calls = [c for c in api.calls if c[0] in (
        "create_in_app_purchase", "update_in_app_purchase",
        "create_in_app_purchase_localization", "update_in_app_purchase_localization",
        "create_in_app_purchase_review_screenshot_reservation",
        "upload_in_app_purchase_review_screenshot",
        "commit_in_app_purchase_review_screenshot",
        "delete_in_app_purchase_review_screenshot",
    )]
    assert write_calls == []


def test_iap_skips_item_without_product_id():
    api = IapFakeAPI()
    items = [{"name": "No Product ID"}]
    _upload_iap_core(api, "app1", items)
    create_calls = [c for c in api.calls if c[0] == "create_in_app_purchase"]
    assert create_calls == []


def test_iap_uploads_review_screenshot_for_new_item(tmp_path):
    shot = tmp_path / "review.png"
    shot.write_bytes(b"fake-png")
    api = IapFakeAPI()
    items = [{
        "productId": "com.example.item1",
        "review": {"note": "review note", "screenshot": str(shot)},
    }]

    _upload_iap_core(api, "app1", items)

    reservation_calls = [
        c for c in api.calls
        if c[0] == "create_in_app_purchase_review_screenshot_reservation"
    ]
    upload_calls = [
        c for c in api.calls if c[0] == "upload_in_app_purchase_review_screenshot"
    ]
    commit_calls = [
        c for c in api.calls if c[0] == "commit_in_app_purchase_review_screenshot"
    ]
    create_calls = [c for c in api.calls if c[0] == "create_in_app_purchase"]
    assert create_calls[0][2]["reviewNote"] == "review note"
    assert len(reservation_calls) == 1
    assert reservation_calls[0][2] == "review.png"
    assert upload_calls == [("upload_in_app_purchase_review_screenshot", len(b"fake-png"))]
    assert len(commit_calls) == 1


def test_iap_replaces_review_screenshot_when_update_existing(tmp_path):
    shot = tmp_path / "review.png"
    shot.write_bytes(b"fake-png")
    iap_id = "iap_old"
    existing = [{"id": iap_id, "attributes": {"productId": "com.example.item1"}}]
    api = IapFakeAPI(existing_iaps=existing)
    api._review_shots[iap_id] = [{"id": "old_shot", "attributes": {"fileName": "old.png"}}]
    items = [{
        "productId": "com.example.item1",
        "review": {"screenshot": str(shot)},
    }]

    _upload_iap_core(api, "app1", items, update_existing=True)

    delete_calls = [
        c for c in api.calls if c[0] == "delete_in_app_purchase_review_screenshot"
    ]
    reservation_calls = [
        c for c in api.calls
        if c[0] == "create_in_app_purchase_review_screenshot_reservation"
    ]
    assert delete_calls == [("delete_in_app_purchase_review_screenshot", "old_shot")]
    assert len(reservation_calls) == 1


from asc.commands.iap import _load_iap_config

def test_load_iap_config_resolves_relative_screenshot_path(tmp_path):
    """Relative screenshot paths are resolved against the config file's directory."""
    import json
    sub_dir = tmp_path / "configs"
    sub_dir.mkdir()
    shot_file = sub_dir / "shots" / "review.png"
    shot_file.parent.mkdir()
    shot_file.write_bytes(b"fake")

    cfg = {
        "subscriptionGroups": [{
            "referenceName": "TestGroup",
            "subscriptions": [{
                "productId": "com.test.sub",
                "name": "Sub",
                "subscriptionPeriod": "ONE_MONTH",
                "groupLevel": 1,
                "localizations": {"en-US": {"name": "Sub", "description": "desc"}},
                "price": {"baseTerritory": "USA", "baseAmount": "0.99"},
                "review": {
                    "note": "test note",
                    "screenshot": "./shots/review.png",
                },
            }],
        }],
    }
    cfg_path = sub_dir / "subs.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    items, subs = _load_iap_config(str(cfg_path))
    shot_path = subs[0]["subscriptions"][0]["review"]["screenshot"]
    assert Path(shot_path).is_absolute(), f"Expected absolute path, got: {shot_path}"
    assert Path(shot_path).exists(), f"Screenshot not found at resolved path: {shot_path}"


def test_load_iap_config_absolute_screenshot_path_untouched(tmp_path):
    """Absolute screenshot paths are kept as-is."""
    import json
    shot_file = tmp_path / "review.png"
    shot_file.write_bytes(b"fake")

    cfg = {
        "subscriptionGroups": [{
            "referenceName": "TestGroup",
            "subscriptions": [{
                "productId": "com.test.sub",
                "name": "Sub",
                "subscriptionPeriod": "ONE_MONTH",
                "groupLevel": 1,
                "localizations": {"en-US": {"name": "Sub", "description": "desc"}},
                "price": {"baseTerritory": "USA", "baseAmount": "0.99"},
                "review": {
                    "note": "test note",
                    "screenshot": str(shot_file),
                },
            }],
        }],
    }
    cfg_path = tmp_path / "subs.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    items, subs = _load_iap_config(str(cfg_path))
    shot_path = subs[0]["subscriptions"][0]["review"]["screenshot"]
    assert shot_path == str(shot_file)


def test_load_iap_config_validates_iap_review_screenshot(tmp_path):
    import json
    cfg = {
        "items": [{
            "productId": "com.test.item",
            "review": {"screenshot": "./missing.png"},
        }],
    }
    cfg_path = tmp_path / "iap.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    with pytest.raises(ValueError, match="review.screenshot file not found"):
        _load_iap_config(str(cfg_path))
