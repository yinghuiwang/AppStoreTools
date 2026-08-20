"""Shared IAP snapshot / plan types and Apple field limits."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

NAME_MIN = 2
NAME_MAX = 30
DESCRIPTION_MAX = 45
REFERENCE_NAME_MAX = 64
PRODUCT_ID_MAX = 100

IAP_TYPES = ("CONSUMABLE", "NON_CONSUMABLE")
# Apple also returns this on list_in_app_purchases. Infer/create still only emit IAP_TYPES.
STORE_IAP_TYPES = IAP_TYPES + ("NON_RENEWING_SUBSCRIPTION",)
SUBSCRIPTION_PERIODS = (
    "ONE_WEEK",
    "ONE_MONTH",
    "TWO_MONTHS",
    "THREE_MONTHS",
    "SIX_MONTHS",
    "ONE_YEAR",
)

GROUP_LEVEL_HELP = (
    "groupLevel 是同一订阅组内的服务等级（Apple 官方字段）：\n"
    "- 数字越小，等级越高（1 最高）\n"
    "- 用户在同组内切换订阅时，靠它判断是升级 / 降级 / 平级（crossgrade）\n"
    "- 升级通常立即生效并折算；降级通常在当前周期结束后生效\n"
    "- 同组内 groupLevel 可以重复：相同等级之间切换为平级（crossgrade）\n"
    "- 消耗品（items）不需要 groupLevel"
)

# Coarse store-sync badges used by the edit tree and upload list.
STATUS_LOCAL_ONLY = "local-only"
STATUS_EQUAL = "equal"
STATUS_CHANGED = "changed"
STATUS_UNKNOWN = "unchecked"

ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_SKIP = "skip"

KIND_IAP = "iap"
KIND_SUBSCRIPTION = "subscription"
KIND_GROUP = "group"


def empty_snapshot_dict() -> dict[str, Any]:
    return {"items": [], "subscriptionGroups": []}


IapSnapshot = dict  # JSON-shaped {items, subscriptionGroups}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def localization_map(value: Any) -> dict[str, dict[str, str]]:
    raw = _as_dict(value)
    out: dict[str, dict[str, str]] = {}
    for locale, payload in raw.items():
        if not isinstance(locale, str) or not locale.strip():
            continue
        if isinstance(payload, str):
            out[locale] = {"name": payload, "description": ""}
            continue
        loc = _as_dict(payload)
        out[locale] = {
            "name": str(loc.get("name") or loc.get("displayName") or "").strip(),
            "description": str(loc.get("description") or "").strip(),
        }
    return out


def price_dict(value: Any) -> Optional[dict[str, Any]]:
    raw = _as_dict(value)
    if not raw:
        return None
    out: dict[str, Any] = {}
    for key in (
        "baseTerritory",
        "baseAmount",
        "pricePointId",
        "territory",
        "applyEqualizedPrices",
        "startDate",
        "endDate",
        "creationMode",
        "inlineBatchSize",
        "maxWorkers",
    ):
        if key in raw and raw[key] is not None:
            out[key] = raw[key]
    return out or None


def review_dict(value: Any) -> dict[str, str]:
    raw = _as_dict(value)
    return {
        "screenshot": str(raw.get("screenshot") or "").strip(),
        "note": str(raw.get("note") or "").strip(),
    }


def intro_summary(value: Any) -> Optional[dict[str, Any]]:
    raw = _as_dict(value)
    if not raw:
        return None
    mode = str(raw.get("offerMode") or raw.get("duration") or "").strip()
    if not mode and raw.get("numberOfPeriods") is None:
        return None
    out: dict[str, Any] = {}
    for key in (
        "offerMode",
        "duration",
        "numberOfPeriods",
        "baseTerritory",
        "baseAmount",
        "startDate",
        "endDate",
    ):
        if raw.get(key) is not None and raw.get(key) != "":
            out[key] = raw[key]
    return out or None


@dataclass
class FieldDiff:
    field: str
    local: str
    asc: str


@dataclass
class IapPlanItem:
    product_id: str
    kind: str
    type: str
    name: str
    group_name: str = ""
    action: str = ACTION_SKIP
    status: str = STATUS_UNKNOWN
    fields: list[FieldDiff] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "productId": self.product_id,
            "kind": self.kind,
            "type": self.type,
            "name": self.name,
            "groupName": self.group_name,
            "action": self.action,
            "status": self.status,
            "fields": [
                {"field": row.field, "local": row.local, "asc": row.asc}
                for row in self.fields
            ],
        }


@dataclass
class IapPlan:
    items: list[IapPlanItem]
    update_existing: bool = False
    remote_ok: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.remote_ok,
            "updateExisting": self.update_existing,
            "error": self.error,
            "items": [item.to_dict() for item in self.items],
            "counts": {
                "create": sum(1 for i in self.items if i.action == ACTION_CREATE),
                "update": sum(1 for i in self.items if i.action == ACTION_UPDATE),
                "skip": sum(1 for i in self.items if i.action == ACTION_SKIP),
            },
        }


def iter_local_products(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten items + subscriptions into comparable product records."""
    rows: list[dict[str, Any]] = []
    for item in snapshot.get("items") or []:
        if not isinstance(item, dict):
            continue
        product_id = str(item.get("productId") or "").strip()
        if not product_id:
            continue
        rows.append(
            {
                "productId": product_id,
                "kind": KIND_IAP,
                "type": str(item.get("inAppPurchaseType") or "").strip(),
                "name": str(item.get("name") or "").strip(),
                "groupName": "",
                "groupLevel": None,
                "subscriptionPeriod": "",
                "price": price_dict(item.get("price")) or {},
                "localizations": localization_map(item.get("localizations")),
                "introductoryOffer": intro_summary(item.get("introductoryOffer")),
                "review": review_dict(item.get("review")),
                "raw": item,
            }
        )
    for group in snapshot.get("subscriptionGroups") or []:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("referenceName") or "").strip()
        for sub in group.get("subscriptions") or []:
            if not isinstance(sub, dict):
                continue
            product_id = str(sub.get("productId") or "").strip()
            if not product_id:
                continue
            level = sub.get("groupLevel")
            rows.append(
                {
                    "productId": product_id,
                    "kind": KIND_SUBSCRIPTION,
                    "type": "AUTO_RENEWABLE_SUBSCRIPTION",
                    "name": str(sub.get("name") or "").strip(),
                    "groupName": group_name,
                    "groupLevel": level if isinstance(level, int) else None,
                    "subscriptionPeriod": str(sub.get("subscriptionPeriod") or "").strip(),
                    "price": price_dict(sub.get("price")) or {},
                    "localizations": localization_map(sub.get("localizations")),
                    "introductoryOffer": intro_summary(sub.get("introductoryOffer")),
                    "review": review_dict(sub.get("review")),
                    "raw": sub,
                    "groupRaw": group,
                }
            )
    return rows
