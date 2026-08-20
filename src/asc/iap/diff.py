"""Compare a local IAP snapshot with an ASC snapshot and build a publish plan."""
from __future__ import annotations

from typing import Any

from asc.iap.models import (
    ACTION_CREATE,
    ACTION_SKIP,
    ACTION_UPDATE,
    STATUS_CHANGED,
    STATUS_EQUAL,
    STATUS_LOCAL_ONLY,
    STATUS_UNKNOWN,
    FieldDiff,
    IapPlan,
    IapPlanItem,
    iter_local_products,
    localization_map,
    price_dict,
)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()


def _price_key(price: dict[str, Any] | None) -> str:
    raw = price_dict(price) or {}
    territory = _norm(raw.get("baseTerritory") or raw.get("territory"))
    amount = _norm(raw.get("baseAmount"))
    return f"{territory}:{amount}"


def _locs_key(locs: Any, *, include_description: bool) -> str:
    mapped = localization_map(locs)
    parts = []
    for locale in sorted(mapped):
        row = mapped[locale]
        name = _norm(row.get("name"))
        desc = _norm(row.get("description")) if include_description else ""
        parts.append(f"{locale}={name}|{desc}")
    return ";".join(parts)


def _intro_key(value: Any) -> str:
    raw = value if isinstance(value, dict) else {}
    return "|".join(
        [
            _norm(raw.get("offerMode")),
            _norm(raw.get("duration")),
            _norm(raw.get("numberOfPeriods")),
            _norm(raw.get("baseTerritory")),
        ]
    )


def _product_fields(local: dict[str, Any], remote: dict[str, Any] | None) -> list[FieldDiff]:
    remote = remote or {}
    include_desc = local.get("kind") != "group"
    pairs = [
        ("type", _norm(local.get("type")), _norm(remote.get("type"))),
        ("name", _norm(local.get("name")), _norm(remote.get("name"))),
        (
            "subscriptionPeriod",
            _norm(local.get("subscriptionPeriod")),
            _norm(remote.get("subscriptionPeriod")),
        ),
        ("groupLevel", _norm(local.get("groupLevel")), _norm(remote.get("groupLevel"))),
        ("price", _price_key(local.get("price")), _price_key(remote.get("price"))),
        (
            "localizations",
            _locs_key(local.get("localizations"), include_description=include_desc),
            _locs_key(remote.get("localizations"), include_description=include_desc),
        ),
        (
            "introductoryOffer",
            _intro_key(local.get("introductoryOffer")),
            _intro_key(remote.get("introductoryOffer")),
        ),
    ]
    diffs: list[FieldDiff] = []
    for field, left, right in pairs:
        if field in {"subscriptionPeriod", "groupLevel", "introductoryOffer"}:
            if not left and not right:
                continue
        if field == "type" and not left and not right:
            continue
        if left != right:
            diffs.append(FieldDiff(field=field, local=left, asc=right))
    return diffs


def coarse_status(local: dict[str, Any] | None, remote: dict[str, Any] | None) -> str:
    if local and not remote:
        return STATUS_LOCAL_ONLY
    if not local:
        return STATUS_UNKNOWN
    diffs = _product_fields(local, remote)
    return STATUS_CHANGED if diffs else STATUS_EQUAL


def build_plan(
    local_snapshot: dict[str, Any],
    remote_snapshot: dict[str, Any] | None,
    *,
    update_existing: bool = False,
    remote_ok: bool = True,
    error: str = "",
) -> IapPlan:
    local_rows = iter_local_products(local_snapshot)
    remote_map: dict[str, dict[str, Any]] = {}
    if remote_snapshot:
        for row in iter_local_products(remote_snapshot):
            remote_map[row["productId"]] = row

    items: list[IapPlanItem] = []
    for row in local_rows:
        remote = remote_map.get(row["productId"])
        status = coarse_status(row, remote) if remote_ok else STATUS_UNKNOWN
        if not remote:
            action = ACTION_CREATE
        elif not update_existing:
            action = ACTION_SKIP
        elif status == STATUS_CHANGED:
            action = ACTION_UPDATE
        else:
            action = ACTION_SKIP
        fields = _product_fields(row, remote) if status == STATUS_CHANGED else []
        items.append(
            IapPlanItem(
                product_id=row["productId"],
                kind=row["kind"],
                type=row.get("type") or "",
                name=row.get("name") or row["productId"],
                group_name=row.get("groupName") or "",
                action=action,
                status=status,
                fields=fields,
            )
        )
    return IapPlan(
        items=items,
        update_existing=update_existing,
        remote_ok=remote_ok,
        error=error,
    )
