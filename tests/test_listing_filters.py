# tests/test_listing_filters.py
"""Unit tests for asc.listing.filters.filter_metadata_rows."""
from __future__ import annotations

from asc.listing.filters import filter_metadata_rows


def test_filter_by_locale_and_fields():
    rows = [
        {"locale": "en-US", "name": "A", "keywords": "k", "description": "d"},
        {"locale": "zh-Hans", "name": "中", "keywords": "词"},
    ]
    out = filter_metadata_rows(
        rows,
        locales=["en-US"],
        fields_by_locale={"en-US": ["name", "keywords"]},
    )
    assert out == [{"locale": "en-US", "name": "A", "keywords": "k"}]


def test_missing_fields_entry_skips_locale():
    rows = [{"locale": "en-US", "name": "A"}, {"locale": "ja", "name": "J"}]
    out = filter_metadata_rows(rows, locales=["en-US", "ja"], fields_by_locale={"en-US": ["name"]})
    assert out == [{"locale": "en-US", "name": "A"}]


def test_empty_locales_does_not_filter_by_locale():
    rows = [{"locale": "en-US", "name": "A"}, {"locale": "ja", "name": "J"}]
    out = filter_metadata_rows(rows, locales=[], fields_by_locale=None)
    assert out == rows


def test_none_locales_does_not_filter_by_locale():
    rows = [{"locale": "en-US", "name": "A"}, {"locale": "ja", "name": "J"}]
    out = filter_metadata_rows(rows, locales=None, fields_by_locale=None)
    assert out == rows


def test_fields_by_locale_none_keeps_all_fields():
    rows = [{"locale": "en-US", "name": "A", "keywords": "k"}]
    out = filter_metadata_rows(rows, locales=None, fields_by_locale=None)
    assert out == rows


def test_empty_field_list_skips_locale_entirely():
    rows = [{"locale": "en-US", "name": "A"}, {"locale": "ja", "name": "J"}]
    out = filter_metadata_rows(
        rows,
        locales=None,
        fields_by_locale={"en-US": [], "ja": ["name"]},
    )
    assert out == [{"locale": "ja", "name": "J"}]


def test_row_without_locale_is_dropped():
    rows = [{"name": "A"}, {"locale": "en-US", "name": "B"}]
    out = filter_metadata_rows(rows, locales=None, fields_by_locale=None)
    assert out == [{"locale": "en-US", "name": "B"}]
