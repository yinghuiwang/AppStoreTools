"""Read / write iap_packages.json with mtime locking."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from asc.iap.models import (
    DESCRIPTION_MAX,
    NAME_MAX,
    NAME_MIN,
    PRODUCT_ID_MAX,
    REFERENCE_NAME_MAX,
    STORE_IAP_TYPES,
    SUBSCRIPTION_PERIODS,
    empty_snapshot_dict,
    iter_local_products,
    localization_map,
)
from asc.listing.local import FileChangedError

_VALID_IAP_TYPES = set(STORE_IAP_TYPES)
_VALID_PERIODS = set(SUBSCRIPTION_PERIODS)


def empty_snapshot() -> dict[str, Any]:
    return empty_snapshot_dict()


def snapshot_has_content(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    items = snapshot.get("items") or []
    groups = snapshot.get("subscriptionGroups") or []
    return bool(items) or bool(groups)


def normalize_snapshot(data: Any) -> dict[str, Any]:
    """Accept a top-level array or {items, subscriptionGroups} object."""
    if data is None:
        return empty_snapshot()
    if isinstance(data, list):
        items = [row for row in data if isinstance(row, dict)]
        return {"items": items, "subscriptionGroups": []}
    if not isinstance(data, dict):
        raise ValueError("IAP 配置格式错误：应为数组或对象")
    items = data.get("items") or []
    groups = data.get("subscriptionGroups") or []
    if items is None:
        items = []
    if groups is None:
        groups = []
    if not isinstance(items, list) or not isinstance(groups, list):
        raise ValueError("IAP 配置格式错误：items / subscriptionGroups 必须是数组")
    return {
        "items": [row for row in items if isinstance(row, dict)],
        "subscriptionGroups": [row for row in groups if isinstance(row, dict)],
    }


def load_local_snapshot(path: str | Path) -> tuple[dict[str, Any], Optional[float], bool]:
    """Load JSON. Missing file → empty snapshot, mtime None, exists=False."""
    target = Path(path)
    if not target.exists() or not target.is_file():
        return empty_snapshot(), None, False
    raw = target.read_text(encoding="utf-8-sig")
    if not raw.strip():
        return empty_snapshot(), os.path.getmtime(target), True
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"IAP JSON 解析失败: {exc}") from exc
    snapshot = normalize_snapshot(data)
    return snapshot, os.path.getmtime(target), True


def save_local_snapshot(
    path: str | Path,
    snapshot: dict[str, Any],
    *,
    expected_mtime: float | None = None,
) -> float:
    """Validate shape, write JSON, return new mtime. Raises FileChangedError on stale mtime."""
    target = Path(path)
    if expected_mtime is not None and target.exists():
        actual = os.path.getmtime(target)
        if actual != expected_mtime:
            raise FileChangedError(
                f"{target} was modified on disk (expected mtime {expected_mtime}, "
                f"found {actual})"
            )
    normalized = normalize_snapshot(snapshot)
    issues = validate_snapshot(normalized, strict=True)
    errors = [row for row in issues if row.get("level") == "error"]
    if errors:
        raise ValueError(errors[0]["message"])
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(normalized, ensure_ascii=False, indent=2)
    if not text.endswith("\n"):
        text += "\n"
    target.write_text(text, encoding="utf-8")
    return os.path.getmtime(target)


def validate_snapshot(snapshot: dict[str, Any], *, strict: bool = False) -> list[dict[str, str]]:
    """Return issue dicts: {level, path, message}. strict=True treats missing productId as error."""
    issues: list[dict[str, str]] = []
    data = normalize_snapshot(snapshot)

    def add(level: str, path: str, message: str) -> None:
        issues.append({"level": level, "path": path, "message": message})

    for idx, item in enumerate(data["items"]):
        prefix = f"items[{idx}]"
        _validate_product_id(item, prefix, add, strict=strict)
        iap_type = str(item.get("inAppPurchaseType") or "").strip()
        if iap_type and iap_type not in _VALID_IAP_TYPES:
            add("error", f"{prefix}.inAppPurchaseType", f"unknown type {iap_type}")
        _validate_localizations(item.get("localizations"), prefix, add, require_description=True)
        name = str(item.get("name") or "").strip()
        if name and len(name) > REFERENCE_NAME_MAX:
            add("warning", f"{prefix}.name", f"reference name exceeds {REFERENCE_NAME_MAX}")

    for gidx, group in enumerate(data["subscriptionGroups"]):
        gprefix = f"subscriptionGroups[{gidx}]"
        ref = str(group.get("referenceName") or "").strip()
        if not ref:
            add("error" if strict else "warning", f"{gprefix}.referenceName", "referenceName required")
        elif len(ref) > REFERENCE_NAME_MAX:
            add("warning", f"{gprefix}.referenceName", f"reference name exceeds {REFERENCE_NAME_MAX}")
        _validate_localizations(
            group.get("localizations"), gprefix, add, require_description=False
        )
        for sidx, sub in enumerate(group.get("subscriptions") or []):
            if not isinstance(sub, dict):
                continue
            prefix = f"{gprefix}.subscriptions[{sidx}]"
            _validate_product_id(sub, prefix, add, strict=strict)
            period = str(sub.get("subscriptionPeriod") or "").strip()
            if period and period not in _VALID_PERIODS:
                add("error", f"{prefix}.subscriptionPeriod", f"unknown period {period}")
            level = sub.get("groupLevel")
            if level is not None and (not isinstance(level, int) or level < 1):
                add("error", f"{prefix}.groupLevel", "groupLevel must be an integer >= 1")
            _validate_localizations(sub.get("localizations"), prefix, add, require_description=True)

    return issues


def _validate_product_id(obj: dict, prefix: str, add, *, strict: bool) -> None:
    product_id = str(obj.get("productId") or "").strip()
    if not product_id:
        add("error" if strict else "warning", f"{prefix}.productId", "productId required")
        return
    if len(product_id) > PRODUCT_ID_MAX:
        add("error", f"{prefix}.productId", f"productId exceeds {PRODUCT_ID_MAX} characters")


def _validate_localizations(value: Any, prefix: str, add, *, require_description: bool) -> None:
    locs = localization_map(value)
    for locale, loc in locs.items():
        name = loc.get("name") or ""
        desc = loc.get("description") or ""
        path = f"{prefix}.localizations.{locale}"
        if name and (len(name) < NAME_MIN or len(name) > NAME_MAX):
            add("warning", f"{path}.name", f"display name must be {NAME_MIN}–{NAME_MAX} characters")
        if require_description and desc and len(desc) > DESCRIPTION_MAX:
            add("warning", f"{path}.description", f"description must be ≤{DESCRIPTION_MAX} characters")


def merge_preserve_review(local: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Overlay incoming onto local, keeping existing review.screenshot paths by productId."""
    local_n = normalize_snapshot(local)
    incoming_n = normalize_snapshot(incoming)
    shots = _screenshot_index(local_n)
    for item in incoming_n["items"]:
        _restore_screenshot(item, shots.get(str(item.get("productId") or "").strip()))
    for group in incoming_n["subscriptionGroups"]:
        for sub in group.get("subscriptions") or []:
            if not isinstance(sub, dict):
                continue
            _restore_screenshot(sub, shots.get(str(sub.get("productId") or "").strip()))
        local_group = _group_by_name(local_n, str(group.get("referenceName") or ""))
        if local_group and not (incoming_n and group.get("localizations")):
            pass
    return incoming_n


def missing_local_screenshot_ids(
    snapshot: dict[str, Any], iap_file: str | os.PathLike[str]
) -> set[str]:
    """Product IDs whose local review.screenshot is blank or not a file on disk."""
    try:
        base_dir = Path(iap_file).expanduser().resolve().parent
    except OSError:
        base_dir = Path(".")
    missing: set[str] = set()
    for row in iter_local_products(snapshot):
        shot = str((row.get("review") or {}).get("screenshot") or "").strip()
        if not shot:
            missing.add(row["productId"])
            continue
        path = Path(shot)
        resolved = path if path.is_absolute() else base_dir / path
        if not resolved.is_file():
            missing.add(row["productId"])
    return missing


def _screenshot_index(snapshot: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in snapshot.get("items") or []:
        pid = str(item.get("productId") or "").strip()
        shot = str((item.get("review") or {}).get("screenshot") or "").strip()
        if pid and shot:
            out[pid] = shot
    for group in snapshot.get("subscriptionGroups") or []:
        for sub in group.get("subscriptions") or []:
            if not isinstance(sub, dict):
                continue
            pid = str(sub.get("productId") or "").strip()
            shot = str((sub.get("review") or {}).get("screenshot") or "").strip()
            if pid and shot:
                out[pid] = shot
    return out


def _restore_screenshot(obj: dict[str, Any], shot: str | None) -> None:
    if not shot:
        return
    review = obj.get("review")
    if not isinstance(review, dict):
        obj["review"] = {"screenshot": shot, "note": ""}
        return
    existing = str(review.get("screenshot") or "").strip()
    if not existing:
        review["screenshot"] = shot


def _group_by_name(snapshot: dict[str, Any], name: str) -> dict[str, Any] | None:
    if not name:
        return None
    for group in snapshot.get("subscriptionGroups") or []:
        if str(group.get("referenceName") or "").strip() == name:
            return group
    return None


def merge_products(
    local: dict[str, Any],
    incoming: dict[str, Any],
    *,
    product_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Replace matching products in `local` with `incoming`; preserve review screenshots.

    When `product_ids` is set, only those productIds are copied from incoming.
    Groups that would become empty are kept if they already exist locally.
    """
    local_n = normalize_snapshot(local)
    incoming_n = normalize_snapshot(incoming)
    wanted = {pid.strip() for pid in (product_ids or set()) if pid and pid.strip()}
    shots = _screenshot_index(local_n)

    incoming_items_by_id = {
        str(item.get("productId") or "").strip(): item
        for item in incoming_n["items"]
        if str(item.get("productId") or "").strip()
    }
    incoming_subs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for group in incoming_n["subscriptionGroups"]:
        for sub in group.get("subscriptions") or []:
            if not isinstance(sub, dict):
                continue
            pid = str(sub.get("productId") or "").strip()
            if pid:
                incoming_subs[pid] = (group, sub)

    if not wanted:
        wanted = set(incoming_items_by_id) | set(incoming_subs)

    # One-time IAP: update or append.
    local_item_ids = {
        str(item.get("productId") or "").strip() for item in local_n["items"]
    }
    new_items: list[dict[str, Any]] = []
    for item in local_n["items"]:
        pid = str(item.get("productId") or "").strip()
        if pid in wanted and pid in incoming_items_by_id:
            incoming_item = dict(incoming_items_by_id[pid])
            _restore_screenshot(incoming_item, shots.get(pid))
            new_items.append(incoming_item)
        else:
            new_items.append(item)
    for pid, item in incoming_items_by_id.items():
        if pid in wanted and pid not in local_item_ids:
            incoming_item = dict(item)
            _restore_screenshot(incoming_item, shots.get(pid))
            new_items.append(incoming_item)
    local_n["items"] = new_items

    # Subscriptions: update in existing groups, append groups as needed.
    local_sub_ids = set()
    for group in local_n["subscriptionGroups"]:
        for sub in group.get("subscriptions") or []:
            if isinstance(sub, dict):
                local_sub_ids.add(str(sub.get("productId") or "").strip())

    for group in local_n["subscriptionGroups"]:
        subs = list(group.get("subscriptions") or [])
        replaced: list[dict[str, Any]] = []
        for sub in subs:
            if not isinstance(sub, dict):
                continue
            pid = str(sub.get("productId") or "").strip()
            if pid in wanted and pid in incoming_subs:
                _g, incoming_sub = incoming_subs[pid]
                merged = dict(incoming_sub)
                _restore_screenshot(merged, shots.get(pid))
                replaced.append(merged)
                # Copy group localizations if local group has none.
                if incoming_subs[pid][0].get("localizations") and not group.get(
                    "localizations"
                ):
                    group["localizations"] = incoming_subs[pid][0]["localizations"]
            else:
                replaced.append(sub)
        group["subscriptions"] = replaced

    groups_by_name = {
        str(g.get("referenceName") or "").strip(): g
        for g in local_n["subscriptionGroups"]
        if str(g.get("referenceName") or "").strip()
    }
    for pid in wanted:
        if pid in local_sub_ids or pid not in incoming_subs:
            continue
        group, sub = incoming_subs[pid]
        name = str(group.get("referenceName") or "").strip() or "Imported"
        merged_sub = dict(sub)
        _restore_screenshot(merged_sub, shots.get(pid))
        existing = groups_by_name.get(name)
        if existing is None:
            new_group = {
                "referenceName": name,
                "localizations": dict(group.get("localizations") or {}),
                "subscriptions": [merged_sub],
            }
            local_n["subscriptionGroups"].append(new_group)
            groups_by_name[name] = new_group
        else:
            existing.setdefault("subscriptions", []).append(merged_sub)

    return local_n
