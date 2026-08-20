"""Tests for IAP local-vs-ASC publish plan."""
from __future__ import annotations

from asc.iap.diff import build_plan, coarse_status
from asc.iap.models import ACTION_CREATE, ACTION_SKIP, ACTION_UPDATE, STATUS_CHANGED, STATUS_EQUAL, STATUS_LOCAL_ONLY


LOCAL = {
    "items": [
        {
            "productId": "com.app.coins",
            "name": "Coins",
            "inAppPurchaseType": "CONSUMABLE",
            "price": {"baseTerritory": "USA", "baseAmount": "0.99"},
            "localizations": {"en-US": {"name": "Coins", "description": "Get coins."}},
        },
        {
            "productId": "com.app.new",
            "name": "New item",
            "inAppPurchaseType": "NON_CONSUMABLE",
            "localizations": {"en-US": {"name": "New item", "description": "One time."}},
        },
    ],
    "subscriptionGroups": [
        {
            "referenceName": "Premium",
            "subscriptions": [
                {
                    "productId": "com.app.premium.month",
                    "name": "Monthly",
                    "subscriptionPeriod": "ONE_MONTH",
                    "groupLevel": 1,
                    "price": {"baseTerritory": "USA", "baseAmount": "9.99"},
                    "localizations": {
                        "en-US": {"name": "Monthly", "description": "Full access."}
                    },
                }
            ],
        }
    ],
}

REMOTE_EQUAL = {
    "items": [LOCAL["items"][0]],
    "subscriptionGroups": LOCAL["subscriptionGroups"],
}


def test_create_only_skips_existing_and_creates_local_only():
    plan = build_plan(LOCAL, REMOTE_EQUAL, update_existing=False)
    by_id = {row.product_id: row for row in plan.items}
    assert by_id["com.app.coins"].action == ACTION_SKIP
    assert by_id["com.app.coins"].status == STATUS_EQUAL
    assert by_id["com.app.new"].action == ACTION_CREATE
    assert by_id["com.app.new"].status == STATUS_LOCAL_ONLY
    assert by_id["com.app.premium.month"].action == ACTION_SKIP


def test_update_existing_marks_changed_for_update():
    remote = {
        "items": [
            {
                "productId": "com.app.coins",
                "name": "Coins",
                "inAppPurchaseType": "CONSUMABLE",
                "price": {"baseTerritory": "USA", "baseAmount": "1.99"},
                "localizations": {"en-US": {"name": "Coins", "description": "Get coins."}},
            }
        ],
        "subscriptionGroups": LOCAL["subscriptionGroups"],
    }
    plan = build_plan(LOCAL, remote, update_existing=True)
    by_id = {row.product_id: row for row in plan.items}
    assert by_id["com.app.coins"].action == ACTION_UPDATE
    assert by_id["com.app.coins"].status == STATUS_CHANGED
    assert any(f.field == "price" for f in by_id["com.app.coins"].fields)
    assert by_id["com.app.premium.month"].action == ACTION_SKIP
    assert by_id["com.app.new"].action == ACTION_CREATE


def test_coarse_status_local_only():
    local = {"productId": "x", "kind": "iap", "type": "CONSUMABLE", "name": "X"}
    assert coarse_status(local, None) == STATUS_LOCAL_ONLY


def test_plan_when_remote_unavailable_still_lists_local():
    plan = build_plan(LOCAL, None, update_existing=False, remote_ok=False, error="network")
    assert plan.remote_ok is False
    assert plan.error == "network"
    assert all(row.status == "unchecked" for row in plan.items)
    assert {row.action for row in plan.items} == {ACTION_CREATE}
