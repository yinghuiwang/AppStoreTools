from __future__ import annotations
from dataclasses import dataclass, field

FIELD_NAMES = (
    "name", "subtitle", "privacyPolicyUrl",
    "description", "keywords", "supportUrl", "marketingUrl",
)

NAME_MIN = 2
NAME_MAX = 30
SUBTITLE_MAX = 30
KEYWORDS_MAX = 100
DESCRIPTION_MAX = 4000
TEXT_FIELDS = ("name", "subtitle", "keywords", "description")


def empty_fields() -> dict[str, str]:
    return {name: "" for name in FIELD_NAMES}


def empty_locale(locale: str) -> LocaleListing:
    return LocaleListing(locale=locale, fields=empty_fields(), screenshots={})


def snapshot_has_content(snapshot: ListingSnapshot | None) -> bool:
    if snapshot is None:
        return False
    return any(True for _ in snapshot.locales)

@dataclass
class ScreenshotItem:
    file_name: str
    order: int
    thumb_url: str = ""
    local_path: str = ""
    remote_id: str = ""

@dataclass
class LocaleListing:
    locale: str
    fields: dict[str, str]
    screenshots: dict[str, list[ScreenshotItem]] = field(default_factory=dict)

@dataclass
class ListingSnapshot:
    source: str
    locales: list[LocaleListing]
    version: dict | None = None

@dataclass
class FieldDiff:
    field: str
    status: str
    local: str
    asc: str

@dataclass
class ScreenshotTypeDiff:
    display_type: str
    local: list[ScreenshotItem]
    asc: list[ScreenshotItem]

@dataclass
class LocaleDiff:
    locale: str
    fields: list[FieldDiff]
    screenshots: list[ScreenshotTypeDiff]

@dataclass
class ListingDiff:
    locales: list[LocaleDiff]
