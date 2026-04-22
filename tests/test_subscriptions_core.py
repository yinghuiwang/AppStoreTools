"""End-to-end subscription core tests using FakeAPI."""
from __future__ import annotations


from asc.commands.subscriptions import _upload_subscriptions_core


def _min_sub(tmp_png, product_id="com.a.monthly", level=1):
    return {
        "productId": product_id,
        "name": product_id,
        "subscriptionPeriod": "ONE_MONTH",
        "groupLevel": level,
        "localizations": {"en-US": {"name": "x", "description": "y"}},
        "price": {"baseTerritory": "USA", "baseAmount": "9.99"},
        "review": {"screenshot": str(tmp_png), "note": "n"},
    }


def _seed_price_point(api, sub_id, territory, amount, pp_id):
    api.price_points.setdefault(sub_id, []).append(
        {"id": pp_id, "territory": territory, "customerPrice": amount}
    )


def test_creates_new_group(fake_api, tmp_png):
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [_min_sub(tmp_png)],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    failed = _upload_subscriptions_core(fake_api, "app1", groups, update_existing=False, dry_run=False)
    assert failed == 0

    assert len(fake_api.groups) == 1
    gid = next(iter(fake_api.groups))
    assert fake_api.groups[gid]["referenceName"] == "Pro"
    assert "en-US" in fake_api.group_locs[gid]


def test_skips_existing_group_by_default(fake_api, tmp_png):
    fake_api.create_subscription_group("app1", "Pro")
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [_min_sub(tmp_png)],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=False, dry_run=False)

    creates = [c for c in fake_api.calls if c[0] == "create_subscription_group"]
    assert len(creates) == 1  # only the seed


def test_updates_existing_group_when_flag_set(fake_api, tmp_png):
    fake_api.create_subscription_group("app1", "Pro")
    gid = next(iter(fake_api.groups))
    fake_api.create_subscription_group_localization(gid, "en-US", "Old")

    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro New"}},
        "subscriptions": [_min_sub(tmp_png)],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=True, dry_run=False)

    updates = [c for c in fake_api.calls if c[0] == "update_subscription_group_localization"]
    assert updates, "expected group loc update"


def test_creates_new_subscription(fake_api, tmp_png):
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [_min_sub(tmp_png)],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    failed = _upload_subscriptions_core(
        fake_api, "app1", groups, update_existing=False, dry_run=False
    )
    assert failed == 0
    assert len(fake_api.subs) == 1
    sub = next(iter(fake_api.subs.values()))
    assert sub["attrs"]["productId"] == "com.a.monthly"
    assert sub["attrs"]["reviewNote"] == "n"


def test_skips_existing_subscription_by_default(fake_api, tmp_png):
    g = fake_api.create_subscription_group("app1", "Pro")
    gid = g["data"]["id"]
    fake_api.create_subscription(gid, {
        "productId": "com.a.monthly",
        "name": "old",
        "subscriptionPeriod": "ONE_MONTH",
        "groupLevel": 1,
    })

    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [_min_sub(tmp_png)],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=False, dry_run=False)

    creates = [c for c in fake_api.calls if c[0] == "create_subscription"]
    assert len(creates) == 1  # only the seed


def test_creates_subscription_localizations(fake_api, tmp_png):
    sub = _min_sub(tmp_png)
    sub["localizations"] = {
        "en-US": {"name": "Pro Monthly", "description": "All features."},
        "zh-Hans": {"name": "高级", "description": "全部"},
    }
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [sub],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=False, dry_run=False)

    sub_id = next(iter(fake_api.subs))
    assert set(fake_api.sub_locs[sub_id].keys()) == {"en-US", "zh-Hans"}
    assert fake_api.sub_locs[sub_id]["zh-Hans"]["description"] == "全部"


def test_creates_price_when_missing(fake_api, tmp_png):
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [_min_sub(tmp_png)],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=False, dry_run=False)
    sub_id = next(iter(fake_api.subs))
    assert len(fake_api.prices[sub_id]) == 1
    assert fake_api.prices[sub_id][0]["pricePointId"] == "pp_usd_999"


def test_price_point_not_found_raises(fake_api, tmp_png):
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [_min_sub(tmp_png)],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: None

    real_list = fake_api.list_subscription_price_points
    def list_pp(sub_id, territory):
        return [
            {"id": "a", "attributes": {"customerPrice": "8.99"}},
            {"id": "b", "attributes": {"customerPrice": "9.99"}},
            {"id": "c", "attributes": {"customerPrice": "10.99"}},
        ]
    fake_api.list_subscription_price_points = list_pp

    failed = _upload_subscriptions_core(
        fake_api, "app1", groups, update_existing=False, dry_run=False
    )
    assert failed == 1  # price point lookup failure counts as subscription failure


def test_price_skipped_when_exists_and_no_update(fake_api, tmp_png):
    g = fake_api.create_subscription_group("app1", "Pro")
    gid = g["data"]["id"]
    s = fake_api.create_subscription(gid, {
        "productId": "com.a.monthly", "name": "x",
        "subscriptionPeriod": "ONE_MONTH", "groupLevel": 1,
    })
    sid = s["data"]["id"]
    fake_api.create_subscription_price(sid, "old_pp", "USA")

    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [_min_sub(tmp_png)],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=False, dry_run=False)
    assert len(fake_api.prices[sid]) == 1
    assert fake_api.prices[sid][0]["pricePointId"] == "old_pp"


def test_creates_free_trial_intro_offer(fake_api, tmp_png):
    sub = _min_sub(tmp_png)
    sub["introductoryOffer"] = {
        "offerMode": "FREE_TRIAL",
        "duration": "ONE_WEEK",
        "numberOfPeriods": 1,
    }
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [sub],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=False, dry_run=False)
    sub_id = next(iter(fake_api.subs))
    assert len(fake_api.intro_offers[sub_id]) == 1
    assert fake_api.intro_offers[sub_id][0]["offerMode"] == "FREE_TRIAL"


def test_replaces_intro_offer_when_update_flag(fake_api, tmp_png):
    g = fake_api.create_subscription_group("app1", "Pro")
    gid = g["data"]["id"]
    s = fake_api.create_subscription(gid, {
        "productId": "com.a.monthly", "name": "x",
        "subscriptionPeriod": "ONE_MONTH", "groupLevel": 1,
    })
    sid = s["data"]["id"]
    fake_api.create_subscription_intro_offer(sid, {"offerMode": "FREE_TRIAL"})

    sub = _min_sub(tmp_png)
    sub["introductoryOffer"] = {
        "offerMode": "FREE_TRIAL", "duration": "ONE_MONTH", "numberOfPeriods": 1,
    }
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [sub],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=True, dry_run=False)

    deletes = [c for c in fake_api.calls if c[0] == "delete_subscription_intro_offer"]
    assert len(deletes) == 1
    assert len(fake_api.intro_offers[sid]) == 1
    assert fake_api.intro_offers[sid][0]["duration"] == "ONE_MONTH"


def _promo(code="WB50", ref="Win-back 50", amount="4.99"):
    return {
        "referenceName": ref,
        "offerCode": code,
        "offerMode": "PAY_AS_YOU_GO",
        "duration": "ONE_MONTH",
        "numberOfPeriods": 3,
        "baseTerritory": "USA",
        "baseAmount": amount,
    }


def test_creates_promo_offer(fake_api, tmp_png):
    sub = _min_sub(tmp_png)
    sub["promotionalOffers"] = [_promo()]
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [sub],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_promo"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=False, dry_run=False)
    sid = next(iter(fake_api.subs))
    assert len(fake_api.promo_offers[sid]) == 1
    assert fake_api.promo_offers[sid][0]["offerCode"] == "WB50"


def test_existing_promo_offer_skipped_by_default(fake_api, tmp_png):
    g = fake_api.create_subscription_group("app1", "Pro")
    gid = g["data"]["id"]
    s = fake_api.create_subscription(gid, {
        "productId": "com.a.monthly", "name": "x",
        "subscriptionPeriod": "ONE_MONTH", "groupLevel": 1,
    })
    sid = s["data"]["id"]
    fake_api.create_subscription_promo_offer(
        sid, {"referenceName": "Old", "offerCode": "WB50"}, "pp_old"
    )

    sub = _min_sub(tmp_png)
    sub["promotionalOffers"] = [_promo()]
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [sub],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_promo"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=False, dry_run=False)
    assert len(fake_api.promo_offers[sid]) == 1  # unchanged


def test_uploads_review_screenshot(fake_api, tmp_png):
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [_min_sub(tmp_png)],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=False, dry_run=False)
    sid = next(iter(fake_api.subs))
    assert len(fake_api.review_shots[sid]) == 1
    assert fake_api.review_shots[sid][0]["uploaded"] is True


def test_replaces_review_screenshot_on_update(fake_api, tmp_png):
    g = fake_api.create_subscription_group("app1", "Pro")
    gid = g["data"]["id"]
    s = fake_api.create_subscription(gid, {
        "productId": "com.a.monthly", "name": "x",
        "subscriptionPeriod": "ONE_MONTH", "groupLevel": 1,
    })
    sid = s["data"]["id"]
    fake_api.create_subscription_review_screenshot_reservation(sid, "old.png", 123)

    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [_min_sub(tmp_png)],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp_usd_999"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=True, dry_run=False)
    deletes = [c for c in fake_api.calls if c[0] == "delete_subscription_review_screenshot"]
    assert len(deletes) == 1
    assert len(fake_api.review_shots[sid]) == 1
    assert fake_api.review_shots[sid][0]["fileName"] != "old.png"


def test_dry_run_performs_no_writes(fake_api, tmp_png):
    sub = _min_sub(tmp_png)
    sub["introductoryOffer"] = {"offerMode": "FREE_TRIAL", "duration": "ONE_WEEK", "numberOfPeriods": 1}
    sub["promotionalOffers"] = [_promo()]
    groups = [{
        "referenceName": "Pro",
        "localizations": {"en-US": {"name": "Pro"}},
        "subscriptions": [sub],
    }]
    fake_api.find_subscription_price_point = lambda s, t, a: "pp"

    _upload_subscriptions_core(fake_api, "app1", groups,
                               update_existing=False, dry_run=True)

    write_prefixes = (
        "create_", "update_", "delete_", "commit_", "upload_",
    )
    writes = [c for c in fake_api.calls if c[0].startswith(write_prefixes)]
    assert writes == [], f"dry-run should not write; got {writes}"
