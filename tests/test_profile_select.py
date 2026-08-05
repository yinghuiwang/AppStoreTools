"""Tests for Web current-app selection rules."""
from __future__ import annotations

from asc.web.profile_select import resolve_web_current_profile


def _opts(*enabled_names: str, disabled: dict[str, dict] | None = None) -> dict:
    options = {name: {"enabled": True} for name in enabled_names}
    if disabled:
        options.update(disabled)
    return options


def test_resolve_prefers_selectable_cookie():
    assert (
        resolve_web_current_profile(
            cookie_profile="alpha",
            profiles=["alpha", "beta"],
            matched_profile="beta",
            options=_opts("alpha", "beta"),
        )
        == "alpha"
    )


def test_resolve_uses_matched_when_cookie_missing():
    assert (
        resolve_web_current_profile(
            cookie_profile=None,
            profiles=["alpha", "beta"],
            matched_profile="beta",
            options=_opts("alpha", "beta"),
        )
        == "beta"
    )


def test_resolve_uses_matched_when_cookie_not_selectable():
    assert (
        resolve_web_current_profile(
            cookie_profile="other",
            profiles=["current", "other"],
            matched_profile="current",
            options={
                "current": {"enabled": True},
                "other": {"enabled": False},
            },
        )
        == "current"
    )


def test_resolve_empty_without_match_ignores_default_and_first():
    """No machine match and no valid cookie → unselected (no first/default fallback)."""
    assert (
        resolve_web_current_profile(
            cookie_profile=None,
            profiles=["alpha", "beta"],
            matched_profile="",
            options=_opts("alpha", "beta"),
        )
        == ""
    )


def test_resolve_empty_when_guard_disabled_and_no_cookie():
    assert (
        resolve_web_current_profile(
            cookie_profile="",
            profiles=["only-app"],
            matched_profile="",
            options=_opts("only-app"),
        )
        == ""
    )


def test_resolve_ignores_matched_outside_selectable():
    assert (
        resolve_web_current_profile(
            cookie_profile=None,
            profiles=["alpha"],
            matched_profile="ghost",
            options=_opts("alpha"),
        )
        == ""
    )
