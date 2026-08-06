from __future__ import annotations

from asc.listing.diff import diff_snapshots
from asc.listing.models import ListingSnapshot, LocaleListing, ScreenshotItem


def _snap(source, locales):
    return ListingSnapshot(source=source, locales=locales)


def test_field_equal_and_changed():
    local = _snap("local", [
        LocaleListing("en-US", {"name": "A", "description": "x"}, {}),
    ])
    asc = _snap("asc", [
        LocaleListing("en-US", {"name": "A", "description": "y"}, {}),
    ])
    d = diff_snapshots(local, asc)
    by = {f.field: f for f in d.locales[0].fields}
    assert by["name"].status == "equal"
    assert by["description"].status == "changed"
    assert by["description"].local == "x"
    assert by["description"].asc == "y"


def test_empty_and_missing_are_equal():
    local = _snap("local", [LocaleListing("en-US", {"name": ""}, {})])
    asc = _snap("asc", [LocaleListing("en-US", {}, {})])
    d = diff_snapshots(local, asc)
    by = {f.field: f for f in d.locales[0].fields}
    assert by["name"].status == "equal"


def test_local_only_and_asc_only_locale():
    local = _snap("local", [LocaleListing("zh-Hans", {"name": "中"}, {})])
    asc = _snap("asc", [LocaleListing("ja", {"name": "日"}, {})])
    d = diff_snapshots(local, asc)
    locales = {x.locale: x for x in d.locales}
    assert "zh-Hans" in locales and "ja" in locales
    zh = {f.field: f for f in locales["zh-Hans"].fields}
    assert zh["name"].status == "local_only"
    ja = {f.field: f for f in locales["ja"].fields}
    assert ja["name"].status == "asc_only"


def test_screenshot_type_side_by_side_no_equality():
    local = _snap("local", [
        LocaleListing("en-US", {}, {
            "APP_IPHONE_67": [ScreenshotItem("01_a.png", 1, local_path="/a")],
        }),
    ])
    asc = _snap("asc", [
        LocaleListing("en-US", {}, {
            "APP_IPHONE_67": [ScreenshotItem("x.png", 1, remote_id="s1")],
            "APP_IPHONE_65": [ScreenshotItem("y.png", 1, remote_id="s2")],
        }),
    ])
    d = diff_snapshots(local, asc)
    types = {s.display_type: s for s in d.locales[0].screenshots}
    assert len(types["APP_IPHONE_67"].local) == 1
    assert len(types["APP_IPHONE_67"].asc) == 1
    assert len(types["APP_IPHONE_65"].local) == 0
    assert len(types["APP_IPHONE_65"].asc) == 1
