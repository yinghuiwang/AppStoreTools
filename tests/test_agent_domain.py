from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image

from asc.listing.models import FIELD_NAMES
from asc.web.agent_domain import (
    count_listing_fields,
    iap_snapshot,
    inspect_screenshots,
    listing_snapshot,
    validate_iap,
    validate_listing,
)


def _write_listing_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    fieldnames = ["locale", *FIELD_NAMES]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
    return path


def test_missing_listing_iap_screenshots_paths(tmp_path: Path):
    csv_path = tmp_path / "missing.csv"
    iap_path = tmp_path / "missing.json"
    shots_path = tmp_path / "missing_shots"

    listing = listing_snapshot(csv_path)
    assert listing["ok"] is True
    assert listing["exists"] is False
    assert listing["locales"] == []

    iap = iap_snapshot(iap_path)
    assert iap["ok"] is True
    assert iap["exists"] is False
    assert iap["items"] == []
    assert iap["subscriptionGroups"] == []
    assert iap["item_count"] == 0
    assert iap["group_count"] == 0

    listing_issues = validate_listing(csv_path)
    assert listing_issues["ok"] is True
    assert listing_issues["exists"] is False
    assert listing_issues["issues"] == []
    assert listing_issues["error_count"] == 0
    assert listing_issues["warning_count"] == 0

    iap_issues = validate_iap(iap_path)
    assert iap_issues["ok"] is True
    assert iap_issues["exists"] is False
    assert iap_issues["issues"] == []
    assert iap_issues["error_count"] == 0
    assert iap_issues["warning_count"] == 0

    counts = count_listing_fields(csv_path)
    assert counts["ok"] is True
    assert counts["locales"] == []

    shots = inspect_screenshots(shots_path)
    assert shots["ok"] is True
    assert shots["exists"] is False
    assert shots["locales"] == []

    not_dir = tmp_path / "file.txt"
    not_dir.write_text("x", encoding="utf-8")
    assert inspect_screenshots(not_dir)["exists"] is False


def test_listing_snapshot_happy_fields(tmp_path: Path):
    path = _write_listing_csv(
        tmp_path / "appstore_info.csv",
        [
            {
                "locale": "en-US",
                "name": "My App",
                "subtitle": "A subtitle",
                "privacyPolicyUrl": "https://example.com/privacy",
                "description": "A description",
                "keywords": "app,tool",
                "supportUrl": "https://example.com/support",
                "marketingUrl": "https://example.com",
            }
        ],
    )
    result = listing_snapshot(path)
    assert result["ok"] is True
    assert result["exists"] is True
    assert result["path"] == str(path)
    assert len(result["locales"]) == 1
    row = result["locales"][0]
    assert row["locale"] == "en-US"
    assert set(row["fields"]) == set(FIELD_NAMES)
    assert row["fields"]["name"] == "My App"
    assert row["fields"]["subtitle"] == "A subtitle"
    assert row["fields"]["keywords"] == "app,tool"
    assert row["fields"]["description"] == "A description"
    assert row["fields"]["supportUrl"] == "https://example.com/support"
    assert row["fields"]["marketingUrl"] == "https://example.com"
    assert row["fields"]["privacyPolicyUrl"] == "https://example.com/privacy"


def test_validate_listing_over_limit_and_bad_url(tmp_path: Path):
    path = _write_listing_csv(
        tmp_path / "over.csv",
        [
            {
                "locale": "en-US",
                "name": "N" * 31,
                "subtitle": "S" * 31,
                "keywords": "k" * 101,
                "description": "d" * 4001,
                "supportUrl": "example.com/support",
                "marketingUrl": "ftp://example.com",
                "privacyPolicyUrl": "not-a-url",
            }
        ],
    )
    result = validate_listing(path)
    assert result["ok"] is True
    assert result["exists"] is True
    errors = [issue for issue in result["issues"] if issue["level"] == "error"]
    fields = {issue["field"] for issue in errors}
    assert "name" in fields
    assert "subtitle" in fields
    assert "keywords" in fields
    assert "description" in fields
    assert "supportUrl" in fields
    assert "marketingUrl" in fields
    assert "privacyPolicyUrl" in fields
    assert result["error_count"] >= 7
    for issue in errors:
        assert issue["locale"] == "en-US"
        assert issue["message"]


def test_validate_listing_partial_locale_empty_required_fields_warn(tmp_path: Path):
    path = _write_listing_csv(
        tmp_path / "partial.csv",
        [
            {
                "locale": "zh-Hans",
                "subtitle": "只有副标题",
                "marketingUrl": "https://example.com",
            }
        ],
    )
    result = validate_listing(path)
    assert result["ok"] is True
    warnings = [issue for issue in result["issues"] if issue["level"] == "warning"]
    fields = {issue["field"] for issue in warnings}
    assert fields == {"name", "keywords", "description", "supportUrl", "privacyPolicyUrl"}
    assert result["warning_count"] == 5
    assert all(issue["locale"] == "zh-Hans" for issue in warnings)
    assert not any(issue["field"] == "marketingUrl" for issue in result["issues"])


def test_validate_iap_invalid_type_uses_validate_snapshot(tmp_path: Path):
    path = tmp_path / "iap.json"
    path.write_text(
        json.dumps(
            {
                "items": [{"productId": "com.app.bad", "inAppPurchaseType": "NONSENSE"}],
                "subscriptionGroups": [],
            }
        ),
        encoding="utf-8",
    )
    result = validate_iap(path)
    assert result["ok"] is True
    assert result["exists"] is True
    errors = [issue for issue in result["issues"] if issue["level"] == "error"]
    assert any("unknown type" in issue["message"] for issue in errors)
    assert any(issue["path"] == "items[0].inAppPurchaseType" for issue in errors)
    assert result["error_count"] >= 1


def test_iap_snapshot_lists_locale_codes_only(tmp_path: Path):
    secret_desc = "SECRET_IAP_DESCRIPTION_SHOULD_NOT_LEAK"
    review_note = "SECRET_REVIEW_NOTE_SHOULD_NOT_LEAK"
    path = tmp_path / "iap.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "productId": "com.app.coins",
                        "name": "Coins",
                        "inAppPurchaseType": "CONSUMABLE",
                        "localizations": {
                            "en-US": {"name": "Coins", "description": secret_desc},
                            "zh-Hans": {"name": "金币", "description": secret_desc},
                        },
                        "review": {"screenshot": "./shot.png", "note": review_note},
                    }
                ],
                "subscriptionGroups": [
                    {
                        "referenceName": "Premium",
                        "subscriptions": [
                            {
                                "productId": "com.app.premium.month",
                                "groupLevel": 1,
                                "subscriptionPeriod": "ONE_MONTH",
                                "localizations": {
                                    "zh-Hans": {
                                        "name": "月度",
                                        "description": secret_desc,
                                    }
                                },
                                "review": {"note": review_note},
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = iap_snapshot(path)
    assert result["ok"] is True
    assert result["exists"] is True
    assert result["item_count"] == 1
    assert result["group_count"] == 1
    item = result["items"][0]
    assert item == {
        "productId": "com.app.coins",
        "name": "Coins",
        "inAppPurchaseType": "CONSUMABLE",
        "locales": ["en-US", "zh-Hans"],
    }
    group = result["subscriptionGroups"][0]
    assert group["referenceName"] == "Premium"
    assert group["subscriptions"][0]["productId"] == "com.app.premium.month"
    assert group["subscriptions"][0]["groupLevel"] == 1
    assert group["subscriptions"][0]["subscriptionPeriod"] == "ONE_MONTH"
    assert group["subscriptions"][0]["locales"] == ["zh-Hans"]
    blob = json.dumps(result, ensure_ascii=False)
    assert secret_desc not in blob
    assert review_note not in blob
    assert "localizations" not in blob
    assert "description" not in blob


def test_count_listing_fields_cjk_name_length(tmp_path: Path):
    path = _write_listing_csv(
        tmp_path / "cjk.csv",
        [
            {"locale": "zh-Hans", "name": "测" * 30},
            {"locale": "ja", "name": "测" * 31},
        ],
    )
    result = count_listing_fields(path)
    assert result["ok"] is True
    by_locale = {row["locale"]: row["fields"] for row in result["locales"]}

    name_30 = by_locale["zh-Hans"]["name"]
    assert name_30["length"] == 30
    assert name_30["limit"] == 30
    assert name_30["target"] == 27
    assert name_30["over_limit"] is False
    assert name_30["over_target"] is True

    name_31 = by_locale["ja"]["name"]
    assert name_31["length"] == 31
    assert name_31["over_limit"] is True

    desc = by_locale["zh-Hans"]["description"]
    assert desc["limit"] == 4000
    assert "target" not in desc
    assert "over_target" not in desc


def test_inspect_screenshots_unknown_pixel_size(tmp_path: Path):
    root = tmp_path / "screenshots"
    locale_dir = root / "en-US"
    locale_dir.mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(locale_dir / "foo.png")

    result = inspect_screenshots(root)
    assert result["ok"] is True
    assert result["exists"] is True
    assert result["path"] == str(root)
    assert len(result["locales"]) == 1
    row = result["locales"][0]
    assert row["locale"] == "en-US"
    assert row["types"]["UNKNOWN"] == 1
    assert row["unknown_files"] == ["foo.png"]
    assert row["file_count"] == 1


def test_iap_invalid_json_is_redacted_error(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{not-json issuer_id=ABCDEF12-aaaa-bbbb-cccc-ddddeeeeffff", encoding="utf-8")
    snap = iap_snapshot(path)
    assert snap["ok"] is False
    assert "error" in snap
    assert "ABCDEF12-aaaa-bbbb-cccc-ddddeeeeffff" not in snap["error"]

    issues = validate_iap(path)
    assert issues["ok"] is False
    assert "error" in issues
