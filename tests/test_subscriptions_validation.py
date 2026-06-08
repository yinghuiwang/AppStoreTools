"""Phase 0 pre-flight validation tests."""
from __future__ import annotations

import pytest

from asc.commands.subscriptions import validate_subscription_config, ValidationError


def _valid_group(tmp_png):
    return {
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [
            {
                "productId": "com.a.monthly",
                "name": "Pro Monthly",
                "subscriptionPeriod": "ONE_MONTH",
                "groupLevel": 1,
                "localizations": {
                    "en-US": {"name": "Pro Monthly", "description": "All features."}
                },
                "price": {"baseTerritory": "USA", "baseAmount": "9.99"},
                "review": {"screenshot": str(tmp_png), "note": "monthly sub"},
            }
        ],
    }


def test_valid_config_passes(tmp_png):
    validate_subscription_config([_valid_group(tmp_png)])


def test_missing_reference_name(tmp_png):
    g = _valid_group(tmp_png)
    del g["referenceName"]
    with pytest.raises(ValidationError, match="referenceName"):
        validate_subscription_config([g])


def test_missing_product_id(tmp_png):
    g = _valid_group(tmp_png)
    del g["subscriptions"][0]["productId"]
    with pytest.raises(ValidationError, match="productId"):
        validate_subscription_config([g])


def test_invalid_subscription_period(tmp_png):
    g = _valid_group(tmp_png)
    g["subscriptions"][0]["subscriptionPeriod"] = "WEIRD"
    with pytest.raises(ValidationError, match="subscriptionPeriod"):
        validate_subscription_config([g])


def test_missing_localization_description(tmp_png):
    g = _valid_group(tmp_png)
    g["subscriptions"][0]["localizations"]["en-US"].pop("description")
    with pytest.raises(ValidationError, match="description"):
        validate_subscription_config([g])


def test_missing_price(tmp_png):
    g = _valid_group(tmp_png)
    del g["subscriptions"][0]["price"]
    with pytest.raises(ValidationError, match="price"):
        validate_subscription_config([g])


def test_price_accepts_explicit_price_point_id_without_base_amount(tmp_png):
    g = _valid_group(tmp_png)
    g["subscriptions"][0]["price"] = {"territory": "USA", "pricePointId": "pp_123"}
    validate_subscription_config([g])


def test_price_rejects_two_letter_territory(tmp_png):
    g = _valid_group(tmp_png)
    g["subscriptions"][0]["price"] = {"baseTerritory": "US", "baseAmount": "9.99"}
    with pytest.raises(ValidationError, match="3-letter territory"):
        validate_subscription_config([g])


def test_review_note_is_optional(tmp_png):
    g = _valid_group(tmp_png)
    del g["subscriptions"][0]["review"]["note"]
    validate_subscription_config([g])


def test_blank_review_note_is_ignored(tmp_png):
    g = _valid_group(tmp_png)
    g["subscriptions"][0]["review"]["note"] = "  "
    validate_subscription_config([g])


def test_missing_review_screenshot_file(tmp_png):
    g = _valid_group(tmp_png)
    g["subscriptions"][0]["review"]["screenshot"] = "/does/not/exist.png"
    with pytest.raises(ValidationError, match="screenshot"):
        validate_subscription_config([g])


def test_duplicate_group_level(tmp_png):
    g = _valid_group(tmp_png)
    g["subscriptions"].append(dict(g["subscriptions"][0], productId="com.a.yearly"))
    with pytest.raises(ValidationError, match="groupLevel"):
        validate_subscription_config([g])


def test_duplicate_promo_offer_code(tmp_png):
    g = _valid_group(tmp_png)
    g["subscriptions"][0]["promotionalOffers"] = [
        {"referenceName": "A", "offerCode": "X", "offerMode": "PAY_AS_YOU_GO",
         "duration": "ONE_MONTH", "numberOfPeriods": 1,
         "baseTerritory": "USA", "baseAmount": "4.99"},
        {"referenceName": "B", "offerCode": "X", "offerMode": "PAY_AS_YOU_GO",
         "duration": "ONE_MONTH", "numberOfPeriods": 1,
         "baseTerritory": "USA", "baseAmount": "3.99"},
    ]
    with pytest.raises(ValidationError, match="offerCode"):
        validate_subscription_config([g])


def test_free_trial_intro_offer_requires_territory(tmp_png):
    g = _valid_group(tmp_png)
    g["subscriptions"][0]["introductoryOffer"] = {
        "offerMode": "FREE_TRIAL",
        "duration": "ONE_WEEK",
        "numberOfPeriods": 1,
    }
    with pytest.raises(ValidationError, match="baseTerritory"):
        validate_subscription_config([g])


def test_free_trial_intro_offer_accepts_territory_without_amount(tmp_png):
    g = _valid_group(tmp_png)
    g["subscriptions"][0]["introductoryOffer"] = {
        "offerMode": "FREE_TRIAL",
        "baseTerritory": "USA",
        "duration": "ONE_WEEK",
        "numberOfPeriods": 1,
    }
    validate_subscription_config([g])


def test_large_screenshot_warns_but_passes(tmp_path, capsys):
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (6 * 1024 * 1024))
    g = {
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [
            {
                "productId": "com.a.monthly",
                "name": "x",
                "subscriptionPeriod": "ONE_MONTH",
                "groupLevel": 1,
                "localizations": {"en-US": {"name": "x", "description": "y"}},
                "price": {"baseTerritory": "USA", "baseAmount": "9.99"},
                "review": {"screenshot": str(big), "note": "n"},
            }
        ],
    }
    validate_subscription_config([g])
    out = capsys.readouterr().out
    assert "exceeds 5MB" in out
