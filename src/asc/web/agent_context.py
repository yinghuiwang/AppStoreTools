"""Sanitize and format per-turn page_context for the Agent system prompt."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from asc.listing.models import FIELD_NAMES
from asc.web.agent_redact import redact_text
from asc.web.agent_workspace import _has_dotdot, is_blocked_workspace_path

_ACCEPTED_KEYS = (
    "route",
    "profile",
    "locale",
    "product_id",
    "phase",
    "csv_path",
    "iap_path",
    "screenshots_path",
    "fields",
)
_LIMITS = {
    "route": 64,
    "profile": 64,
    "locale": 16,
    "product_id": 128,
    "phase": 32,
    "csv_path": 512,
    "iap_path": 512,
    "screenshots_path": 512,
}
_PATH_KEYS = frozenset({"csv_path", "iap_path", "screenshots_path"})
_FIELD_ALLOW = frozenset(FIELD_NAMES) | {"whatsNew"}
_FIELD_VALUE_MAX = 200
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)(?:^|[^\w.])(?:issuer_id|key_id|api_key|password|token)\s*="
)
_FORMAT_LABELS = {
    "csv_path": "csv",
    "iap_path": "iap",
    "screenshots_path": "screenshots",
}


def _looks_secret(text: str) -> bool:
    lowered = text.lower()
    if ".p8" in lowered or _SECRET_ASSIGN_RE.search(text):
        return True
    return redact_text(text) != text


def _clean_str(value: Any, *, max_len: int, is_path: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or len(text) > max_len:
        return None
    if _looks_secret(text):
        return None
    if is_path:
        if _has_dotdot(text):
            return None
        try:
            if is_blocked_workspace_path(Path(text)):
                return None
        except Exception:
            return None
    return text


def _sanitize_fields(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    fields: dict[str, str] = {}
    for name, raw in value.items():
        key = str(name)
        if key not in _FIELD_ALLOW or _looks_secret(key):
            continue
        text = _clean_str(raw, max_len=_FIELD_VALUE_MAX)
        if text is not None:
            fields[key] = text
    return fields


def sanitize_page_context(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in _ACCEPTED_KEYS:
        if key not in raw or _looks_secret(key):
            continue
        value = raw[key]
        if key == "fields":
            cleaned = _sanitize_fields(value)
            if cleaned:
                out["fields"] = cleaned
            continue
        text = _clean_str(value, max_len=_LIMITS[key], is_path=key in _PATH_KEYS)
        if text is not None:
            out[key] = text
    return out


def _one_line(value: Any) -> str:
    return str(value).replace("\n", " ").replace("\r", " ").strip()


def format_page_context(ctx: dict, lang: str) -> str:
    if not ctx:
        return ""
    parts: list[str] = []
    for key in _ACCEPTED_KEYS:
        if key not in ctx:
            continue
        if key == "fields":
            fields = ctx.get("fields")
            if isinstance(fields, dict) and fields:
                bits = [f"{name}={_one_line(val)}" for name, val in fields.items()]
                parts.append("fields=" + ",".join(bits))
            continue
        parts.append(f"{_FORMAT_LABELS.get(key, key)}={_one_line(ctx[key])}")
    if not parts:
        return ""
    return "[page] " + " ".join(parts)
