"""Load App Store Connect listing text/screenshots into a `ListingSnapshot`."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests

from asc.commands.metadata import _select_app_info_id
from asc.listing.local import (
    PathTraversalError,
    _assert_under_root,
    _safe_locale_name,
    find_locale_screenshot_dir,
)
from asc.listing.models import FIELD_NAMES, ListingSnapshot, LocaleListing, ScreenshotItem

# App Info localization fields (name / subtitle / privacy URL).
_INFO_FIELDS = ("name", "subtitle", "privacyPolicyUrl")
# Version localization fields (description / keywords / URLs).
_VERSION_FIELDS = ("description", "keywords", "supportUrl", "marketingUrl")

_ASSET_TIMEOUT = (10, 120)
_ORDER_PREFIX_RE = re.compile(r"^\d+_")


class NoEditableVersionError(RuntimeError):
    """Raised when App Store Connect has no version in an editable state."""


class NoAppInfoError(RuntimeError):
    """Raised when the app has no App Info records."""


def load_asc_text_snapshot(api, app_id: str) -> ListingSnapshot:
    """Fetch editable-version + App Info localizations into an ASC text snapshot.

    Screenshots are left empty (`{}`); call `attach_asc_screenshots` to fill them.
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


def screenshot_thumb_url(shot_attrs: dict) -> str:
    """Build a small preview URL from ASC `imageAsset.templateUrl`.

    Replaces `{w}` / `{h}` with `100`. Also fills `{f}` with `png` when present.
    """
    asset = (shot_attrs or {}).get("imageAsset") or {}
    template = asset.get("templateUrl") or ""
    if not template:
        return ""
    url = template.replace("{w}", "100").replace("{h}", "100")
    if "{f}" in url:
        url = url.replace("{f}", "png")
    return url


def _full_image_url(shot_attrs: dict) -> str:
    """Resolve a full-resolution download URL from screenshot attributes."""
    asset = (shot_attrs or {}).get("imageAsset") or {}
    template = asset.get("templateUrl") or ""
    if not template:
        return ""
    width = asset.get("width") or 0
    height = asset.get("height") or 0
    if width and height:
        url = template.replace("{w}", str(width)).replace("{h}", str(height))
    else:
        # Large fallback when dimensions are missing from the list payload.
        url = template.replace("{w}", "2000").replace("{h}", "2000")
    if "{f}" in url:
        # Prefer original extension from fileName when available.
        file_name = (shot_attrs or {}).get("fileName") or ""
        ext = Path(file_name).suffix.lstrip(".").lower() or "png"
        if ext == "jpeg":
            ext = "jpg"
        url = url.replace("{f}", ext if ext in ("png", "jpg") else "png")
    return url


def _included_screenshots(sets_resp: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in sets_resp.get("included") or []:
        if item.get("type") == "appScreenshots" and item.get("id"):
            out[item["id"]] = item
    return out


def _ordered_shot_ids(set_resource: dict) -> list[str]:
    rel = (set_resource.get("relationships") or {}).get("appScreenshots") or {}
    data = rel.get("data") or []
    ids: list[str] = []
    for ref in data:
        if isinstance(ref, dict) and ref.get("id"):
            ids.append(ref["id"])
    return ids


def _shots_for_set(api, set_resource: dict, included: dict[str, dict]) -> list[dict]:
    """Return ordered screenshot resources for one set (included first, else API)."""
    ordered_ids = _ordered_shot_ids(set_resource)
    if ordered_ids:
        shots: list[dict] = []
        missing = False
        for sid in ordered_ids:
            shot = included.get(sid)
            if shot is None:
                missing = True
                break
            shots.append(shot)
        if not missing:
            return shots

    set_id = set_resource.get("id")
    if not set_id:
        return []
    listed = api.get_screenshots_in_set(set_id) or []
    if ordered_ids:
        by_id = {s.get("id"): s for s in listed if s.get("id")}
        return [by_id[sid] for sid in ordered_ids if sid in by_id]
    return list(listed)


def attach_asc_screenshots(api, snapshot: ListingSnapshot) -> ListingSnapshot:
    """Fill `snapshot.locales[*].screenshots` from ASC screenshot sets.

    Looks up version localization ids via `get_version_localizations`, then
    `get_screenshot_sets` (with included `appScreenshots`) per localization.
    Mutates and returns the same snapshot instance.
    """
    version = snapshot.version or {}
    version_id = version.get("id")
    if not version_id:
        return snapshot

    ver_locs = api.get_version_localizations(version_id) or []
    loc_id_by_locale = {
        (loc.get("attributes") or {}).get("locale"): loc.get("id")
        for loc in ver_locs
        if (loc.get("attributes") or {}).get("locale") and loc.get("id")
    }

    for loc in snapshot.locales:
        loc_id = loc_id_by_locale.get(loc.locale)
        if not loc_id:
            loc.screenshots = {}
            continue
        sets_resp = api.get_screenshot_sets(loc_id) or {}
        included = _included_screenshots(sets_resp)
        by_type: dict[str, list[ScreenshotItem]] = {}
        for set_resource in sets_resp.get("data") or []:
            attrs = set_resource.get("attributes") or {}
            display_type = attrs.get("screenshotDisplayType")
            if not display_type:
                continue
            items: list[ScreenshotItem] = []
            for order, shot in enumerate(_shots_for_set(api, set_resource, included), start=1):
                shot_attrs = shot.get("attributes") or {}
                items.append(
                    ScreenshotItem(
                        file_name=str(shot_attrs.get("fileName") or f"screenshot_{order}.png"),
                        order=order,
                        thumb_url=screenshot_thumb_url(shot_attrs),
                        local_path="",
                        remote_id=str(shot.get("id") or ""),
                    )
                )
            by_type[display_type] = items
        loc.screenshots = by_type
    return snapshot


def _resolve_screenshot_attrs(api, shot: dict) -> dict:
    """Return attributes, fetching screenshot detail when imageAsset is missing."""
    attrs = dict(shot.get("attributes") or {})
    asset = attrs.get("imageAsset") or {}
    if asset.get("templateUrl"):
        return attrs
    shot_id = shot.get("id")
    if not shot_id:
        return attrs
    detail = api.get(f"/v1/appScreenshots/{shot_id}")
    detail_attrs = ((detail or {}).get("data") or {}).get("attributes") or {}
    merged = {**attrs, **detail_attrs}
    return merged


def _fetch_image_bytes(api, shot: dict) -> bytes:
    attrs = _resolve_screenshot_attrs(api, shot)
    url = _full_image_url(attrs)
    if not url:
        raise RuntimeError(f"No download URL for screenshot {shot.get('id')}")
    resp = requests.get(url, timeout=_ASSET_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def _safe_download_name(file_name: str, index: int) -> str:
    raw = Path(file_name or f"screenshot_{index}.png").name
    stem = Path(raw).stem
    suffix = Path(raw).suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg"):
        suffix = ".png"
    stem = _ORDER_PREFIX_RE.sub("", stem)
    stem = re.sub(r"[^\w.\-]+", "_", stem).strip("._") or f"screenshot_{index}"
    return f"{index:02d}_{stem}{suffix}"


def _delete_local_display_type(locale_dir: Path, display_type: str) -> None:
    from asc.commands.screenshots import _detect_display_type, _get_sorted_screenshots

    if not locale_dir.exists():
        return
    for path in _get_sorted_screenshots(locale_dir):
        detected = _detect_display_type(path)
        if detected == display_type:
            path.unlink(missing_ok=True)


def _resolve_pull_locale_dir(screenshots_dir: str, locale: str) -> Path:
    """Resolve the local folder for an ASC locale, preferring an existing mapped dir.

    Uses `find_locale_screenshot_dir` so aliases like `en/` → `en-US` stay in place.
    Creates `root / <ASC-locale>` only when no mapped folder exists. Always asserts
    the result lies under `screenshots_dir`.
    """
    safe = _safe_locale_name(locale)
    existing = find_locale_screenshot_dir(screenshots_dir, safe)
    if existing is not None:
        locale_dir = existing
    else:
        locale_dir = Path(screenshots_dir) / safe
        locale_dir.mkdir(parents=True, exist_ok=True)
    return _assert_under_root(screenshots_dir, locale_dir)


def download_asc_screenshots(
    api,
    app_id: str,
    screenshots_dir: str,
    scopes: list[dict],
    reporter: Any = None,
) -> None:
    """Download ASC screenshots for each `(locale, display_type)` scope.

    For each scope: resolve the local folder that Diff/scan maps to the ASC
    locale (keep existing mapped names like `en/`), delete files of that
    displayType there, then write `01_*.png` … in online order.
    """
    version = api.get_editable_version(app_id)
    if not version:
        raise NoEditableVersionError("No editable version")
    version_id = version["id"]
    ver_locs = api.get_version_localizations(version_id) or []
    loc_id_by_locale = {
        (loc.get("attributes") or {}).get("locale"): loc.get("id")
        for loc in ver_locs
        if (loc.get("attributes") or {}).get("locale") and loc.get("id")
    }

    base = Path(screenshots_dir)
    base.mkdir(parents=True, exist_ok=True)

    total = max(len(scopes), 1)
    for idx, scope in enumerate(scopes):
        locale = (scope or {}).get("locale")
        display_type = (scope or {}).get("display_type")
        if not locale or not display_type:
            continue
        if reporter is not None:
            reporter.log(f"⬇️  {locale} / {display_type}")
            try:
                reporter.progress(idx, total, f"{locale} {display_type}")
            except Exception:
                pass

        loc_id = loc_id_by_locale.get(locale)
        if not loc_id:
            if reporter is not None:
                reporter.log(f"⚠️  跳过 {locale}：无版本本地化")
            continue

        sets_resp = api.get_screenshot_sets(loc_id) or {}
        included = _included_screenshots(sets_resp)
        set_resource = None
        for candidate in sets_resp.get("data") or []:
            attrs = candidate.get("attributes") or {}
            if attrs.get("screenshotDisplayType") == display_type:
                set_resource = candidate
                break
        if set_resource is None:
            if reporter is not None:
                reporter.log(f"⚠️  跳过 {locale}/{display_type}：线上无该设备类型")
            continue

        shots = _shots_for_set(api, set_resource, included)
        try:
            locale_dir = _resolve_pull_locale_dir(screenshots_dir, locale)
        except PathTraversalError as e:
            if reporter is not None:
                reporter.log(f"⚠️  跳过 {locale}：{e}")
            continue

        _delete_local_display_type(locale_dir, display_type)

        for order, shot in enumerate(shots, start=1):
            attrs = shot.get("attributes") or {}
            name = _safe_download_name(str(attrs.get("fileName") or ""), order)
            target = _assert_under_root(screenshots_dir, locale_dir / name)
            data = _fetch_image_bytes(api, shot)
            target.write_bytes(data)
            if reporter is not None:
                reporter.log(f"  ✓ {locale_dir.name}/{name}")

    if reporter is not None:
        try:
            reporter.progress(total, total, "done")
        except Exception:
            pass
