from __future__ import annotations
from dataclasses import dataclass, field

FIELD_NAMES = (
    "name", "subtitle", "privacyPolicyUrl",
    "description", "keywords", "supportUrl", "marketingUrl",
)

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
