"""Shared Web profile snapshot for Jinja pages and GET /api/bootstrap."""
from __future__ import annotations

from typing import Any


def load_web_profile_state(cookie_profile: str | None) -> dict[str, Any]:
    from asc.config import Config
    from asc.guard import Guard
    from asc.web.profile_select import resolve_web_current_profile

    config = Config(app_name=cookie_profile or None)
    profiles = config.list_apps()
    profile_data = {name: config.get_app_profile(name) or {} for name in profiles}
    access = Guard().profile_access(profile_data)
    options = access["options"]
    current = resolve_web_current_profile(
        cookie_profile=cookie_profile,
        profiles=profiles,
        matched_profile=access["matched_profile"],
        options=options,
    )
    if current:
        current_config = Config(app_name=current)
        csv_path = current_config.csv_path
        screenshots_path = current_config.screenshots_path
        iap_path = current_config.iap_path or "data/iap_packages.json"
    else:
        csv_path = "data/appstore_info.csv"
        screenshots_path = "data/screenshots"
        iap_path = "data/iap_packages.json"
    return {
        "profiles": profiles,
        "profile_access": options,
        "has_machine_profile": bool(access["matched_profile"]),
        "current_profile": current or "",
        "paths": {
            "csv": csv_path,
            "screenshots": screenshots_path,
            "iap": iap_path,
        },
    }


def apply_profile_cookie(response: Any, *, cookie: str, current: str) -> None:
    if cookie == current:
        return
    if current:
        response.set_cookie("asc_profile", current, httponly=True, samesite="lax")
    elif cookie:
        response.delete_cookie("asc_profile")
