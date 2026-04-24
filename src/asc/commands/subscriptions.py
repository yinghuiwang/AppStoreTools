"""Subscription bulk upload command."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


VALID_PERIODS = {
    "ONE_WEEK", "ONE_MONTH", "TWO_MONTHS", "THREE_MONTHS",
    "SIX_MONTHS", "ONE_YEAR",
}
VALID_INTRO_MODES = {"FREE_TRIAL", "PAY_AS_YOU_GO", "PAY_UP_FRONT"}
VALID_PROMO_MODES = {"PAY_AS_YOU_GO", "PAY_UP_FRONT"}
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
SCREENSHOT_EXTS = {".png", ".jpg", ".jpeg"}


class ValidationError(Exception):
    """Raised when subscription JSON config fails pre-flight validation."""


def _require(cond, msg):
    if not cond:
        raise ValidationError(msg)


def _non_empty_str(v):
    return isinstance(v, str) and v.strip() != ""


def validate_subscription_config(groups: list[dict]) -> None:
    _require(isinstance(groups, list), "subscriptionGroups must be a list")
    for gi, group in enumerate(groups):
        gtag = f"subscriptionGroups[{gi}]"
        _require(isinstance(group, dict), f"{gtag} must be an object")
        _require(_non_empty_str(group.get("referenceName")),
                 f"{gtag}.referenceName is required (non-empty string)")
        subs = group.get("subscriptions", [])
        _require(isinstance(subs, list) and subs,
                 f"{gtag}.subscriptions must be a non-empty list")
        levels_seen = set()
        for si, sub in enumerate(subs):
            stag = f"{gtag}.subscriptions[{si}]"
            _validate_subscription(sub, stag)
            lvl = sub.get("groupLevel")
            _require(lvl not in levels_seen,
                     f"{stag}.groupLevel={lvl} duplicates another in the group")
            levels_seen.add(lvl)


def _validate_subscription(sub: dict, tag: str) -> None:
    _require(isinstance(sub, dict), f"{tag} must be an object")
    _require(_non_empty_str(sub.get("productId")), f"{tag}.productId required")
    _require(_non_empty_str(sub.get("name")), f"{tag}.name required")
    period = sub.get("subscriptionPeriod")
    _require(period in VALID_PERIODS,
             f"{tag}.subscriptionPeriod must be one of {sorted(VALID_PERIODS)}, got {period!r}")
    _require(isinstance(sub.get("groupLevel"), int) and sub["groupLevel"] >= 1,
             f"{tag}.groupLevel must be a positive int")
    locs = sub.get("localizations")
    _require(isinstance(locs, dict) and locs,
             f"{tag}.localizations required (at least 1 locale)")
    for locale, loc in locs.items():
        ltag = f"{tag}.localizations[{locale}]"
        _require(isinstance(loc, dict), f"{ltag} must be an object")
        _require(_non_empty_str(loc.get("name")), f"{ltag}.name required")
        _require(_non_empty_str(loc.get("description")), f"{ltag}.description required")
    price = sub.get("price")
    _require(isinstance(price, dict), f"{tag}.price required (object)")
    _require(_non_empty_str(price.get("baseTerritory")),
             f"{tag}.price.baseTerritory required")
    _require(_non_empty_str(price.get("baseAmount")),
             f"{tag}.price.baseAmount required (string)")
    review = sub.get("review")
    _require(isinstance(review, dict), f"{tag}.review required (object)")
    _require(_non_empty_str(review.get("note")),
             f"{tag}.review.note required (non-empty string)")
    shot = review.get("screenshot")
    _require(_non_empty_str(shot), f"{tag}.review.screenshot path required")
    shot_path = Path(shot)
    _require(shot_path.exists() and shot_path.is_file(),
             f"{tag}.review.screenshot file not found: {shot}")
    _require(shot_path.suffix.lower() in SCREENSHOT_EXTS,
             f"{tag}.review.screenshot must be .png/.jpg/.jpeg, got {shot_path.suffix}")
    size = shot_path.stat().st_size
    _require(size <= MAX_SCREENSHOT_BYTES,
             f"{tag}.review.screenshot exceeds 5MB ({size} bytes)")
    intro = sub.get("introductoryOffer")
    if intro is not None:
        _validate_intro_offer(intro, f"{tag}.introductoryOffer")
    promos = sub.get("promotionalOffers", [])
    if promos:
        _require(isinstance(promos, list), f"{tag}.promotionalOffers must be a list")
        codes_seen = set()
        for pi, promo in enumerate(promos):
            ptag = f"{tag}.promotionalOffers[{pi}]"
            _validate_promo_offer(promo, ptag)
            code = promo["offerCode"]
            _require(code not in codes_seen,
                     f"{ptag}.offerCode={code!r} duplicates another on this subscription")
            codes_seen.add(code)


def _validate_intro_offer(offer: dict, tag: str) -> None:
    _require(isinstance(offer, dict), f"{tag} must be an object")
    mode = offer.get("offerMode")
    _require(mode in VALID_INTRO_MODES,
             f"{tag}.offerMode must be one of {sorted(VALID_INTRO_MODES)}")
    _require(offer.get("duration") in VALID_PERIODS,
             f"{tag}.duration must be one of {sorted(VALID_PERIODS)}")
    _require(isinstance(offer.get("numberOfPeriods"), int) and offer["numberOfPeriods"] >= 1,
             f"{tag}.numberOfPeriods must be positive int")
    if mode != "FREE_TRIAL":
        _require(_non_empty_str(offer.get("baseTerritory")),
                 f"{tag}.baseTerritory required for non-FREE_TRIAL")
        _require(_non_empty_str(offer.get("baseAmount")),
                 f"{tag}.baseAmount required for non-FREE_TRIAL")


def _validate_promo_offer(offer: dict, tag: str) -> None:
    _require(isinstance(offer, dict), f"{tag} must be an object")
    _require(_non_empty_str(offer.get("referenceName")), f"{tag}.referenceName required")
    _require(_non_empty_str(offer.get("offerCode")), f"{tag}.offerCode required")
    _require(offer.get("offerMode") in VALID_PROMO_MODES,
             f"{tag}.offerMode must be one of {sorted(VALID_PROMO_MODES)}")
    _require(offer.get("duration") in VALID_PERIODS,
             f"{tag}.duration must be one of {sorted(VALID_PERIODS)}")
    _require(isinstance(offer.get("numberOfPeriods"), int) and offer["numberOfPeriods"] >= 1,
             f"{tag}.numberOfPeriods must be positive int")
    _require(_non_empty_str(offer.get("baseTerritory")), f"{tag}.baseTerritory required")
    _require(_non_empty_str(offer.get("baseAmount")), f"{tag}.baseAmount required")


# ---------- Orchestrator ----------


def _upload_subscriptions_core(
    api, app_id: str, groups: list[dict], update_existing: bool, dry_run: bool
) -> int:
    validate_subscription_config(groups)

    print("\n" + "=" * 60)
    print("🔁  上传订阅")
    print("=" * 60)

    stats = {
        "groups_created": 0, "groups_updated": 0, "groups_skipped": 0,
        "subs_created": 0, "subs_updated": 0, "subs_skipped": 0,
        "subs_failed": 0,
    }
    failures: list[tuple[str, str]] = []

    for group_cfg in groups:
        ref_name = group_cfg["referenceName"]
        print(f"\n── 订阅组: {ref_name} ──")
        group_id, group_status = _sync_group(
            api, app_id, group_cfg, update_existing, dry_run
        )
        stats[f"groups_{group_status}"] += 1
        if group_id is None:
            group_id = "DRY_RUN_GROUP"

        for sub_cfg in group_cfg["subscriptions"]:
            pid = sub_cfg["productId"]
            try:
                status = _sync_subscription(
                    api, group_id, sub_cfg, update_existing, dry_run
                )
                stats[f"subs_{status}"] += 1
            except Exception as e:
                stats["subs_failed"] += 1
                failures.append((pid, str(e)))
                print(f"  ❌ {pid} 失败: {e}")

    _print_summary(stats, failures)
    return stats["subs_failed"]


def _print_summary(stats: dict, failures: list) -> None:
    print("\n" + "=" * 60)
    print("📊  订阅上传汇总")
    print(f"    订阅组: {stats['groups_created']} 创建 / "
          f"{stats['groups_updated']} 更新 / {stats['groups_skipped']} 跳过")
    print(f"    订阅:   {stats['subs_created']} 创建 / "
          f"{stats['subs_updated']} 更新 / {stats['subs_skipped']} 跳过 / "
          f"{stats['subs_failed']} 失败")
    print("=" * 60)
    if failures:
        print("\n失败明细:")
        for pid, err in failures:
            print(f"  • {pid}: {err}")


# ---------- Phase 1: Groups ----------


def _sync_group(
    api, app_id: str, group_cfg: dict, update_existing: bool, dry_run: bool
) -> tuple[str | None, str]:
    ref_name = group_cfg["referenceName"]
    existing_groups = api.list_subscription_groups(app_id)
    existing_by_ref = {
        g["attributes"]["referenceName"]: g for g in existing_groups
    }

    if ref_name in existing_by_ref:
        group_id = existing_by_ref[ref_name]["id"]
        if not update_existing:
            print(f"    已存在 (ID: {group_id})，跳过")
            _sync_group_localizations(
                api, group_id, group_cfg.get("localizations", {}),
                update_existing=False, dry_run=dry_run,
            )
            return group_id, "skipped"
        print(f"    已存在 (ID: {group_id})，更新本地化")
        _sync_group_localizations(
            api, group_id, group_cfg.get("localizations", {}),
            update_existing=True, dry_run=dry_run,
        )
        return group_id, "updated"

    if dry_run:
        print(f"    [预览] 将创建订阅组: {ref_name}")
        return None, "created"

    print(f"    不存在，创建中...")
    resp = api.create_subscription_group(app_id, ref_name)
    group_id = resp["data"]["id"]
    print(f"    ✅ 已创建，ID: {group_id}")
    _sync_group_localizations(
        api, group_id, group_cfg.get("localizations", {}),
        update_existing=False, dry_run=False,
    )
    return group_id, "created"


def _sync_group_localizations(
    api, group_id: str, loc_cfg: dict, update_existing: bool, dry_run: bool
) -> None:
    if not loc_cfg:
        return
    if dry_run and group_id == "DRY_RUN_GROUP":
        print(f"    [预览] 将同步组本地化: {list(loc_cfg.keys())}")
        return

    existing = api.list_subscription_group_localizations(group_id)
    by_locale = {loc["attributes"]["locale"]: loc for loc in existing}

    for locale, data in loc_cfg.items():
        name = str(data.get("name", "")).strip()
        custom_app_name = data.get("customAppName")
        if not name:
            continue
        if locale in by_locale:
            if update_existing and not dry_run:
                attrs = {"name": name}
                if custom_app_name:
                    attrs["customAppName"] = custom_app_name
                api.update_subscription_group_localization(
                    by_locale[locale]["id"], attrs
                )
                print(f"    本地化 {locale}: 更新 ✅")
            else:
                print(f"    本地化 {locale}: 已存在，跳过")
        else:
            if dry_run:
                print(f"    [预览] 本地化 {locale}: 将创建")
            else:
                api.create_subscription_group_localization(
                    group_id, locale, name, custom_app_name
                )
                print(f"    本地化 {locale}: 创建 ✅")


# ---------- Phase 2-7: Subscription (placeholder — filled in later tasks) ----------


def _sync_subscription(
    api, group_id: str, sub_cfg: dict, update_existing: bool, dry_run: bool
) -> str:
    pid = sub_cfg["productId"]
    print(f"\n  ── 订阅: {pid} ──")

    sub_id, status = _sync_subscription_main(
        api, group_id, sub_cfg, update_existing, dry_run
    )

    if sub_id is None:
        return status

    _sync_subscription_localizations(
        api, sub_id, sub_cfg["localizations"], update_existing, dry_run
    )
    _sync_review_screenshot(
        api, sub_id, sub_cfg["review"]["screenshot"],
        update_existing, dry_run,
    )
    _sync_subscription_price(
        api, sub_id, sub_cfg["price"], update_existing, dry_run
    )
    _sync_intro_offer(
        api, sub_id, sub_cfg.get("introductoryOffer"),
        update_existing, dry_run,
    )
    _sync_promo_offers(
        api, sub_id, sub_cfg.get("promotionalOffers", []),
        update_existing, dry_run,
    )
    return status


def _sync_subscription_main(
    api, group_id: str, sub_cfg: dict, update_existing: bool, dry_run: bool
) -> tuple[str | None, str]:
    pid = sub_cfg["productId"]
    existing_subs = api.list_subscriptions(group_id)
    by_pid = {s["attributes"]["productId"]: s for s in existing_subs}

    attrs = {
        "productId": pid,
        "name": sub_cfg["name"],
        "subscriptionPeriod": sub_cfg["subscriptionPeriod"],
        "groupLevel": sub_cfg["groupLevel"],
        "familySharable": bool(sub_cfg.get("familySharable", False)),
        "reviewNote": sub_cfg["review"]["note"],
    }

    if pid in by_pid:
        sub_id = by_pid[pid]["id"]
        if update_existing:
            if dry_run:
                print(f"    [预览] 已存在 (ID: {sub_id})，将更新")
            else:
                update_attrs = {k: v for k, v in attrs.items() if k != "productId"}
                api.update_subscription(sub_id, update_attrs)
                print(f"    已存在 (ID: {sub_id})，已更新 ✅")
            return sub_id, "updated"
        print(f"    已存在 (ID: {sub_id})，跳过")
        return sub_id, "skipped"

    if dry_run:
        print(f"    [预览] 将创建订阅: {pid}")
        return None, "created"

    resp = api.create_subscription(group_id, attrs)
    sub_id = resp["data"]["id"]
    print(f"    已创建，ID: {sub_id} ✅")
    return sub_id, "created"


def _sync_subscription_localizations(api, sub_id, loc_cfg, update_existing, dry_run):
    if not loc_cfg:
        return
    if dry_run:
        print(f"    [预览] 将同步订阅本地化: {list(loc_cfg.keys())}")
        return

    existing = api.list_subscription_localizations(sub_id)
    by_locale = {loc["attributes"]["locale"]: loc for loc in existing}

    for locale, data in loc_cfg.items():
        name = str(data.get("name", "")).strip()
        desc = str(data.get("description", "")).strip()
        if locale in by_locale:
            if update_existing:
                api.update_subscription_localization(
                    by_locale[locale]["id"], {"name": name, "description": desc}
                )
                print(f"    本地化 {locale}: 更新 ✅")
            else:
                print(f"    本地化 {locale}: 已存在，跳过")
        else:
            api.create_subscription_localization(sub_id, locale, name, desc)
            print(f"    本地化 {locale}: 创建 ✅")


def _sync_subscription_price(api, sub_id, price_cfg, update_existing, dry_run):
    territory = price_cfg["baseTerritory"]
    amount = price_cfg["baseAmount"]

    pp_id = api.find_subscription_price_point(sub_id, territory, amount)
    if pp_id is None:
        candidates = api.list_subscription_price_points(sub_id, territory)
        nearest = _nearest_price_points(candidates, amount, limit=3)
        hint = ", ".join(f"{c}" for c in nearest) or "无候选"
        raise Exception(
            f"未找到 Price Point: {territory} {amount}. 最近候选: {hint}"
        )

    if dry_run:
        print(f"    [预览] 价格: 基准 {territory} {amount} → Price Point {pp_id}")
        return

    existing = api.list_subscription_prices(sub_id)
    if existing and not update_existing:
        print(f"    价格: 已存在 {len(existing)} 条，跳过")
        return
    if existing and update_existing:
        for p in existing:
            api.delete_subscription_price(p["id"])
        print(f"    价格: 已删除 {len(existing)} 条旧价格")

    try:
        api.create_subscription_price(sub_id, pp_id, territory)
        print(f"    价格: 基准 {territory} {amount} → Price Point {pp_id} ✅")
    except Exception as e:
        # ASC subscription price creation requires the subscription to be in a complete state
        # (all metadata, screenshot, and territory availability set). If creation fails, skip gracefully.
        print(f"    ⚠️  价格创建跳过（可能需要在 ASC UI 手动设置）: {e}")


def _nearest_price_points(candidates: list, target: str, limit: int) -> list[str]:
    try:
        t = float(target)
    except ValueError:
        return [c.get("attributes", {}).get("customerPrice", "?") for c in candidates[:limit]]
    scored = []
    for c in candidates:
        price_str = c.get("attributes", {}).get("customerPrice", "")
        try:
            scored.append((abs(float(price_str) - t), price_str))
        except ValueError:
            continue
    scored.sort()
    return [p for _, p in scored[:limit]]


def _sync_intro_offer(api, sub_id, offer_cfg, update_existing, dry_run):
    if offer_cfg is None:
        return

    existing = api.list_subscription_intro_offers(sub_id)
    if existing and not update_existing:
        print("    入门优惠: 已存在，跳过")
        return

    pp_id = None
    territory = offer_cfg.get("baseTerritory")
    if offer_cfg["offerMode"] != "FREE_TRIAL":
        amount = offer_cfg["baseAmount"]
        pp_id = api.find_subscription_price_point(sub_id, territory, amount)
        if pp_id is None:
            raise Exception(
                f"入门优惠 Price Point 未命中: {territory} {amount}"
            )

    if dry_run:
        print(f"    [预览] 入门优惠: {offer_cfg['offerMode']} / {offer_cfg['duration']}")
        return

    if existing:
        for o in existing:
            api.delete_subscription_intro_offer(o["id"])

    attrs = {
        "offerMode": offer_cfg["offerMode"],
        "duration": offer_cfg["duration"],
        "numberOfPeriods": offer_cfg["numberOfPeriods"],
    }
    api.create_subscription_intro_offer(sub_id, attrs, pp_id, territory)
    print(f"    入门优惠: {attrs['offerMode']} / {attrs['duration']} ✅")


def _sync_promo_offers(api, sub_id, offers_cfg, update_existing, dry_run):
    if not offers_cfg:
        return

    existing = api.list_subscription_promo_offers(sub_id)
    by_code = {o["attributes"].get("offerCode"): o for o in existing}

    for cfg in offers_cfg:
        code = cfg["offerCode"]
        territory = cfg["baseTerritory"]
        amount = cfg["baseAmount"]

        pp_id = api.find_subscription_price_point(sub_id, territory, amount)
        if pp_id is None:
            raise Exception(
                f"促销优惠 {code} Price Point 未命中: {territory} {amount}"
            )

        attrs = {
            "referenceName": cfg["referenceName"],
            "offerCode": code,
            "offerMode": cfg["offerMode"],
            "duration": cfg["duration"],
            "numberOfPeriods": cfg["numberOfPeriods"],
        }

        if code in by_code:
            if update_existing:
                if dry_run:
                    print(f"    [预览] 促销优惠 {code}: 将重建")
                else:
                    api.delete_subscription_promo_offer(by_code[code]["id"])
                    api.create_subscription_promo_offer(sub_id, attrs, pp_id)
                    print(f"    促销优惠 {code}: 重建 ✅")
            else:
                print(f"    促销优惠 {code}: 已存在，跳过")
        else:
            if dry_run:
                print(f"    [预览] 促销优惠 {code}: 将创建")
            else:
                api.create_subscription_promo_offer(sub_id, attrs, pp_id)
                print(f"    促销优惠 {code}: 创建 ✅")


def _sync_review_screenshot(api, sub_id, shot_path, update_existing, dry_run):
    path = Path(shot_path)

    existing = api.list_subscription_review_screenshots(sub_id)
    if existing and not update_existing:
        print(f"    审核截图: 已存在，跳过")
        return

    if dry_run:
        print(f"    [预览] 审核截图: 将上传 {path.name}")
        return

    for s in existing:
        api.delete_subscription_review_screenshot(s["id"])

    file_bytes = path.read_bytes()
    reservation = api.create_subscription_review_screenshot_reservation(
        sub_id, path.name, len(file_bytes)
    )
    shot_id = reservation["data"]["id"]
    upload_ops = reservation["data"].get("attributes", {}).get("uploadOperations", [])
    api.upload_subscription_review_screenshot(upload_ops, file_bytes)
    md5 = hashlib.md5(file_bytes).hexdigest()
    api.commit_subscription_review_screenshot(shot_id, md5)
    print(f"    审核截图: {path.name} 上传 ✅")
