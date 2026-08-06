"""Load App Store Connect listing text into a `ListingSnapshot`."""
from __future__ import annotations

from asc.commands.metadata import _select_app_info_id
from asc.listing.models import FIELD_NAMES, ListingSnapshot, LocaleListing

# App Info localization fields (name / subtitle / privacy URL).
_INFO_FIELDS = ("name", "subtitle", "privacyPolicyUrl")
# Version localization fields (description / keywords / URLs).
_VERSION_FIELDS = ("description", "keywords", "supportUrl", "marketingUrl")


class NoEditableVersionError(RuntimeError):
    """Raised when App Store Connect has no version in an editable state."""


class NoAppInfoError(RuntimeError):
    """Raised when the app has no App Info records."""


def load_asc_text_snapshot(api, app_id: str) -> ListingSnapshot:
    """Fetch editable-version + App Info localizations into an ASC text snapshot.

    Screenshots are left empty (`{}`); Task 8 fills them via a separate attach step.
    Reuses `metadata._select_app_info_id` so App Info selection matches upload.
    """
    version = api.get_editable_version(app_id)
    if not version:
        raise NoEditableVersionError("No editable version")

    version_id = version["id"]
    attrs = version.get("attributes") or {}
    version_string = attrs.get("versionString", "")
    version_state = attrs.get("appStoreState") or attrs.get("appVersionState", "")

    app_infos = api.get_app_infos(app_id)
    if not app_infos:
        raise NoAppInfoError("No App Info")
    app_info_id = _select_app_info_id(app_infos, version_id, version_state)

    info_locs = api.get_app_info_localizations(app_info_id) or []
    ver_locs = api.get_version_localizations(version_id) or []

    by_locale: dict[str, dict[str, str]] = {}

    def _ensure(locale: str) -> dict[str, str]:
        if locale not in by_locale:
            by_locale[locale] = {name: "" for name in FIELD_NAMES}
        return by_locale[locale]

    for loc in info_locs:
        loc_attrs = loc.get("attributes") or {}
        locale = loc_attrs.get("locale")
        if not locale:
            continue
        fields = _ensure(locale)
        for name in _INFO_FIELDS:
            val = loc_attrs.get(name)
            fields[name] = "" if val is None else str(val)

    for loc in ver_locs:
        loc_attrs = loc.get("attributes") or {}
        locale = loc_attrs.get("locale")
        if not locale:
            continue
        fields = _ensure(locale)
        for name in _VERSION_FIELDS:
            val = loc_attrs.get(name)
            fields[name] = "" if val is None else str(val)

    locales = [
        LocaleListing(locale=locale, fields=fields, screenshots={})
        for locale, fields in sorted(by_locale.items())
    ]
    return ListingSnapshot(
        source="asc",
        locales=locales,
        version={
            "id": version_id,
            "versionString": version_string,
            "appStoreState": version_state,
        },
    )
