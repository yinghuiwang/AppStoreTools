"""Tests for IAP review screenshot scan and path matching."""
from __future__ import annotations

import json

from asc.commands.iap_review_screenshots import (
    ReviewScreenshotUploadItem,
    ReviewScreenshotTarget,
    attach_default_paths,
    extract_review_screenshot_paths,
    scan_missing_review_screenshots,
    upload_review_screenshots,
    validate_review_screenshot_path,
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


class UploadReviewScreenshotFakeAPI(ReviewScreenshotFakeAPI):
    def __init__(self):
        super().__init__()
        self.iap_shots = {"iap_1": []}
        self.sub_shots = {"sub_1": []}
        self.fail_commit_for = set()

    def create_in_app_purchase_review_screenshot_reservation(
        self, iap_id, filename, filesize
    ):
        self.calls.append(
            (
                "create_in_app_purchase_review_screenshot_reservation",
                iap_id,
                filename,
                filesize,
            )
        )
        return {
            "data": {
                "id": f"iap_shot_{iap_id}",
                "attributes": {"uploadOperations": []},
            }
        }

    def upload_in_app_purchase_review_screenshot(self, upload_operations, file_bytes):
        self.calls.append(("upload_in_app_purchase_review_screenshot", len(file_bytes)))

    def commit_in_app_purchase_review_screenshot(
        self, screenshot_id, source_file_checksum
    ):
        self.calls.append(
            (
                "commit_in_app_purchase_review_screenshot",
                screenshot_id,
                source_file_checksum,
            )
        )
        if screenshot_id in self.fail_commit_for:
            raise RuntimeError("commit failed")
        self.iap_shots["iap_1"] = [{"id": screenshot_id}]

    def create_subscription_review_screenshot_reservation(
        self, sub_id, filename, filesize
    ):
        self.calls.append(
            (
                "create_subscription_review_screenshot_reservation",
                sub_id,
                filename,
                filesize,
            )
        )
        return {
            "data": {
                "id": f"sub_shot_{sub_id}",
                "attributes": {"uploadOperations": []},
            }
        }

    def upload_subscription_review_screenshot(self, upload_operations, file_bytes):
        self.calls.append(("upload_subscription_review_screenshot", len(file_bytes)))

    def commit_subscription_review_screenshot(
        self, screenshot_id, source_file_checksum
    ):
        self.calls.append(
            (
                "commit_subscription_review_screenshot",
                screenshot_id,
                source_file_checksum,
            )
        )
        if screenshot_id in self.fail_commit_for:
            raise RuntimeError("commit failed")
        self.sub_shots["sub_1"] = [{"id": screenshot_id}]


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


def test_validate_review_screenshot_path_accepts_images(tmp_path):
    shot = tmp_path / "shot.PNG"
    shot.write_bytes(b"png")

    result = validate_review_screenshot_path(str(shot))

    assert result.ok is True
    assert result.path == shot
    assert result.warning == ""


def test_validate_review_screenshot_path_rejects_missing_file(tmp_path):
    result = validate_review_screenshot_path(str(tmp_path / "missing.png"))

    assert result.ok is False
    assert "file not found" in result.error


def test_validate_review_screenshot_path_rejects_unsupported_extension(tmp_path):
    shot = tmp_path / "shot.gif"
    shot.write_bytes(b"gif")

    result = validate_review_screenshot_path(str(shot))

    assert result.ok is False
    assert "must be .png/.jpg/.jpeg" in result.error


def test_upload_review_screenshots_uploads_iap_and_subscription(tmp_path):
    api = UploadReviewScreenshotFakeAPI()
    iap_shot = tmp_path / "iap.png"
    sub_shot = tmp_path / "sub.jpg"
    iap_shot.write_bytes(b"iap")
    sub_shot.write_bytes(b"sub")
    items = [
        ReviewScreenshotUploadItem(
            kind="iap", id="iap_1", product_id="coins.100", path=str(iap_shot)
        ),
        ReviewScreenshotUploadItem(
            kind="subscription",
            id="sub_1",
            product_id="premium.monthly",
            path=str(sub_shot),
        ),
    ]

    result = upload_review_screenshots(api, items)

    assert result.uploaded == 2
    assert result.skipped == 0
    assert result.failed == 0
    call_names = [call[0] for call in api.calls]
    assert "create_in_app_purchase_review_screenshot_reservation" in call_names
    assert "commit_in_app_purchase_review_screenshot" in call_names
    assert "create_subscription_review_screenshot_reservation" in call_names
    assert "commit_subscription_review_screenshot" in call_names


def test_upload_review_screenshots_skips_when_online_screenshot_appears(tmp_path):
    api = UploadReviewScreenshotFakeAPI()
    api.iap_shots["iap_1"] = [{"id": "existing"}]
    shot = tmp_path / "iap.png"
    shot.write_bytes(b"iap")

    result = upload_review_screenshots(
        api,
        [
            ReviewScreenshotUploadItem(
                kind="iap", id="iap_1", product_id="coins.100", path=str(shot)
            )
        ],
    )

    assert result.uploaded == 0
    assert result.skipped == 1
    assert result.failed == 0
    assert not any(
        call[0] == "create_in_app_purchase_review_screenshot_reservation"
        for call in api.calls
    )


def test_upload_review_screenshots_continues_after_failure(tmp_path):
    api = UploadReviewScreenshotFakeAPI()
    api.fail_commit_for.add("iap_shot_iap_1")
    iap_shot = tmp_path / "iap.png"
    sub_shot = tmp_path / "sub.jpg"
    iap_shot.write_bytes(b"iap")
    sub_shot.write_bytes(b"sub")

    result = upload_review_screenshots(
        api,
        [
            ReviewScreenshotUploadItem(
                kind="iap", id="iap_1", product_id="coins.100", path=str(iap_shot)
            ),
            ReviewScreenshotUploadItem(
                kind="subscription",
                id="sub_1",
                product_id="premium.monthly",
                path=str(sub_shot),
            ),
        ],
    )

    assert result.uploaded == 1
    assert result.failed == 1
    assert result.failures == [("coins.100", "commit failed")]
