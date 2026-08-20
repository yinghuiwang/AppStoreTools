"""Tests for iap_packages.json load/save and mtime locking."""
from __future__ import annotations

import json
import time

import pytest

from asc.iap.local import (
    load_local_snapshot,
    merge_products,
    save_local_snapshot,
    snapshot_has_content,
    validate_snapshot,
)
from asc.listing.local import FileChangedError


def test_missing_file_returns_empty_snapshot(tmp_path):
    path = tmp_path / "missing.json"
    snapshot, mtime, exists = load_local_snapshot(path)
    assert exists is False
    assert mtime is None
    assert snapshot == {"items": [], "subscriptionGroups": []}
    assert snapshot_has_content(snapshot) is False


def test_empty_json_object_is_empty_snapshot(tmp_path):
    path = tmp_path / "iap.json"
    path.write_text("{}\n", encoding="utf-8")
    snapshot, mtime, exists = load_local_snapshot(path)
    assert exists is True
    assert mtime is not None
    assert snapshot["items"] == []
    assert snapshot["subscriptionGroups"] == []


def test_top_level_array_normalizes_to_items(tmp_path):
    path = tmp_path / "iap.json"
    path.write_text(
        json.dumps([{"productId": "com.app.coins", "inAppPurchaseType": "CONSUMABLE"}]),
        encoding="utf-8",
    )
    snapshot, _mtime, exists = load_local_snapshot(path)
    assert exists is True
    assert snapshot["items"][0]["productId"] == "com.app.coins"
    assert snapshot["subscriptionGroups"] == []


def test_save_mtime_conflict(tmp_path):
    path = tmp_path / "iap.json"
    save_local_snapshot(
        path,
        {"items": [{"productId": "a", "inAppPurchaseType": "CONSUMABLE"}], "subscriptionGroups": []},
    )
    snapshot, mtime, _ = load_local_snapshot(path)
    time.sleep(0.05)
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(FileChangedError):
        save_local_snapshot(path, snapshot, expected_mtime=mtime)


def test_save_updates_mtime(tmp_path):
    path = tmp_path / "iap.json"
    first = save_local_snapshot(
        path,
        {"items": [{"productId": "a", "inAppPurchaseType": "CONSUMABLE"}], "subscriptionGroups": []},
    )
    snapshot, mtime, _ = load_local_snapshot(path)
    assert mtime == first
    time.sleep(0.02)
    second = save_local_snapshot(path, snapshot, expected_mtime=mtime)
    assert second >= first


def test_save_accepts_non_renewing_subscription(tmp_path):
    path = tmp_path / "iap.json"
    save_local_snapshot(
        path,
        {
            "items": [
                {
                    "productId": "com.app.pass",
                    "inAppPurchaseType": "NON_RENEWING_SUBSCRIPTION",
                }
            ],
            "subscriptionGroups": [],
        },
    )
    snapshot, _mtime, exists = load_local_snapshot(path)
    assert exists is True
    assert snapshot["items"][0]["inAppPurchaseType"] == "NON_RENEWING_SUBSCRIPTION"


def test_merge_products_preserves_review_screenshot(tmp_path):
    local = {
        "items": [
            {
                "productId": "com.app.coins",
                "name": "Old",
                "inAppPurchaseType": "CONSUMABLE",
                "review": {"screenshot": "./iap_review/coins.png", "note": "keep me"},
            }
        ],
        "subscriptionGroups": [
            {
                "referenceName": "Premium",
                "subscriptions": [
                    {
                        "productId": "com.app.premium.month",
                        "name": "Monthly",
                        "review": {"screenshot": "./iap_review/month.png"},
                    }
                ],
            }
        ],
    }
    incoming = {
        "items": [
            {
                "productId": "com.app.coins",
                "name": "New coins",
                "inAppPurchaseType": "CONSUMABLE",
                "review": {"screenshot": "", "note": "from store"},
            }
        ],
        "subscriptionGroups": [
            {
                "referenceName": "Premium",
                "subscriptions": [
                    {
                        "productId": "com.app.premium.month",
                        "name": "Monthly from store",
                        "groupLevel": 1,
                    }
                ],
            }
        ],
    }
    merged = merge_products(local, incoming, product_ids={"com.app.coins", "com.app.premium.month"})
    assert merged["items"][0]["name"] == "New coins"
    assert merged["items"][0]["review"]["screenshot"] == "./iap_review/coins.png"
    sub = merged["subscriptionGroups"][0]["subscriptions"][0]
    assert sub["name"] == "Monthly from store"
    assert sub["review"]["screenshot"] == "./iap_review/month.png"
    assert sub["groupLevel"] == 1


def test_validate_snapshot_flags_unknown_type():
    issues = validate_snapshot(
        {
            "items": [{"productId": "x", "inAppPurchaseType": "NONSENSE"}],
            "subscriptionGroups": [],
        }
    )
    assert any("unknown type" in row["message"] for row in issues)


def test_missing_local_screenshot_ids_blank_and_missing_file(tmp_path):
    from asc.iap.local import missing_local_screenshot_ids

    shot = tmp_path / "review.png"
    shot.write_bytes(b"png")
    snapshot = {
        "items": [
            {"productId": "blank", "inAppPurchaseType": "CONSUMABLE", "review": {"screenshot": ""}},
            {
                "productId": "ok",
                "inAppPurchaseType": "CONSUMABLE",
                "review": {"screenshot": "review.png"},
            },
            {
                "productId": "gone",
                "inAppPurchaseType": "CONSUMABLE",
                "review": {"screenshot": "missing.png"},
            },
        ],
        "subscriptionGroups": [
            {
                "referenceName": "Premium",
                "subscriptions": [
                    {
                        "productId": "sub-blank",
                        "name": "Monthly",
                        "review": {"screenshot": "  "},
                    }
                ],
            }
        ],
    }
    missing = missing_local_screenshot_ids(snapshot, tmp_path / "iap.json")
    assert missing == {"blank", "gone", "sub-blank"}
