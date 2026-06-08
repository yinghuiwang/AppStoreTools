"""Subscription bulk upload command."""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional, Tuple


VALID_PERIODS = {
    "ONE_WEEK", "ONE_MONTH", "TWO_MONTHS", "THREE_MONTHS",
    "SIX_MONTHS", "ONE_YEAR",
}
VALID_INTRO_MODES = {"FREE_TRIAL", "PAY_AS_YOU_GO", "PAY_UP_FRONT"}
VALID_PROMO_MODES = {"PAY_AS_YOU_GO", "PAY_UP_FRONT"}
SCREENSHOT_WARNING_BYTES = 5 * 1024 * 1024
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
    has_price_point = _non_empty_str(price.get("pricePointId"))
    has_base_lookup = (
        _non_empty_str(price.get("baseTerritory"))
        and _non_empty_str(price.get("baseAmount"))
    )
    _require(
        has_price_point or has_base_lookup,
        f"{tag}.price requires either pricePointId or baseTerritory + baseAmount",
    )
    if price.get("baseTerritory") is not None:
        _require(
            _valid_territory_id(price.get("baseTerritory")),
            f"{tag}.price.baseTerritory must be a 3-letter territory id such as USA or CHN",
        )
    if price.get("territory") is not None:
        _require(
            _valid_territory_id(price.get("territory")),
            f"{tag}.price.territory must be a 3-letter territory id such as USA or CHN",
        )
    review = sub.get("review")
    _require(isinstance(review, dict), f"{tag}.review required (object)")
    shot = review.get("screenshot")
    _require(_non_empty_str(shot), f"{tag}.review.screenshot path required")
    shot_path = Path(shot)
    _require(shot_path.exists() and shot_path.is_file(),
             f"{tag}.review.screenshot file not found: {shot}")
    _require(shot_path.suffix.lower() in SCREENSHOT_EXTS,
             f"{tag}.review.screenshot must be .png/.jpg/.jpeg, got {shot_path.suffix}")
    size = shot_path.stat().st_size
    if size > SCREENSHOT_WARNING_BYTES:
        print(
            f"⚠️  {tag}.review.screenshot exceeds 5MB ({size} bytes); "
            "continuing and leaving final validation to App Store Connect"
        )
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
    _require(_non_empty_str(offer.get("baseTerritory")),
             f"{tag}.baseTerritory required")
    _require(
        _valid_territory_id(offer.get("baseTerritory")),
        f"{tag}.baseTerritory must be a 3-letter territory id such as USA or CHN",
    )
    _require(offer.get("duration") in VALID_PERIODS,
             f"{tag}.duration must be one of {sorted(VALID_PERIODS)}")
    _require(isinstance(offer.get("numberOfPeriods"), int) and offer["numberOfPeriods"] >= 1,
             f"{tag}.numberOfPeriods must be positive int")
    if mode != "FREE_TRIAL":
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


def _valid_territory_id(value: Any) -> bool:
    return isinstance(value, str) and len(value.strip()) == 3 and value.strip().isalpha()


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

    total_subs = sum(len(g.get("subscriptions", [])) for g in groups)
    total_items = len(groups) + total_subs
    completed = 0

    for group_cfg in groups:
        ref_name = group_cfg["referenceName"]
        print(f"\n── 订阅组: {ref_name} ──")
        group_id, group_status = _sync_group(
            api, app_id, group_cfg, update_existing, dry_run
        )
        stats[f"groups_{group_status}"] += 1
        completed += 1
        pct = int(completed / total_items * 100) if total_items else 0
        print(f"[PROGRESS:{pct}:订阅组 {completed}/{total_items}]")
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

            completed += 1
            pct = int(completed / total_items * 100) if total_items else 0
            print(f"[PROGRESS:{pct}:订阅 {completed}/{total_items}]")

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
) -> Tuple[Optional[str], str]:
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

    _sync_subscription_availability(
        api, sub_id, sub_cfg, update_existing, dry_run
    )
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
) -> Tuple[Optional[str], str]:
    pid = sub_cfg["productId"]
    existing_subs = api.list_subscriptions(group_id)
    by_pid = {s["attributes"]["productId"]: s for s in existing_subs}

    attrs = {
        "productId": pid,
        "name": sub_cfg["name"],
        "subscriptionPeriod": sub_cfg["subscriptionPeriod"],
        "groupLevel": sub_cfg["groupLevel"],
        "familySharable": bool(sub_cfg.get("familySharable", False)),
    }
    review_note = str(sub_cfg.get("review", {}).get("note", "")).strip()
    if review_note:
        attrs["reviewNote"] = review_note

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


def _sync_subscription_availability(api, sub_id, sub_cfg, update_existing, dry_run):
    available_all = bool(sub_cfg.get("availableInAllTerritories", True))
    territory_ids = sub_cfg.get("availableTerritories") or sub_cfg.get("territories")

    if territory_ids is not None:
        if not isinstance(territory_ids, list):
            print("    ⚠️  销售地区: availableTerritories/territories 必须是列表，跳过")
            return
        territory_ids = [str(t).strip() for t in territory_ids if str(t).strip()]
    elif available_all:
        if dry_run:
            print("    [预览] 销售地区: 全部国家/地区")
            return
        territory_ids = [t["id"] for t in api.list_territories()]
    else:
        territory_ids = []

    if not territory_ids:
        print("    ⚠️  销售地区: 无可用地区配置，跳过")
        return

    if dry_run:
        print(f"    [预览] 销售地区: {len(territory_ids)} 个地区")
        return

    try:
        existing = api.get_subscription_availability(sub_id)
    except Exception:
        existing = None

    if existing and not update_existing:
        print("    销售地区: 已存在，跳过")
        return
    if existing and update_existing:
        print("    销售地区: 已存在（Apple API 不支持直接替换），跳过")
        return

    try:
        api.create_subscription_availability(
            sub_id,
            available_in_new_territories=available_all,
            territory_ids=territory_ids,
        )
        print(f"    销售地区: 已设置 {len(territory_ids)} 个地区 ✅")
    except Exception as e:
        print(f"    ⚠️  销售地区设置跳过: {e}")


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
    territory = price_cfg.get("territory") or price_cfg.get("baseTerritory")
    amount = price_cfg.get("baseAmount")
    pp_id = str(price_cfg.get("pricePointId") or "").strip()
    apply_equalized = bool(price_cfg.get("applyEqualizedPrices", True))
    max_workers = _positive_int(price_cfg.get("maxWorkers"), default=6)

    if not pp_id:
        pp_id = api.find_subscription_price_point(sub_id, territory, amount)
    if not pp_id:
        candidates = api.list_subscription_price_points(sub_id, territory)
        nearest = _nearest_price_points(candidates, amount, limit=3)
        hint = ", ".join(f"{c}" for c in nearest) or "无候选"
        raise Exception(
            f"未找到 Price Point: {territory} {amount}. "
            f"territory 必须使用 Apple 三字母 ID（如 USA/CHN），最近候选: {hint}"
        )

    if dry_run:
        if amount:
            print(f"    [预览] 价格: 基准 {territory} {amount} → Price Point {pp_id}")
        else:
            print(f"    [预览] 价格: Price Point {pp_id}")
        return

    existing = api.list_subscription_prices(sub_id)
    if existing and not update_existing:
        print(f"    价格: 已存在 {len(existing)} 条，跳过")
        return
    if existing and update_existing:
        for p in existing:
            api.delete_subscription_price(p["id"])
        print(f"    价格: 已删除 {len(existing)} 条旧价格")

    price_points = [(territory, pp_id)]
    if apply_equalized:
        try:
            equalizations = api.list_subscription_price_point_equalizations(pp_id, sub_id)
            price_points = _price_points_by_territory(equalizations)
            if not any(t == territory for t, _ in price_points):
                price_points.insert(0, (territory, pp_id))
        except Exception as e:
            print(f"    ⚠️  等价价格点查询失败，仅设置基准地区: {e}")

    created, failed = _create_subscription_prices(
        api, sub_id, price_points, price_cfg, max_workers
    )

    if amount:
        print(
            f"    价格: 基准 {territory} {amount} → 已设置 {created} 个地区"
            f"{f' / {failed} 失败' if failed else ''} ✅"
        )
    else:
        print(
            f"    价格: Price Point {pp_id} → 已设置 {created} 个地区"
            f"{f' / {failed} 失败' if failed else ''} ✅"
        )


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _create_subscription_prices(api, sub_id, price_points, price_cfg, max_workers):
    mode = str(price_cfg.get("creationMode", "inlinePatch")).strip()
    if (
        mode != "post"
        and len(price_points) > 1
        and hasattr(api, "update_subscription_prices_inline")
    ):
        created, failed, fallback_points = _create_subscription_prices_inline(
            api, sub_id, price_points, price_cfg
        )
        if not fallback_points:
            return created, failed
        fallback_created, fallback_failed = _create_subscription_prices_post(
            api, sub_id, fallback_points, price_cfg, max_workers
        )
        return created + fallback_created, failed + fallback_failed

    return _create_subscription_prices_post(api, sub_id, price_points, price_cfg, max_workers)


def _create_subscription_prices_inline(api, sub_id, price_points, price_cfg):
    batch_size = min(_positive_int(price_cfg.get("inlineBatchSize"), default=50), 50)
    created = 0
    failed = 0
    batches = list(_chunks(price_points, batch_size))
    print(f"    价格: inline PATCH 创建 {len(price_points)} 个地区（batch={batch_size}）")

    for idx, batch in enumerate(batches):
        try:
            api.update_subscription_prices_inline(
                sub_id,
                batch,
                start_date=price_cfg.get("startDate"),
                preserve_current_price=price_cfg.get("preserveCurrentPrice"),
            )
            created += len(batch)
        except Exception as e:
            failed += len(batch)
            remaining = batch[:]
            for later in batches[idx + 1:]:
                remaining.extend(later)
            print(f"    ⚠️  inline 价格创建失败，回退并发 POST: {e}")
            return created, failed, remaining

    return created, failed, []


def _chunks(items, size):
    for idx in range(0, len(items), size):
        yield items[idx:idx + size]


def _create_subscription_prices_post(api, sub_id, price_points, price_cfg, max_workers):
    if len(price_points) <= 1 or max_workers <= 1:
        return _create_subscription_prices_sequential(api, sub_id, price_points, price_cfg)

    created = 0
    failed = 0
    workers = min(max_workers, len(price_points))
    print(f"    价格: 并发创建 {len(price_points)} 个地区（workers={workers}）")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                api.create_subscription_price,
                sub_id,
                target_pp_id,
                target_territory,
                start_date=price_cfg.get("startDate"),
                preserve_current_price=price_cfg.get("preserveCurrentPrice"),
            ): target_territory
            for target_territory, target_pp_id in price_points
        }
        for future in as_completed(future_map):
            target_territory = future_map[future]
            try:
                future.result()
                created += 1
            except Exception as e:
                failed += 1
                print(f"    ⚠️  价格创建跳过 {target_territory}: {e}")

    return created, failed


def _create_subscription_prices_sequential(api, sub_id, price_points, price_cfg):
    created = 0
    failed = 0
    for target_territory, target_pp_id in price_points:
        try:
            api.create_subscription_price(
                sub_id,
                target_pp_id,
                target_territory,
                start_date=price_cfg.get("startDate"),
                preserve_current_price=price_cfg.get("preserveCurrentPrice"),
            )
            created += 1
        except Exception as e:
            failed += 1
            print(f"    ⚠️  价格创建跳过 {target_territory}: {e}")
    return created, failed


def _price_points_by_territory(price_points: list) -> list[tuple[str, str]]:
    result = []
    seen = set()
    for pp in price_points:
        territory_id = (
            pp.get("relationships", {})
            .get("territory", {})
            .get("data", {})
            .get("id")
        )
        if not territory_id:
            territory_id = pp.get("territory")
        pp_id = pp.get("id")
        if territory_id and pp_id and territory_id not in seen:
            result.append((territory_id, pp_id))
            seen.add(territory_id)
    return result


def _nearest_price_points(candidates: list, target: str, limit: int) -> list[str]:
    try:
        t = Decimal(str(target))
    except (InvalidOperation, ValueError):
        return [c.get("attributes", {}).get("customerPrice", "?") for c in candidates[:limit]]
    scored = []
    for c in candidates:
        price_str = c.get("attributes", {}).get("customerPrice", "")
        try:
            scored.append((abs(Decimal(str(price_str)) - t), price_str))
        except (InvalidOperation, ValueError):
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
