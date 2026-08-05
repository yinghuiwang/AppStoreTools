"""Resolve the Web UI "current App" selection.

Auto-select only when Guard reports a machine-matched profile. Never fall back
to ``default_app`` or the first selectable profile.
"""
from __future__ import annotations

from typing import Mapping, Sequence


def resolve_web_current_profile(
    *,
    cookie_profile: str | None,
    profiles: Sequence[str],
    matched_profile: str | None,
    options: Mapping[str, Mapping[str, object]],
) -> str:
    """Return the profile that should be treated as currently selected.

    Priority:
    1. Cookie value, if it names a selectable profile (explicit user choice)
    2. Guard ``matched_profile`` (this machine's bound app)
    3. Empty string — no default_app / first-item fallback
    """
    selectable = {
        name
        for name in profiles
        if options.get(name, {}).get("enabled", True)
    }
    cookie = (cookie_profile or "").strip()
    if cookie and cookie in selectable:
        return cookie
    matched = (matched_profile or "").strip()
    if matched and matched in selectable:
        return matched
    return ""
