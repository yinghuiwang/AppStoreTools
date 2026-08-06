from __future__ import annotations
from asc.listing.models import (
    FIELD_NAMES, FieldDiff, ListingDiff, ListingSnapshot,
    LocaleDiff, LocaleListing, ScreenshotTypeDiff,
)

def _norm(v: str | None) -> str:
    return (v or "").strip()

def _field_status(local: str, asc: str) -> str:
    l, a = _norm(local), _norm(asc)
    if not l and not a:
        return "equal"
    if l and not a:
        return "local_only"
    if a and not l:
        return "asc_only"
    if l == a:
        return "equal"
    return "changed"

def diff_snapshots(local: ListingSnapshot, asc: ListingSnapshot) -> ListingDiff:
    local_map = {x.locale: x for x in local.locales}
    asc_map = {x.locale: x for x in asc.locales}
    locales = sorted(set(local_map) | set(asc_map))
    out: list[LocaleDiff] = []
    for loc in locales:
        lm = local_map.get(loc) or LocaleListing(loc, {}, {})
        am = asc_map.get(loc) or LocaleListing(loc, {}, {})
        fields = [
            FieldDiff(
                field=f,
                status=_field_status(lm.fields.get(f, ""), am.fields.get(f, "")),
                local=_norm(lm.fields.get(f, "")),
                asc=_norm(am.fields.get(f, "")),
            )
            for f in FIELD_NAMES
        ]
        types = sorted(set(lm.screenshots) | set(am.screenshots))
        shots = [
            ScreenshotTypeDiff(
                display_type=t,
                local=list(lm.screenshots.get(t, [])),
                asc=list(am.screenshots.get(t, [])),
            )
            for t in types
        ]
        out.append(LocaleDiff(locale=loc, fields=fields, screenshots=shots))
    return ListingDiff(locales=out)
