"""Pull IAP + subscription metadata from App Store Connect into a local snapshot.

Copies product identity, type, period, groupLevel, localizations, intro
summary, and the base price only. Review screenshots stay empty; the
equalized / per-territory price matrix is not downloaded.
"""
from __future__ import annotations

from typing import Any, Optional

from asc.iap.models import intro_summary, localization_map
from asc.progress import ProcessCanceled


def _raise_if_canceled(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessCanceled("iap compare canceled")


def _report_phase(reporter, phase_id: str) -> None:
    if reporter is None:
        return
    phase = getattr(reporter, "phase", None)
    if callable(phase):
        phase(phase_id)


def _report_progress(reporter, current: int, total: int, msg: str | None = None) -> None:
    if reporter is None:
        return
    progress = getattr(reporter, "progress", None)
    if callable(progress):
        progress(current, total, msg=msg)


def pull_remote_snapshot(
    api,
    app_id: str,
    *,
    product_ids: Optional[list[str]] = None,
    group_names: Optional[list[str]] = None,
    reporter: Any = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """Fetch ASC IAP + subscriptions as an iap_packages.json-shaped snapshot."""
    wanted = {pid.strip() for pid in (product_ids or []) if pid and str(pid).strip()}
    wanted_groups = {
        name.strip() for name in (group_names or []) if name and str(name).strip()
    }

    _raise_if_canceled(cancel_event)
    _report_phase(reporter, "iap")
    items = _pull_one_time_items(
        api, app_id, wanted=wanted or None, reporter=reporter, cancel_event=cancel_event
    )
    _raise_if_canceled(cancel_event)
    _report_phase(reporter, "groups")
    groups = _pull_subscription_groups(
        api,
        app_id,
        wanted_products=wanted or None,
        wanted_groups=wanted_groups or None,
        reporter=reporter,
        cancel_event=cancel_event,
    )
    if wanted:
        items = [
            item
            for item in items
            if str(item.get("productId") or "").strip() in wanted
        ]
        filtered_groups = []
        for group in groups:
            subs = [
                sub
                for sub in group.get("subscriptions") or []
                if str(sub.get("productId") or "").strip() in wanted
            ]
            if subs:
                copy = dict(group)
                copy["subscriptions"] = subs
                filtered_groups.append(copy)
        groups = filtered_groups
    return {"items": items, "subscriptionGroups": groups}


def _pull_one_time_items(
    api,
    app_id: str,
    *,
    wanted: Optional[set[str]],
    reporter: Any = None,
    cancel_event: Any = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        records = api.list_in_app_purchases(app_id) or []
    except Exception:
        _report_progress(reporter, 1, 1, msg="IAP 0/0")
        return items
    total = len(records)
    if total == 0:
        _report_progress(reporter, 1, 1, msg="IAP 0/0")
        return items
    _report_progress(reporter, 0, total, msg=f"IAP 0/{total}")
    for idx, record in enumerate(records):
        _raise_if_canceled(cancel_event)
        attrs = record.get("attributes") or {}
        product_id = str(attrs.get("productId") or "").strip()
        if not product_id:
            _report_progress(reporter, idx + 1, total, msg=f"IAP {idx + 1}/{total}")
            continue
        if wanted is not None and product_id not in wanted:
            _report_progress(reporter, idx + 1, total, msg=f"IAP {idx + 1}/{total}")
            continue
        iap_id = record.get("id")
        loc_map = {}
        if iap_id:
            loc_map = _iap_localizations(api, iap_id)
        price = _iap_base_price(api, iap_id) if iap_id else None
        item: dict[str, Any] = {
            "productId": product_id,
            "name": str(attrs.get("name") or product_id).strip(),
            "inAppPurchaseType": str(attrs.get("inAppPurchaseType") or "").strip(),
            "availableInAllTerritories": True,
            "localizations": loc_map,
            "review": {"screenshot": "", "note": str(attrs.get("reviewNote") or "")},
        }
        if price:
            item["price"] = price
        items.append(item)
        _report_progress(reporter, idx + 1, total, msg=f"IAP {idx + 1}/{total}")
    return items


def _pull_subscription_groups(
    api,
    app_id: str,
    *,
    wanted_products: Optional[set[str]],
    wanted_groups: Optional[set[str]],
    reporter: Any = None,
    cancel_event: Any = None,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    try:
        records = api.list_subscription_groups(app_id) or []
    except Exception:
        _report_progress(reporter, 1, 1, msg="订阅组 0/0")
        return groups
    total = len(records)
    if total == 0:
        _report_progress(reporter, 1, 1, msg="订阅组 0/0")
        return groups
    _report_progress(reporter, 0, total, msg=f"订阅组 0/{total}")
    for idx, record in enumerate(records):
        _raise_if_canceled(cancel_event)
        attrs = record.get("attributes") or {}
        reference = str(attrs.get("referenceName") or "").strip()
        if wanted_groups is not None and reference not in wanted_groups:
            _report_progress(reporter, idx + 1, total, msg=f"订阅组 {idx + 1}/{total}")
            continue
        group_id = record.get("id")
        loc_map = _group_localizations(api, group_id) if group_id else {}
        subs = _pull_subscriptions(
            api,
            group_id,
            wanted_products=wanted_products,
            cancel_event=cancel_event,
        ) if group_id else []
        if wanted_products is not None and not subs and wanted_groups is None:
            _report_progress(reporter, idx + 1, total, msg=f"订阅组 {idx + 1}/{total}")
            continue
        groups.append(
            {
                "referenceName": reference or "Untitled",
                "localizations": loc_map,
                "subscriptions": subs,
            }
        )
        _report_progress(reporter, idx + 1, total, msg=f"订阅组 {idx + 1}/{total}")
    return groups


def _pull_subscriptions(
    api,
    group_id: str,
    *,
    wanted_products: Optional[set[str]],
    cancel_event: Any = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        records = api.list_subscriptions(group_id) or []
    except Exception:
        return out
    for record in records:
        _raise_if_canceled(cancel_event)
        attrs = record.get("attributes") or {}
        product_id = str(attrs.get("productId") or "").strip()
        if not product_id:
            continue
        if wanted_products is not None and product_id not in wanted_products:
            continue
        sub_id = record.get("id")
        loc_map = _sub_localizations(api, sub_id) if sub_id else {}
        price = _sub_base_price(api, sub_id) if sub_id else None
        intro = _intro_summary(api, sub_id) if sub_id else None
        level = attrs.get("groupLevel")
        try:
            group_level = int(level) if level is not None else None
        except (TypeError, ValueError):
            group_level = None
        sub: dict[str, Any] = {
            "productId": product_id,
            "name": str(attrs.get("name") or product_id).strip(),
            "subscriptionPeriod": str(attrs.get("subscriptionPeriod") or "").strip(),
            "familySharable": bool(attrs.get("familySharable", False)),
            "availableInAllTerritories": True,
            "localizations": loc_map,
            "review": {"screenshot": "", "note": str(attrs.get("reviewNote") or "")},
        }
        if group_level is not None:
            sub["groupLevel"] = group_level
        if price:
            sub["price"] = price
        if intro:
            sub["introductoryOffer"] = intro
        out.append(sub)
    return out


def _loc_map_from_resources(records: list, *, include_description: bool) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for record in records or []:
        attrs = record.get("attributes") or {}
        locale = str(attrs.get("locale") or "").strip()
        if not locale:
            continue
        row = {"name": str(attrs.get("name") or "").strip()}
        if include_description:
            row["description"] = str(attrs.get("description") or "").strip()
        out[locale] = row
    return localization_map(out)


def _iap_localizations(api, iap_id: str) -> dict[str, dict[str, str]]:
    try:
        records = api.get_in_app_purchase_localizations(iap_id) or []
    except Exception:
        return {}
    return _loc_map_from_resources(records, include_description=True)


def _group_localizations(api, group_id: str) -> dict[str, dict[str, str]]:
    try:
        records = api.list_subscription_group_localizations(group_id) or []
    except Exception:
        return {}
    return _loc_map_from_resources(records, include_description=False)


def _sub_localizations(api, sub_id: str) -> dict[str, dict[str, str]]:
    try:
        records = api.list_subscription_localizations(sub_id) or []
    except Exception:
        return {}
    return _loc_map_from_resources(records, include_description=True)


def _relationship_id(resource: dict, name: str) -> str:
    rel = ((resource.get("relationships") or {}).get(name) or {}).get("data") or {}
    if isinstance(rel, list):
        rel = rel[0] if rel else {}
    return str(rel.get("id") or "")


def _iap_base_price(api, iap_id: str) -> Optional[dict[str, Any]]:
    try:
        schedule = api.get_in_app_purchase_price_schedule(iap_id)
    except Exception:
        schedule = None
    if not isinstance(schedule, dict):
        return None
    territory = _relationship_id(schedule, "baseTerritory")
    amount = ""
    attrs = schedule.get("attributes") or {}
    amount = str(attrs.get("customerPrice") or attrs.get("baseAmount") or "").strip()
    # Some fakes stash the base amount directly.
    if not amount:
        amount = str(schedule.get("baseAmount") or "").strip()
    if not territory:
        territory = str(schedule.get("baseTerritory") or "").strip()
    if not territory and not amount:
        return None
    out: dict[str, Any] = {"applyEqualizedPrices": True}
    if territory:
        out["baseTerritory"] = territory
    if amount:
        out["baseAmount"] = amount
    return out


def _sub_base_price(api, sub_id: str) -> Optional[dict[str, Any]]:
    try:
        prices = api.list_subscription_prices(sub_id) or []
    except Exception:
        prices = []
    if not prices:
        return None
    first = prices[0] if isinstance(prices[0], dict) else {}
    attrs = first.get("attributes") or {}
    territory = (
        str(attrs.get("territory") or first.get("territory") or "").strip()
        or _relationship_id(first, "territory")
    )
    amount = str(
        attrs.get("customerPrice")
        or attrs.get("baseAmount")
        or first.get("customerPrice")
        or first.get("baseAmount")
        or ""
    ).strip()
    if not territory and not amount:
        return None
    out: dict[str, Any] = {"applyEqualizedPrices": True}
    if territory:
        out["baseTerritory"] = territory
    if amount:
        out["baseAmount"] = amount
    return out


def _intro_summary(api, sub_id: str) -> Optional[dict[str, Any]]:
    try:
        offers = api.list_subscription_intro_offers(sub_id) or []
    except Exception:
        offers = []
    if not offers:
        return None
    first = offers[0] if isinstance(offers[0], dict) else {}
    attrs = dict(first.get("attributes") or {})
    if first.get("offerMode") and "offerMode" not in attrs:
        attrs["offerMode"] = first.get("offerMode")
    return intro_summary(attrs)
