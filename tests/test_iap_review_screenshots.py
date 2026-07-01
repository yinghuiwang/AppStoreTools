"""Tests for IAP review screenshot scan and path matching."""
from __future__ import annotations

import json

from asc.commands.iap_review_screenshots import (
    ReviewScreenshotTarget,
    attach_default_paths,
    extract_review_screenshot_paths,
    scan_missing_review_screenshots,
)


class ReviewScreenshotFakeAPI:
    def __init__(self):
        self.calls = []
        self.iaps = [
            {
                "id": "iap_1",
                "attributes": {
                    "productId": "coins.100",
                    "name": "100 Coins",
                    "inAppPurchaseType": "CONSUMABLE",
                },
            },
            {
                "id": "iap_2",
                "attributes": {
                    "productId": "remove.ads",
                    "name": "Remove Ads",
                    "inAppPurchaseType": "NON_CONSUMABLE",
                },
            },
        ]
        self.iap_shots = {"iap_1": [], "iap_2": [{"id": "iap_shot_existing"}]}
        self.groups = [{"id": "grp_1", "attributes": {"referenceName": "Premium"}}]
        self.subs = {
            "grp_1": [
                {
                    "id": "sub_1",
                    "attributes": {
                        "productId": "premium.monthly",
                        "name": "Premium Monthly",
                    },
                },
                {
                    "id": "sub_2",
                    "attributes": {
                        "productId": "premium.yearly",
                        "name": "Premium Yearly",
                    },
                },
            ]
        }
        self.sub_shots = {"sub_1": [], "sub_2": [{"id": "sub_shot_existing"}]}

    def list_in_app_purchases(self, app_id):
        self.calls.append(("list_in_app_purchases", app_id))
        return self.iaps

    def list_in_app_purchase_review_screenshots(self, iap_id):
        self.calls.append(("list_in_app_purchase_review_screenshots", iap_id))
        return self.iap_shots.get(iap_id, [])

    def list_subscription_groups(self, app_id):
        self.calls.append(("list_subscription_groups", app_id))
        return self.groups

    def list_subscriptions(self, group_id):
        self.calls.append(("list_subscriptions", group_id))
        return self.subs.get(group_id, [])

    def list_subscription_review_screenshots(self, sub_id):
        self.calls.append(("list_subscription_review_screenshots", sub_id))
        return self.sub_shots.get(sub_id, [])


def test_scan_missing_review_screenshots_uses_online_state():
    api = ReviewScreenshotFakeAPI()

    result = scan_missing_review_screenshots(api, "app_1")

    assert [t.product_id for t in result.targets] == ["coins.100", "premium.monthly"]
    assert result.targets[0].kind == "iap"
    assert result.targets[0].id == "iap_1"
    assert result.targets[1].kind == "subscription"
    assert result.targets[1].id == "sub_1"
    assert result.targets[1].group_name == "Premium"
    assert result.errors == []
    assert ("list_in_app_purchases", "app_1") in api.calls
    assert ("list_subscription_groups", "app_1") in api.calls


def test_scan_records_per_product_errors_and_continues():
    api = ReviewScreenshotFakeAPI()

    def failing_iap_shots(iap_id):
        if iap_id == "iap_1":
            raise RuntimeError("relationship unavailable")
        return api.iap_shots.get(iap_id, [])

    api.list_in_app_purchase_review_screenshots = failing_iap_shots

    result = scan_missing_review_screenshots(api, "app_1")

    assert [t.product_id for t in result.targets] == ["premium.monthly"]
    assert result.errors == ["IAP coins.100: relationship unavailable"]


def test_extract_review_screenshot_paths_tolerates_incomplete_json(tmp_path):
    shot = tmp_path / "iap_review" / "coins.png"
    shot.parent.mkdir()
    shot.write_bytes(b"png")
    cfg = tmp_path / "iap_packages.json"
    cfg.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "productId": "coins.100",
                        "review": {"screenshot": "./iap_review/coins.png"},
                    },
                    {
                        "name": "missing product id",
                        "review": {"screenshot": "./ignored.png"},
                    },
                ],
                "subscriptionGroups": [
                    {
                        "subscriptions": [
                            {
                                "productId": "premium.monthly",
                                "review": {"screenshot": "/abs/monthly.png"},
                            },
                            {"productId": "premium.yearly"},
                        ]
                    }
                ],
            }
        )
    )

    paths = extract_review_screenshot_paths(str(cfg))

    assert paths == {
        "coins.100": str(shot),
        "premium.monthly": "/abs/monthly.png",
    }


def test_extract_review_screenshot_paths_missing_file_returns_empty(tmp_path):
    paths = extract_review_screenshot_paths(str(tmp_path / "missing.json"))

    assert paths == {}


def test_attach_default_paths_updates_matching_targets():
    targets = [
        ReviewScreenshotTarget(
            kind="iap", id="iap_1", product_id="coins.100", name="100 Coins"
        ),
        ReviewScreenshotTarget(
            kind="subscription",
            id="sub_1",
            product_id="premium.monthly",
            name="Premium Monthly",
            group_name="Premium",
        ),
    ]

    attach_default_paths(targets, {"coins.100": "/tmp/coins.png"})

    assert targets[0].default_path == "/tmp/coins.png"
    assert targets[1].default_path == ""
