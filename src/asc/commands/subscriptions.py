"""Subscription bulk upload command."""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys
from typing import Any, Callable, Optional, Tuple

from asc.progress import ProcessCanceled
from asc.reporting import TaskReporter, make_cli_reporter


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
        for si, sub in enumerate(subs):
            stag = f"{gtag}.subscriptions[{si}]"
            _validate_subscription(sub, stag)


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
            "continuing and leaving final validation to App Store Connect",
            file=sys.stderr,
            flush=True,
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


def _finish_subscriptions(reporter: TaskReporter, finalize: bool) -> None:
    if finalize:
        reporter.done("订阅上传完成")
    else:
        reporter.log("订阅上传完成")


def _upload_subscriptions_core(
    api,
    app_id: str,
    groups: list[dict],
    update_existing: bool,
    dry_run: bool,
    reporter: TaskReporter | None = None,
    verbose: bool = False,
    manage_phases: bool = True,
    finalize: bool = True,
    cancel_event=None,
) -> int:
    if reporter is None:
        reporter = make_cli_reporter(verbose=verbose)

    validate_subscription_config(groups)

    if cancel_event is not None:
        api.cancel_event = cancel_event

    if manage_phases:
        reporter.set_phases([("subscriptions", 100, "订阅")])
    reporter.phase("subscriptions")

    reporter.log("=" * 60)
    reporter.log("🔁  上传订阅")
    reporter.log("=" * 60)

    stats = {
        "groups_created": 0, "groups_updated": 0, "groups_skipped": 0,
        "subs_created": 0, "subs_updated": 0, "subs_skipped": 0,
        "subs_failed": 0,
    }
    failures: list[tuple[str, str]] = []
    log = reporter.log

    total_subs = sum(len(g.get("subscriptions", [])) for g in groups)
    if total_subs == 0:
        reporter.progress(1, 1, msg="订阅 0/0")
        _print_summary(stats, failures, log=log)
        _finish_subscriptions(reporter, finalize)
        return 0

    completed = 0
    existing_groups = api.list_subscription_groups(app_id)
    for group_cfg in groups:
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCanceled("subscription upload canceled")
        ref_name = group_cfg["referenceName"]
        reporter.log(f"── 订阅组: {ref_name} ──")
        group_id, group_status = _sync_group(
            api,
            app_id,
            group_cfg,
            update_existing,
            dry_run,
            log=log,
            existing_groups=existing_groups,
        )
        stats[f"groups_{group_status}"] += 1
        if group_id is None:
            group_id = "DRY_RUN_GROUP"

        existing_subs = (
            []
            if group_id == "DRY_RUN_GROUP"
            else api.list_subscriptions(group_id)
        )

        for sub_cfg in group_cfg["subscriptions"]:
            if cancel_event is not None and cancel_event.is_set():
                raise ProcessCanceled("subscription upload canceled")
            pid = sub_cfg["productId"]
            try:
                status = _sync_subscription(
                    api,
                    group_id,
                    sub_cfg,
                    update_existing,
                    dry_run,
                    log=log,
                    cancel_event=cancel_event,
                    existing_subs=existing_subs,
                )
                stats[f"subs_{status}"] += 1
            except ProcessCanceled:
                raise
            except Exception as e:
                stats["subs_failed"] += 1
                failures.append((pid, str(e)))
                reporter.log(f"  ❌ {pid} 失败: {e}")

            completed += 1
            reporter.progress(
                completed, total_subs, msg=f"订阅 {completed}/{total_subs}"
            )

    _print_summary(stats, failures, log=log)
    _finish_subscriptions(reporter, finalize)
    return stats["subs_failed"]


def _print_summary(stats: dict, failures: list, log: Callable[..., None] = print) -> None:
    log("=" * 60)
    log("📊  订阅上传汇总")
    log(f"    订阅组: {stats['groups_created']} 创建 / "
        f"{stats['groups_updated']} 更新 / {stats['groups_skipped']} 跳过")
    log(f"    订阅:   {stats['subs_created']} 创建 / "
        f"{stats['subs_updated']} 更新 / {stats['subs_skipped']} 跳过 / "
        f"{stats['subs_failed']} 失败")
    log("=" * 60)
    if failures:
        log("失败明细:")
        for pid, err in failures:
            log(f"  • {pid}: {err}")


# ---------- Phase 1: Groups ----------


def _sync_group(
    api, app_id: str, group_cfg: dict, update_existing: bool, dry_run: bool,
    log: Callable[..., None] = print,
    existing_groups: Optional[list] = None,
) -> Tuple[Optional[str], str]:
    ref_name = group_cfg["referenceName"]
    if existing_groups is None:
        existing_groups = api.list_subscription_groups(app_id)
    existing_by_ref = {
        g["attributes"]["referenceName"]: g for g in existing_groups
    }

    if ref_name in existing_by_ref:
        group_id = existing_by_ref[ref_name]["id"]
        if not update_existing:
            log(f"    已存在 (ID: {group_id})，跳过")
            _sync_group_localizations(
                api, group_id, group_cfg.get("localizations", {}),
                update_existing=False, dry_run=dry_run, log=log,
            )
            return group_id, "skipped"
        log(f"    已存在 (ID: {group_id})，更新本地化")
        _sync_group_localizations(
            api, group_id, group_cfg.get("localizations", {}),
            update_existing=True, dry_run=dry_run, log=log,
        )
        return group_id, "updated"

    if dry_run:
        log(f"    [预览] 将创建订阅组: {ref_name}")
        return None, "created"

    log(f"    不存在，创建中...")
    resp = api.create_subscription_group(app_id, ref_name)
    group_id = resp["data"]["id"]
    existing_groups.append(
        {"id": group_id, "attributes": {"referenceName": ref_name}}
    )
    log(f"    ✅ 已创建，ID: {group_id}")
    _sync_group_localizations(
        api, group_id, group_cfg.get("localizations", {}),
        update_existing=False, dry_run=False, log=log,
    )
    return group_id, "created"


def _sync_group_localizations(
    api, group_id: str, loc_cfg: dict, update_existing: bool, dry_run: bool,
    log: Callable[..., None] = print,
) -> None:
    if not loc_cfg:
        return
    if dry_run and group_id == "DRY_RUN_GROUP":
        log(f"    [预览] 将同步组本地化: {list(loc_cfg.keys())}")
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
                log(f"    本地化 {locale}: 更新 ✅")
            else:
                log(f"    本地化 {locale}: 已存在，跳过")
        else:
            if dry_run:
                log(f"    [预览] 本地化 {locale}: 将创建")
            else:
                api.create_subscription_group_localization(
                    group_id, locale, name, custom_app_name
                )
                log(f"    本地化 {locale}: 创建 ✅")


# ---------- Phase 2-7: Subscription (placeholder — filled in later tasks) ----------


def _sync_subscription(
    api, group_id: str, sub_cfg: dict, update_existing: bool, dry_run: bool,
    log: Callable[..., None] = print,
    cancel_event=None,
    existing_subs: Optional[list] = None,
) -> str:
    pid = sub_cfg["productId"]
    log(f"\n  ── 订阅: {pid} ──")

    sub_id, status = _sync_subscription_main(
        api,
        group_id,
        sub_cfg,
        update_existing,
        dry_run,
        log=log,
        existing_subs=existing_subs,
    )

    if sub_id is None:
        return status

    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCanceled("subscription upload canceled")

    _sync_subscription_availability(
        api, sub_id, sub_cfg, update_existing, dry_run, log=log
    )
    _sync_subscription_localizations(
        api, sub_id, sub_cfg["localizations"], update_existing, dry_run, log=log
    )
    _sync_review_screenshot(
        api, sub_id, sub_cfg["review"]["screenshot"],
        update_existing, dry_run, log=log,
    )
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCanceled("subscription upload canceled")
    _sync_subscription_price(
        api,
        sub_id,
        sub_cfg["price"],
        update_existing,
        dry_run,
        log=log,
        cancel_event=cancel_event,
    )
    _sync_intro_offer(
        api, sub_id, sub_cfg.get("introductoryOffer"),
        update_existing, dry_run, log=log,
    )
    _sync_promo_offers(
        api, sub_id, sub_cfg.get("promotionalOffers", []),
        update_existing, dry_run, log=log,
    )
    return status


def _sync_subscription_main(
    api, group_id: str, sub_cfg: dict, update_existing: bool, dry_run: bool,
    log: Callable[..., None] = print,
    existing_subs: Optional[list] = None,
) -> Tuple[Optional[str], str]:
    pid = sub_cfg["productId"]
    if existing_subs is None:
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
                log(f"    [预览] 已存在 (ID: {sub_id})，将更新")
            else:
                update_attrs = {k: v for k, v in attrs.items() if k != "productId"}
                api.update_subscription(sub_id, update_attrs)
                log(f"    已存在 (ID: {sub_id})，已更新 ✅")
            return sub_id, "updated"
        log(f"    已存在 (ID: {sub_id})，跳过")
        return sub_id, "skipped"

    if dry_run:
        log(f"    [预览] 将创建订阅: {pid}")
        return None, "created"

    resp = api.create_subscription(group_id, attrs)
    sub_id = resp["data"]["id"]
    existing_subs.append({"id": sub_id, "attributes": dict(attrs)})
    log(f"    已创建，ID: {sub_id} ✅")
    return sub_id, "created"


def _sync_subscription_availability(api, sub_id, sub_cfg, update_existing, dry_run, log=print):
    available_all = bool(sub_cfg.get("availableInAllTerritories", True))
    territory_ids = sub_cfg.get("availableTerritories") or sub_cfg.get("territories")

    if territory_ids is not None:
        if not isinstance(territory_ids, list):
            log("    ⚠️  销售地区: availableTerritories/territories 必须是列表，跳过")
            return
        territory_ids = [str(t).strip() for t in territory_ids if str(t).strip()]
    elif available_all:
        if dry_run:
            log("    [预览] 销售地区: 全部国家/地区")
            return
        territory_ids = [t["id"] for t in api.list_territories()]
    else:
        territory_ids = []

    if not territory_ids:
        log("    ⚠️  销售地区: 无可用地区配置，跳过")
        return

    if dry_run:
        log(f"    [预览] 销售地区: {len(territory_ids)} 个地区")
        return

    try:
        existing = api.get_subscription_availability(sub_id)
    except Exception:
        existing = None

    if existing and not update_existing:
        log("    销售地区: 已存在，跳过")
        return
    if existing and update_existing:
        log("    销售地区: 已存在（Apple API 不支持直接替换），跳过")
        return

    try:
        api.create_subscription_availability(
            sub_id,
            available_in_new_territories=available_all,
            territory_ids=territory_ids,
        )
        log(f"    销售地区: 已设置 {len(territory_ids)} 个地区 ✅")
    except Exception as e:
        log(f"    ⚠️  销售地区设置跳过: {e}")


def _sync_subscription_localizations(api, sub_id, loc_cfg, update_existing, dry_run, log=print):
    if not loc_cfg:
        return
    if dry_run:
        log(f"    [预览] 将同步订阅本地化: {list(loc_cfg.keys())}")
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
                log(f"    本地化 {locale}: 更新 ✅")
            else:
                log(f"    本地化 {locale}: 已存在，跳过")
        else:
            api.create_subscription_localization(sub_id, locale, name, desc)
            log(f"    本地化 {locale}: 创建 ✅")


def _sync_subscription_price(
    api, sub_id, price_cfg, update_existing, dry_run, log=print, cancel_event=None
):
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
            log(f"    [预览] 价格: 基准 {territory} {amount} → Price Point {pp_id}")
        else:
            log(f"    [预览] 价格: Price Point {pp_id}")
        return

    existing = api.list_subscription_prices(sub_id)
    if existing and not update_existing:
        log(f"    价格: 已存在 {len(existing)} 条，跳过")
        return

    price_points = [(territory, pp_id)]
    if apply_equalized:
        try:
            equalizations = api.list_subscription_price_point_equalizations(pp_id, sub_id)
            price_points = _price_points_by_territory(equalizations)
            if not any(t == territory for t, _ in price_points):
                price_points.insert(0, (territory, pp_id))
        except Exception as e:
            log(f"    ⚠️  等价价格点查询失败，仅设置基准地区: {e}")

    matched_territories: set[str] = set()
    if existing and update_existing:
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCanceled("subscription upload canceled")
        to_delete, matched_territories = _diff_subscription_prices_for_update(
            existing, price_points
        )
        if to_delete:
            _delete_subscription_prices(
                api,
                to_delete,
                max_workers,
                cancel_event=cancel_event,
            )
            log(f"    价格: 已删除 {len(to_delete)} 条旧价格")
        elif matched_territories:
            log(f"    价格: {len(matched_territories)} 个地区已匹配，跳过删除")

    price_points_to_create = [
        (t, target_pp) for t, target_pp in price_points if t not in matched_territories
    ]
    if not price_points_to_create:
        if amount:
            log(f"    价格: 基准 {territory} {amount} → 已匹配全部地区 ✅")
        else:
            log(f"    价格: Price Point {pp_id} → 已匹配全部地区 ✅")
        return

    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCanceled("subscription upload canceled")

    created, failed = _create_subscription_prices(
        api,
        sub_id,
        price_points_to_create,
        price_cfg,
        max_workers,
        log=log,
        cancel_event=cancel_event,
    )

    if amount:
        log(
            f"    价格: 基准 {territory} {amount} → 已设置 {created} 个地区"
            f"{f' / {failed} 失败' if failed else ''} ✅"
        )
    else:
        log(
            f"    价格: Price Point {pp_id} → 已设置 {created} 个地区"
            f"{f' / {failed} 失败' if failed else ''} ✅"
        )


def _parse_existing_subscription_price(price: dict) -> tuple[Optional[str], Optional[str]]:
    """Extract (territory_id, price_point_id) from ASC or flat FakeAPI shapes."""
    relationships = price.get("relationships") or {}
    territory = (
        (relationships.get("territory") or {}).get("data") or {}
    ).get("id") or price.get("territory")
    price_point_id = (
        (relationships.get("subscriptionPricePoint") or {}).get("data") or {}
    ).get("id") or price.get("pricePointId")
    return territory, price_point_id


def _diff_subscription_prices_for_update(
    existing: list, target_price_points: list[tuple[str, str]]
) -> tuple[list, set[str]]:
    """Return (prices_to_delete, matched_territories).

    Falls back to deleting all existing prices when any item lacks territory /
    price-point linkage (cannot safely compute a differential).
    """
    target_by_territory = {t: pp for t, pp in target_price_points}
    parsed: list[tuple[dict, str, str]] = []
    for price in existing:
        territory, price_point_id = _parse_existing_subscription_price(price)
        if not territory or not price_point_id:
            return list(existing), set()
        parsed.append((price, territory, price_point_id))

    to_delete: list = []
    matched_territories: set[str] = set()
    for price, territory, price_point_id in parsed:
        if target_by_territory.get(territory) == price_point_id:
            matched_territories.add(territory)
        else:
            to_delete.append(price)
    return to_delete, matched_territories


def _delete_subscription_prices(
    api, prices, max_workers, cancel_event=None
):
    if not prices:
        return

    if len(prices) <= 1 or max_workers <= 1:
        for price in prices:
            if cancel_event is not None and cancel_event.is_set():
                raise ProcessCanceled("subscription upload canceled")
            api.delete_subscription_price(price["id"])
        return

    workers = min(max_workers, len(prices))

    def _delete_one(price_id: str):
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCanceled("subscription upload canceled")
        api.delete_subscription_price(price_id)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_delete_one, price["id"]): price["id"] for price in prices
        }
        try:
            for future in as_completed(future_map):
                if cancel_event is not None and cancel_event.is_set():
                    for pending in future_map:
                        pending.cancel()
                    raise ProcessCanceled("subscription upload canceled")
                future.result()
        except ProcessCanceled:
            for pending in future_map:
                pending.cancel()
            raise


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _create_subscription_prices(
    api, sub_id, price_points, price_cfg, max_workers, log=print, cancel_event=None
):
    mode = str(price_cfg.get("creationMode", "inlinePatch")).strip()
    if (
        mode != "post"
        and len(price_points) > 1
        and hasattr(api, "update_subscription_prices_inline")
    ):
        created, failed, fallback_points = _create_subscription_prices_inline(
            api, sub_id, price_points, price_cfg, log=log, cancel_event=cancel_event
        )
        if not fallback_points:
            return created, failed
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCanceled("subscription upload canceled")
        fallback_created, fallback_failed = _create_subscription_prices_post(
            api,
            sub_id,
            fallback_points,
            price_cfg,
            max_workers,
            log=log,
            cancel_event=cancel_event,
        )
        return created + fallback_created, failed + fallback_failed

    return _create_subscription_prices_post(
        api,
        sub_id,
        price_points,
        price_cfg,
        max_workers,
        log=log,
        cancel_event=cancel_event,
    )


def _create_subscription_prices_inline(
    api, sub_id, price_points, price_cfg, log=print, cancel_event=None
):
    batch_size = min(_positive_int(price_cfg.get("inlineBatchSize"), default=50), 50)
    created = 0
    failed = 0
    batches = list(_chunks(price_points, batch_size))
    log(f"    价格: inline PATCH 创建 {len(price_points)} 个地区（batch={batch_size}）")

    for idx, batch in enumerate(batches):
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCanceled("subscription upload canceled")
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
            log(f"    ⚠️  inline 价格创建失败，回退并发 POST: {e}")
            return created, failed, remaining

    return created, failed, []


def _chunks(items, size):
    for idx in range(0, len(items), size):
        yield items[idx:idx + size]


def _create_subscription_prices_post(
    api, sub_id, price_points, price_cfg, max_workers, log=print, cancel_event=None
):
    if len(price_points) <= 1 or max_workers <= 1:
        return _create_subscription_prices_sequential(
            api, sub_id, price_points, price_cfg, log=log, cancel_event=cancel_event
        )

    created = 0
    failed = 0
    workers = min(max_workers, len(price_points))
    log(f"    价格: 并发创建 {len(price_points)} 个地区（workers={workers}）")

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
        try:
            for future in as_completed(future_map):
                if cancel_event is not None and cancel_event.is_set():
                    for pending in future_map:
                        pending.cancel()
                    raise ProcessCanceled("subscription upload canceled")
                target_territory = future_map[future]
                try:
                    future.result()
                    created += 1
                except Exception as e:
                    failed += 1
                    log(f"    ⚠️  价格创建跳过 {target_territory}: {e}")
        except ProcessCanceled:
            for pending in future_map:
                pending.cancel()
            raise

    return created, failed


def _create_subscription_prices_sequential(
    api, sub_id, price_points, price_cfg, log=print, cancel_event=None
):
    created = 0
    failed = 0
    for target_territory, target_pp_id in price_points:
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCanceled("subscription upload canceled")
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
            log(f"    ⚠️  价格创建跳过 {target_territory}: {e}")
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


def _sync_intro_offer(api, sub_id, offer_cfg, update_existing, dry_run, log=print):
    if offer_cfg is None:
        return

    existing = api.list_subscription_intro_offers(sub_id)
    if existing and not update_existing:
        log("    入门优惠: 已存在，跳过")
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
        log(f"    [预览] 入门优惠: {offer_cfg['offerMode']} / {offer_cfg['duration']}")
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
    log(f"    入门优惠: {attrs['offerMode']} / {attrs['duration']} ✅")


def _sync_promo_offers(api, sub_id, offers_cfg, update_existing, dry_run, log=print):
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
                    log(f"    [预览] 促销优惠 {code}: 将重建")
                else:
                    api.delete_subscription_promo_offer(by_code[code]["id"])
                    api.create_subscription_promo_offer(sub_id, attrs, pp_id)
                    log(f"    促销优惠 {code}: 重建 ✅")
            else:
                log(f"    促销优惠 {code}: 已存在，跳过")
        else:
            if dry_run:
                log(f"    [预览] 促销优惠 {code}: 将创建")
            else:
                api.create_subscription_promo_offer(sub_id, attrs, pp_id)
                log(f"    促销优惠 {code}: 创建 ✅")


def _sync_review_screenshot(api, sub_id, shot_path, update_existing, dry_run, log=print):
    path = Path(shot_path)

    existing = api.list_subscription_review_screenshots(sub_id)
    if existing and not update_existing:
        log(f"    审核截图: 已存在，跳过")
        return

    if dry_run:
        log(f"    [预览] 审核截图: 将上传 {path.name}")
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
    log(f"    审核截图: {path.name} 上传 ✅")
