"""Tests for IAP product-table inference heuristics."""
from __future__ import annotations

from asc.iap.infer import apply_group_levels, infer_products


def test_year_and_week_product_ids_are_subscriptions():
    raw = (
        "productId\tname\tprice\n"
        "com.app.year.49.99\tYear 49.99\t49.99\n"
        "com.app.week.7.99\tWeek 7.99\t7.99\n"
    )
    result = infer_products(raw)
    kinds = {p["productId"]: p["kind"] for p in result["products"]}
    assert kinds["com.app.year.49.99"] == "subscription"
    assert kinds["com.app.week.7.99"] == "subscription"
    periods = {p["productId"]: p["subscriptionPeriod"] for p in result["products"]}
    assert periods["com.app.year.49.99"] == "ONE_YEAR"
    assert periods["com.app.week.7.99"] == "ONE_WEEK"
    for group in result["snapshot"]["subscriptionGroups"]:
        for sub in group["subscriptions"]:
            assert "groupLevel" not in sub


def test_coins_without_period_are_consumable():
    raw = (
        "productId,name,price,category\n"
        "com.app.coins.4.99,Credits 4.99,4.99,积分权益\n"
    )
    result = infer_products(raw)
    product = result["products"][0]
    assert product["kind"] == "iap"
    assert product["inAppPurchaseType"] == "CONSUMABLE"
    assert result["snapshot"]["items"][0]["productId"] == "com.app.coins.4.99"


def test_unknown_kind_needs_confirmation():
    raw = "productId,name\ncom.app.mystery.sku,Mystery Addon\n"
    result = infer_products(raw)
    assert result["products"][0]["kind"] == "unknown"
    assert result["needsConfirmation"]
    assert result["needsConfirmation"][0]["productId"] == "com.app.mystery.sku"


def test_json_products_and_group_level_apply():
    raw = """
    {"products": [
      {"productId": "com.app.premium.year.49.99", "name": "Year", "price": 49.99, "displayName": "Pro"},
      {"productId": "com.app.premium.week.7.99", "name": "Week", "price": 7.99, "displayName": "Pro"}
    ]}
    """
    result = infer_products(raw)
    assert result["groupLevelHelp"]
    assert result["groupLevelBatches"]
    snapshot = apply_group_levels(
        result["snapshot"],
        {
            "com.app.premium.year.49.99": 1,
            "com.app.premium.week.7.99": 2,
        },
    )
    levels = {
        sub["productId"]: sub["groupLevel"]
        for group in snapshot["subscriptionGroups"]
        for sub in group["subscriptions"]
    }
    assert levels["com.app.premium.year.49.99"] == 1
    assert levels["com.app.premium.week.7.99"] == 2


def test_points_month_is_subscription_not_consumable():
    raw = "productId,name\ncom.app.credits_points_month_4.99,Credits monthly\n"
    result = infer_products(raw)
    assert result["products"][0]["kind"] == "subscription"
