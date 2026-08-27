"""Read-only listing / IAP / screenshot facts for the Web Agent.

These helpers wrap existing snapshot loaders and validators. They never write
business files and do not resolve sandbox paths — callers pass already-resolved
paths.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from asc.iap.local import load_local_snapshot, validate_snapshot
from asc.iap.models import localization_map
from asc.listing.local import load_local_text_snapshot, scan_local_screenshots
from asc.listing.models import (
    DESCRIPTION_MAX,
    FIELD_NAMES,
    KEYWORDS_MAX,
    NAME_MAX,
    NAME_MIN,
    SUBTITLE_MAX,
)
from asc.web.agent_redact import redact_text

_URL_FIELDS = ("supportUrl", "marketingUrl", "privacyPolicyUrl")
_WARN_EMPTY_FIELDS = ("name", "keywords", "description", "supportUrl", "privacyPolicyUrl")
_COUNT_SPECS: dict[str, tuple[int, int | None]] = {
    "name": (NAME_MAX, 27),
    "subtitle": (SUBTITLE_MAX, 27),
    "keywords": (KEYWORDS_MAX, 90),
    "description": (DESCRIPTION_MAX, None),
}
_UNKNOWN_FILES_CAP = 20


def _as_path(path: str | Path) -> Path:
    return Path(path)


def _locale_codes(value: Any) -> list[str]:
    return list(localization_map(value))


def listing_snapshot(csv_path: str | Path) -> dict:
    target = _as_path(csv_path)
    if not target.is_file():
        return {"ok": True, "path": str(target), "exists": False, "locales": []}
    snap = load_local_text_snapshot(str(target))
    locales = [
        {
            "locale": loc.locale,
            "fields": {name: loc.fields.get(name, "") for name in FIELD_NAMES},
        }
        for loc in snap.locales
    ]
    return {"ok": True, "path": str(target), "exists": True, "locales": locales}


def iap_snapshot(json_path: str | Path) -> dict:
    target = _as_path(json_path)
    if not target.is_file():
        return {
            "ok": True,
            "path": str(target),
            "exists": False,
            "item_count": 0,
            "group_count": 0,
            "items": [],
            "subscriptionGroups": [],
        }
    try:
        snapshot, _mtime, _exists = load_local_snapshot(target)
    except (ValueError, OSError) as exc:
        return {"ok": False, "path": str(target), "exists": True, "error": redact_text(exc)}

    items = [
        {
            "productId": str(item.get("productId") or ""),
            "name": str(item.get("name") or ""),
            "inAppPurchaseType": str(item.get("inAppPurchaseType") or ""),
            "locales": _locale_codes(item.get("localizations")),
        }
        for item in snapshot.get("items") or []
        if isinstance(item, dict)
    ]
    groups: list[dict[str, Any]] = []
    for group in snapshot.get("subscriptionGroups") or []:
        if not isinstance(group, dict):
            continue
        subscriptions = [
            {
                "productId": str(sub.get("productId") or ""),
                "groupLevel": sub.get("groupLevel"),
                "subscriptionPeriod": str(sub.get("subscriptionPeriod") or ""),
                "locales": _locale_codes(sub.get("localizations")),
            }
            for sub in group.get("subscriptions") or []
            if isinstance(sub, dict)
        ]
        groups.append(
            {
                "referenceName": str(group.get("referenceName") or ""),
                "subscriptions": subscriptions,
            }
        )
    return {
        "ok": True,
        "path": str(target),
        "exists": True,
        "item_count": len(items),
        "group_count": len(groups),
        "items": items,
        "subscriptionGroups": groups,
    }


def validate_listing(csv_path: str | Path) -> dict:
    target = _as_path(csv_path)
    if not target.is_file():
        return {
            "ok": True,
            "path": str(target),
            "exists": False,
            "issues": [],
            "error_count": 0,
            "warning_count": 0,
        }
    snap = load_local_text_snapshot(str(target))
    issues: list[dict[str, str]] = []
    for loc in snap.locales:
        fields = loc.fields
        locale = loc.locale
        name = fields.get("name") or ""
        if name and not (NAME_MIN <= len(name) <= NAME_MAX):
            issues.append(
                {
                    "level": "error",
                    "locale": locale,
                    "field": "name",
                    "message": f"name must be {NAME_MIN}–{NAME_MAX} characters",
                }
            )
        subtitle = fields.get("subtitle") or ""
        if len(subtitle) > SUBTITLE_MAX:
            issues.append(
                {
                    "level": "error",
                    "locale": locale,
                    "field": "subtitle",
                    "message": f"subtitle must be ≤{SUBTITLE_MAX} characters",
                }
            )
        keywords = fields.get("keywords") or ""
        if len(keywords) > KEYWORDS_MAX:
            issues.append(
                {
                    "level": "error",
                    "locale": locale,
                    "field": "keywords",
                    "message": f"keywords must be ≤{KEYWORDS_MAX} characters",
                }
            )
        description = fields.get("description") or ""
        if len(description) > DESCRIPTION_MAX:
            issues.append(
                {
                    "level": "error",
                    "locale": locale,
                    "field": "description",
                    "message": f"description must be ≤{DESCRIPTION_MAX} characters",
                }
            )
        for url_field in _URL_FIELDS:
            value = fields.get(url_field) or ""
            if value and not value.startswith(("http://", "https://")):
                issues.append(
                    {
                        "level": "error",
                        "locale": locale,
                        "field": url_field,
                        "message": f"{url_field} must start with http:// or https://",
                    }
                )
        has_any = any((fields.get(field) or "").strip() for field in FIELD_NAMES)
        if has_any:
            for warn_field in _WARN_EMPTY_FIELDS:
                if not (fields.get(warn_field) or "").strip():
                    issues.append(
                        {
                            "level": "warning",
                            "locale": locale,
                            "field": warn_field,
                            "message": f"{warn_field} is empty",
                        }
                    )
    error_count = sum(1 for issue in issues if issue["level"] == "error")
    warning_count = sum(1 for issue in issues if issue["level"] == "warning")
    return {
        "ok": True,
        "path": str(target),
        "exists": True,
        "issues": issues,
        "error_count": error_count,
        "warning_count": warning_count,
    }


def validate_iap(json_path: str | Path) -> dict:
    target = _as_path(json_path)
    if not target.is_file():
        return {
            "ok": True,
            "path": str(target),
            "exists": False,
            "issues": [],
            "error_count": 0,
            "warning_count": 0,
        }
    try:
        snapshot, _mtime, _exists = load_local_snapshot(target)
    except (ValueError, OSError) as exc:
        return {"ok": False, "path": str(target), "exists": True, "error": redact_text(exc)}
    issues = [
        {
            "level": str(row.get("level") or "error"),
            "path": str(row.get("path") or ""),
            "message": str(row.get("message") or ""),
        }
        for row in validate_snapshot(snapshot, strict=False)
    ]
    return {
        "ok": True,
        "path": str(target),
        "exists": True,
        "issues": issues,
        "error_count": sum(1 for issue in issues if issue["level"] == "error"),
        "warning_count": sum(1 for issue in issues if issue["level"] == "warning"),
    }


def count_listing_fields(csv_path: str | Path) -> dict:
    target = _as_path(csv_path)
    if not target.is_file():
        return {"ok": True, "path": str(target), "exists": False, "locales": []}
    snap = load_local_text_snapshot(str(target))
    locales: list[dict[str, Any]] = []
    for loc in snap.locales:
        field_counts: dict[str, dict[str, Any]] = {}
        for field, (limit, target_len) in _COUNT_SPECS.items():
            length = len(loc.fields.get(field) or "")
            info: dict[str, Any] = {
                "length": length,
                "limit": limit,
                "over_limit": length > limit,
            }
            if target_len is not None:
                info["target"] = target_len
                info["over_target"] = length > target_len
            field_counts[field] = info
        locales.append({"locale": loc.locale, "fields": field_counts})
    return {"ok": True, "path": str(target), "exists": True, "locales": locales}


def inspect_screenshots(screenshots_dir: str | Path) -> dict:
    target = _as_path(screenshots_dir)
    if not target.is_dir():
        return {"ok": True, "path": str(target), "exists": False, "locales": []}
    scanned = scan_local_screenshots(str(target))
    locales: list[dict[str, Any]] = []
    for locale, by_type in scanned.items():
        types = {display_type: len(items) for display_type, items in by_type.items()}
        unknown_items = by_type.get("UNKNOWN") or []
        locales.append(
            {
                "locale": locale,
                "types": types,
                "unknown_files": [item.file_name for item in unknown_items[:_UNKNOWN_FILES_CAP]],
                "file_count": sum(types.values()),
            }
        )
    return {"ok": True, "path": str(target), "exists": True, "locales": locales}
