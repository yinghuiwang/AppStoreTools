"""Infer IAP kinds / periods from a pasted product table. Never writes disk."""
from __future__ import annotations

import csv
import io
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from asc.iap.models import GROUP_LEVEL_HELP, IAP_TYPES, SUBSCRIPTION_PERIODS

_PERIOD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:^|[._-])week(?:s)?(?:[._-]|$)", re.I), "ONE_WEEK"),
    (re.compile(r"(?:^|[._-])year(?:ly)?(?:[._-]|$)|annual", re.I), "ONE_YEAR"),
    (re.compile(r"(?:^|[._-])(?:six|6)[._-]?months?(?:[._-]|$)", re.I), "SIX_MONTHS"),
    (re.compile(r"(?:^|[._-])(?:three|3)[._-]?months?(?:[._-]|$)", re.I), "THREE_MONTHS"),
    (re.compile(r"(?:^|[._-])(?:two|2)[._-]?months?(?:[._-]|$)", re.I), "TWO_MONTHS"),
    (re.compile(r"(?:^|[._-])month(?:ly|s)?(?:[._-]|$)", re.I), "ONE_MONTH"),
]
_CONSUMABLE_RE = re.compile(
    r"coins?|credits?|packs?|gems?|points?|金币|积分|点券", re.I
)
_MEMBERSHIP_RE = re.compile(r"会员|member|premium|pro\b|vip|subscription", re.I)
_SUPER_RE = re.compile(r"(?:^|[._-])super(?:[._-]|$)", re.I)
_POINTS_MONTH_RE = re.compile(r"_points_month_|[._]points[._]month[._]", re.I)
_PRODUCT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}\.[A-Za-z0-9._-]+")
_PRICE_IN_ID_RE = re.compile(r"(?:^|[._-])(\d+)[._](\d{2})(?:[._-]|$)")

_HEADER_ALIASES = {
    "productid": "productId",
    "product_id": "productId",
    "id": "productId",
    "sku": "productId",
    "商品id": "productId",
    "name": "name",
    "名称": "name",
    "price": "price",
    "价格": "price",
    "kind": "kind",
    "category": "kind",
    "type": "kind",
    "类型": "kind",
    "分类": "kind",
    "points": "points",
    "积分": "points",
    "displayname": "displayName",
    "display_name": "displayName",
    "展示名": "displayName",
    "group": "group",
    "订阅组": "group",
}


def infer_products(
    raw: str,
    *,
    app_short_name: str = "",
    default_territory: str = "USA",
) -> dict[str, Any]:
    """Parse a pasted table / JSON and return a draft snapshot plus confirmations.

    Does not write groupLevel onto subscriptions. Callers must collect levels
    from `groupLevelBatches` before saving.
    """
    rows = _parse_input(raw)
    products: list[dict[str, Any]] = []
    needs_confirmation: list[dict[str, Any]] = []
    for row in rows:
        inferred = _infer_row(row)
        products.append(inferred)
        if inferred["kind"] == "unknown" or inferred.get("needsConfirmation"):
            needs_confirmation.append(
                {
                    "productId": inferred["productId"],
                    "name": inferred.get("name") or "",
                    "reason": inferred.get("reason") or "unable to infer type",
                    "kind": inferred["kind"],
                }
            )

    snapshot, groups_meta = _build_draft(
        products,
        app_short_name=app_short_name,
        default_territory=default_territory,
    )
    batches = _group_level_batches(groups_meta)
    return {
        "ok": True,
        "snapshot": snapshot,
        "products": products,
        "needsConfirmation": needs_confirmation,
        "needsGroupLevels": [p["productId"] for p in products if p["kind"] == "subscription"],
        "groupLevelHelp": GROUP_LEVEL_HELP,
        "groupLevelBatches": batches,
    }


def apply_group_levels(
    snapshot: dict[str, Any],
    levels: dict[str, int],
) -> dict[str, Any]:
    """Write confirmed groupLevel values onto matching subscriptions."""
    out = {
        "items": list(snapshot.get("items") or []),
        "subscriptionGroups": [],
    }
    for group in snapshot.get("subscriptionGroups") or []:
        if not isinstance(group, dict):
            continue
        copy = dict(group)
        subs = []
        for sub in group.get("subscriptions") or []:
            if not isinstance(sub, dict):
                continue
            row = dict(sub)
            pid = str(row.get("productId") or "").strip()
            if pid in levels:
                row["groupLevel"] = int(levels[pid])
            subs.append(row)
        copy["subscriptions"] = subs
        out["subscriptionGroups"].append(copy)
    return out


def _parse_input(raw: str) -> list[dict[str, str]]:
    text = (raw or "").strip()
    if not text:
        return []
    if text[0] in "{[":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if data is not None:
            return _rows_from_json(data)
    return _rows_from_table(text)


def _rows_from_json(data: Any) -> list[dict[str, str]]:
    products: list[Any]
    if isinstance(data, dict):
        products = data.get("products") or data.get("items") or data.get("rows") or []
        if isinstance(products, dict):
            products = [products]
    elif isinstance(data, list):
        products = data
    else:
        return []
    rows: list[dict[str, str]] = []
    for item in products:
        if not isinstance(item, dict):
            continue
        row = {str(k): "" if v is None else str(v).strip() for k, v in item.items()}
        rows.append(_canonicalize_row(row))
    return [r for r in rows if r.get("productId")]


def _rows_from_table(text: str) -> list[dict[str, str]]:
    sample = text.splitlines()[0] if text else ""
    dialect = "excel-tab" if "\t" in sample else "excel"
    reader = csv.reader(io.StringIO(text), dialect=dialect)
    lines = [list(row) for row in reader if any(str(c).strip() for c in row)]
    if not lines:
        return []
    header = [_canonical_header(c) for c in lines[0]]
    has_header = "productId" in header or "name" in header
    rows: list[dict[str, str]] = []
    body = lines[1:] if has_header else lines
    if has_header:
        for cells in body:
            raw = {
                header[i]: str(cells[i]).strip()
                for i in range(min(len(header), len(cells)))
                if header[i]
            }
            rows.append(_canonicalize_row(raw))
    else:
        for cells in body:
            rows.append(_row_from_cells(cells))
    return [r for r in rows if r.get("productId")]


def _canonical_header(value: str) -> str:
    key = re.sub(r"[\s_]+", "", (value or "").strip().lower())
    return _HEADER_ALIASES.get(key) or _HEADER_ALIASES.get((value or "").strip().lower()) or ""


def _canonicalize_row(row: dict[str, str]) -> dict[str, str]:
    out = {"productId": "", "name": "", "price": "", "kind": "", "points": "", "displayName": "", "group": ""}
    mapped: dict[str, str] = {}
    for key, value in row.items():
        canon = _HEADER_ALIASES.get(re.sub(r"[\s_]+", "", key.strip().lower())) or key
        mapped[canon] = value
    out.update({k: mapped[k] for k in out if k in mapped})
    if not out["productId"]:
        out["productId"] = mapped.get("productId") or mapped.get("id") or ""
    return out


def _row_from_cells(cells: list[str]) -> dict[str, str]:
    values = [str(c).strip() for c in cells if str(c).strip()]
    product_id = ""
    for cell in values:
        match = _PRODUCT_ID_RE.search(cell)
        if match and "." in match.group(0):
            product_id = match.group(0)
            break
    name = ""
    price = ""
    kind = ""
    points = ""
    display = ""
    for cell in values:
        if cell == product_id:
            continue
        if _looks_like_price(cell) and not price:
            price = cell
            continue
        if cell.isdigit() and not points:
            points = cell
            continue
        if _MEMBERSHIP_RE.search(cell) or "积分" in cell or "权益" in cell:
            if not kind:
                kind = cell
                continue
        if not name:
            name = cell
            continue
        if not display:
            display = cell
    return {
        "productId": product_id,
        "name": name,
        "price": price,
        "kind": kind,
        "points": points,
        "displayName": display,
        "group": "",
    }


def _looks_like_price(value: str) -> bool:
    text = value.strip().replace("$", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", text):
        return False
    try:
        Decimal(text)
    except (InvalidOperation, ValueError):
        return False
    return True


def _infer_row(row: dict[str, str]) -> dict[str, Any]:
    product_id = (row.get("productId") or "").strip()
    name = (row.get("name") or "").strip()
    blob = f"{product_id} {name} {row.get('kind') or ''} {row.get('displayName') or ''}"
    period = _infer_period(blob)
    category = (row.get("kind") or "").strip()
    kind = "unknown"
    reason = ""
    iap_type = ""

    if _POINTS_MONTH_RE.search(product_id) or (
        period and _CONSUMABLE_RE.search(blob) and "订阅" not in category
    ):
        if period:
            kind = "subscription"
            reason = "period token in productId"
    if period and kind == "unknown":
        kind = "subscription"
        reason = "period token"
    if kind == "unknown" and ("会员" in category or _MEMBERSHIP_RE.search(category)):
        if period:
            kind = "subscription"
            reason = "membership category"
        else:
            kind = "unknown"
            reason = "membership category without period"
    if kind == "unknown":
        consumable_hint = (
            "积分" in category
            or "消耗" in category
            or _CONSUMABLE_RE.search(blob)
        )
        if consumable_hint and not period:
            kind = "iap"
            iap_type = "CONSUMABLE"
            reason = "coins/credits without period"
        elif "非消耗" in category or "non-consumable" in category.lower():
            kind = "iap"
            iap_type = "NON_CONSUMABLE"
            reason = "non-consumable category"

    if kind == "unknown":
        reason = reason or "unable to infer type"

    price = _normalize_price(row.get("price") or "", product_id)
    display = (row.get("displayName") or "").strip()
    return {
        "productId": product_id,
        "name": name or product_id,
        "kind": kind,
        "inAppPurchaseType": iap_type,
        "subscriptionPeriod": period,
        "price": price,
        "points": (row.get("points") or "").strip(),
        "displayName": display,
        "group": (row.get("group") or "").strip(),
        "isSuper": bool(_SUPER_RE.search(blob)),
        "reason": reason,
        "needsConfirmation": kind == "unknown",
        "raw": row,
    }


def _infer_period(blob: str) -> str:
    for pattern, period in _PERIOD_PATTERNS:
        if pattern.search(blob):
            return period
    return ""


def _normalize_price(value: str, product_id: str) -> str:
    text = (value or "").strip().replace("$", "")
    if _looks_like_price(text):
        if "." not in text:
            return f"{text}.00"
        return text
    match = _PRICE_IN_ID_RE.search(product_id)
    if match:
        return f"{int(match.group(1))}.{match.group(2)}"
    return ""


def _build_draft(
    products: list[dict[str, Any]],
    *,
    app_short_name: str,
    default_territory: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    group_order: list[str] = []

    for product in products:
        if product["kind"] == "iap":
            items.append(_item_from_product(product, default_territory))
            continue
        if product["kind"] != "subscription":
            # Unknown rows still appear as items so the user can retype them.
            item = _item_from_product(product, default_territory)
            item["inAppPurchaseType"] = product.get("inAppPurchaseType") or "CONSUMABLE"
            items.append(item)
            continue
        group_key = product.get("group") or product.get("displayName") or "Membership"
        if group_key not in groups:
            display = product.get("displayName") or group_key
            groups[group_key] = {
                "referenceName": group_key,
                "localizations": _group_locs(display, app_short_name),
                "subscriptions": [],
            }
            group_order.append(group_key)
        groups[group_key]["subscriptions"].append(
            _sub_from_product(product, default_territory)
        )

    snapshot = {
        "items": items,
        "subscriptionGroups": [groups[key] for key in group_order],
    }
    meta = [
        {
            "referenceName": groups[key]["referenceName"],
            "displayName": (groups[key]["localizations"].get("en-US") or {}).get("name")
            or groups[key]["referenceName"],
            "subscriptions": [
                {
                    "productId": sub.get("productId"),
                    "name": sub.get("name"),
                    "suggestedGroupLevel": None,
                }
                for sub in groups[key]["subscriptions"]
            ],
        }
        for key in group_order
    ]
    return snapshot, meta


def _item_from_product(product: dict[str, Any], territory: str) -> dict[str, Any]:
    name = product.get("name") or product["productId"]
    loc_name = _clip_name(product.get("displayName") or name)
    points = product.get("points") or ""
    en_desc = _clip_desc(
        f"Get {points} credits immediately after purchase."
        if points
        else f"Unlock {loc_name}."
    )
    zh_desc = _clip_desc(
        f"购买后立即获得 {points} 积分。" if points else f"解锁{loc_name}。"
    )
    iap_type = product.get("inAppPurchaseType") or "CONSUMABLE"
    if iap_type not in IAP_TYPES:
        iap_type = "CONSUMABLE"
    item: dict[str, Any] = {
        "productId": product["productId"],
        "name": name[:64],
        "inAppPurchaseType": iap_type,
        "availableInAllTerritories": True,
        "localizations": {
            "en-US": {"name": loc_name, "description": en_desc},
            "zh-Hans": {"name": _clip_name(loc_name), "description": zh_desc},
        },
        "review": {"screenshot": "", "note": ""},
    }
    if product.get("price"):
        item["price"] = {
            "baseTerritory": territory,
            "baseAmount": str(product["price"]),
            "applyEqualizedPrices": True,
        }
    return item


def _sub_from_product(product: dict[str, Any], territory: str) -> dict[str, Any]:
    name = product.get("name") or product["productId"]
    loc_name = _clip_name(product.get("displayName") or name)
    period = product.get("subscriptionPeriod") or "ONE_MONTH"
    if period not in SUBSCRIPTION_PERIODS:
        period = "ONE_MONTH"
    sub: dict[str, Any] = {
        "productId": product["productId"],
        "name": name[:64],
        "subscriptionPeriod": period,
        "familySharable": False,
        "availableInAllTerritories": True,
        "localizations": {
            "en-US": {
                "name": loc_name,
                "description": _clip_desc(f"{loc_name} auto-renewing access."),
            },
            "zh-Hans": {
                "name": _clip_name(loc_name),
                "description": _clip_desc(f"{loc_name} 自动续期会员。"),
            },
        },
        "review": {"screenshot": "", "note": ""},
    }
    # groupLevel intentionally omitted — UI must confirm.
    if product.get("price"):
        sub["price"] = {
            "baseTerritory": territory,
            "baseAmount": str(product["price"]),
            "applyEqualizedPrices": True,
        }
    return sub


def _group_locs(display: str, app_short_name: str) -> dict[str, dict[str, str]]:
    name = _clip_name(display or app_short_name or "Premium")
    return {
        "en-US": {"name": name},
        "zh-Hans": {"name": name},
    }


def _group_level_batches(groups_meta: list[dict[str, Any]]) -> list[dict[str, Any]]:
    batches = []
    for group in groups_meta:
        lines = []
        fill = []
        for sub in group["subscriptions"]:
            pid = sub["productId"]
            label = sub.get("name") or pid
            lines.append(f"{pid}\t\t# {label}")
            fill.append({"productId": pid, "name": label, "groupLevel": None})
        batches.append(
            {
                "referenceName": group["referenceName"],
                "displayName": group["displayName"],
                "fillTemplate": "\n".join(lines),
                "subscriptions": fill,
            }
        )
    return batches


def _clip_name(value: str) -> str:
    text = (value or "").strip() or "Item"
    if len(text) < 2:
        text = f"{text}X"
    return text[:30]


def _clip_desc(value: str) -> str:
    return (value or "").strip()[:45]
