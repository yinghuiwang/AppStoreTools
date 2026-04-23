"""Tests for src/asc/commands/screenshots.py"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from asc.commands.screenshots import (
    _detect_display_type,
    _get_sorted_screenshots,
    _upload_screenshots_core,
)


def _make_png(path: Path, width: int, height: int):
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    img.save(str(path), "PNG")


class ScreenshotFakeAPI:
    def __init__(self):
        self.calls = []
        self.version_id = "ver_1"
        self.loc_id = "loc_en"

    def get_editable_version(self, app_id):
        return {
            "id": self.version_id,
            "attributes": {"versionString": "1.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
        }

    def get_version_localizations(self, version_id):
        return [{"id": self.loc_id, "attributes": {"locale": "en-US"}}]

    def get_screenshot_sets(self, localization_id):
        self.calls.append(("get_screenshot_sets", localization_id))
        return {"data": [], "included": []}

    def create_screenshot_set(self, localization_id, display_type):
        self.calls.append(("create_screenshot_set", localization_id, display_type))
        return {"data": {"id": "set_1"}}

    def get_screenshots_in_set(self, set_id):
        return []

    def delete_screenshot(self, screenshot_id):
        self.calls.append(("delete_screenshot", screenshot_id))

    def reserve_screenshot(self, set_id, filename, filesize):
        self.calls.append(("reserve_screenshot", set_id, filename, filesize))
        return {
            "data": {
                "id": "shot_1",
                "attributes": {"uploadOperations": []},
            }
        }

    def upload_screenshot_asset(self, upload_operations, file_path):
        self.calls.append(("upload_screenshot_asset",))

    def commit_screenshot(self, screenshot_id, checksum):
        self.calls.append(("commit_screenshot", screenshot_id))

    def get(self, path, **params):
        return {
            "data": {
                "attributes": {
                    "assetDeliveryState": {"state": "COMPLETE"}
                }
            }
        }


# ── _detect_display_type ──

def test_detect_known_iphone_67(tmp_path):
    img_path = tmp_path / "screen.png"
    _make_png(img_path, 1290, 2796)
    assert _detect_display_type(img_path) == "APP_IPHONE_67"


def test_detect_unknown_size_returns_none(tmp_path):
    img_path = tmp_path / "screen.png"
    _make_png(img_path, 100, 100)
    assert _detect_display_type(img_path) is None


def test_detect_landscape_iphone_67(tmp_path):
    img_path = tmp_path / "screen.png"
    _make_png(img_path, 2796, 1290)
    assert _detect_display_type(img_path) == "APP_IPHONE_67"


# ── _get_sorted_screenshots ──

def test_get_sorted_screenshots_numeric_order(tmp_path):
    for name in ["10.png", "1.png", "2.jpg"]:
        (tmp_path / name).write_bytes(b"")
    result = _get_sorted_screenshots(tmp_path)
    names = [f.name for f in result]
    assert names == ["1.png", "2.jpg", "10.png"]


def test_get_sorted_screenshots_filters_non_image(tmp_path):
    (tmp_path / "1.png").write_bytes(b"")
    (tmp_path / "readme.txt").write_bytes(b"")
    result = _get_sorted_screenshots(tmp_path)
    assert len(result) == 1
    assert result[0].name == "1.png"


# ── _upload_screenshots_core ──

def test_upload_screenshots_missing_dir(tmp_path):
    api = ScreenshotFakeAPI()
    missing = str(tmp_path / "nonexistent")
    _upload_screenshots_core(api, "app1", missing)
    assert api.calls == []


def test_upload_screenshots_dry_run(tmp_path):
    api = ScreenshotFakeAPI()
    locale_dir = tmp_path / "en-US"
    locale_dir.mkdir()
    _make_png(locale_dir / "1.png", 1290, 2796)

    _upload_screenshots_core(api, "app1", str(tmp_path), dry_run=True)
    write_calls = [c for c in api.calls if c[0] in (
        "create_screenshot_set", "reserve_screenshot", "commit_screenshot"
    )]
    assert write_calls == []


def test_upload_screenshots_happy_path(tmp_path):
    api = ScreenshotFakeAPI()
    locale_dir = tmp_path / "en-US"
    locale_dir.mkdir()
    _make_png(locale_dir / "1.png", 1290, 2796)

    with patch("time.sleep"):
        _upload_screenshots_core(api, "app1", str(tmp_path))

    call_names = [c[0] for c in api.calls]
    assert "create_screenshot_set" in call_names
    assert "reserve_screenshot" in call_names
    assert "commit_screenshot" in call_names


def test_upload_screenshots_en_us_fallback(tmp_path):
    en_dir = tmp_path / "en-US"
    en_dir.mkdir()
    _make_png(en_dir / "1.png", 1290, 2796)

    class FallbackAPI(ScreenshotFakeAPI):
        def get_version_localizations(self, version_id):
            return [
                {"id": "loc_en", "attributes": {"locale": "en-US"}},
                {"id": "loc_ja", "attributes": {"locale": "ja"}},
            ]

    api2 = FallbackAPI()
    with patch("time.sleep"):
        _upload_screenshots_core(api2, "app1", str(tmp_path))

    reserve_calls = [c for c in api2.calls if c[0] == "reserve_screenshot"]
    assert len(reserve_calls) == 2
