from __future__ import annotations

import importlib.resources
import json
from pathlib import Path
from typing import Any


class LocaleCatalogError(Exception):
    """Raised when the static App Store Connect locale catalog cannot be loaded."""


def _default_catalog_resource():
    return importlib.resources.files("asc").joinpath("data/asc_locales.json")


def _read_text(path: str | Path | None) -> str:
    if path is None:
        resource = _default_catalog_resource()
        try:
            return resource.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise LocaleCatalogError("locale catalog is unavailable") from exc
    catalog_path = Path(path)
    try:
        return catalog_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError) as exc:
        raise LocaleCatalogError("locale catalog is unavailable") from exc


def _require_nonempty_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise LocaleCatalogError(f"locale field {field} must be a string")
    text = value.strip()
    if not text:
        raise LocaleCatalogError(f"locale field {field} must be non-empty")
    return text


def list_locales(path: str | Path | None = None) -> list[dict[str, str]]:
    raw = _read_text(path)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LocaleCatalogError("locale catalog is not valid JSON") from exc
    if not isinstance(payload, list):
        raise LocaleCatalogError("locale catalog root must be a list")

    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            raise LocaleCatalogError("locale catalog entries must be objects")
        code = _require_nonempty_str(entry.get("code"), "code")
        name_en = _require_nonempty_str(entry.get("name_en"), "name_en")
        name_zh = _require_nonempty_str(entry.get("name_zh"), "name_zh")
        if code in seen:
            raise LocaleCatalogError(f"duplicate locale code: {code}")
        seen.add(code)
        items.append({"code": code, "name_en": name_en, "name_zh": name_zh})
    return items


def filter_locales(query: str, items: list[dict[str, str]]) -> list[dict[str, str]]:
    q = (query or "").strip().casefold()
    if not q:
        matched = list(items)
    else:
        matched = []
        for item in items:
            haystacks = (
                str(item.get("code") or ""),
                str(item.get("name_en") or ""),
                str(item.get("name_zh") or ""),
            )
            if any(q in field.casefold() for field in haystacks):
                matched.append(item)
    return sorted(matched, key=lambda row: row["code"])
