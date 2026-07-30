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
from asc.reporting import TaskReporter


class RecordingSink:
    def __init__(self):
        self.logs = []
        self.progress_events = []

    def on_log(self, message, *, level="info"):
        self.logs.append((level, message))

    def on_progress(self, *, pct, msg, phase, phase_label, phase_index, phase_total):
        self.progress_events.append({
            "pct": pct,
            "msg": msg,
            "phase": phase,
            "phase_label": phase_label,
            "phase_index": phase_index,
            "phase_total": phase_total,
        })


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
    with pytest.raises(RuntimeError):
        _upload_screenshots_core(api, "app1", missing)
    assert api.calls == []


def test_upload_screenshots_no_editable_version_raises(tmp_path):
    class NoVersionAPI(ScreenshotFakeAPI):
        def get_editable_version(self, app_id):
            self.calls.append(("get_editable_version", app_id))
            return None

    api = NoVersionAPI()
    locale_dir = tmp_path / "en-US"
    locale_dir.mkdir()
    with pytest.raises(RuntimeError):
        _upload_screenshots_core(api, "app1", str(tmp_path))


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


def test_upload_screenshots_core_reports_progress_per_file(tmp_path):
    """2 locales × 3 files → upload phase ends at progress(6, 6)."""
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)

    class MultiLocaleAPI(ScreenshotFakeAPI):
        def get_version_localizations(self, version_id):
            return [
                {"id": "loc_en", "attributes": {"locale": "en-US"}},
                {"id": "loc_zh", "attributes": {"locale": "zh-Hans"}},
            ]

    for locale in ("en-US", "zh-Hans"):
        locale_dir = tmp_path / locale
        locale_dir.mkdir()
        for i in range(1, 4):
            _make_png(locale_dir / f"{i}.png", 1290, 2796)

    _upload_screenshots_core(
        MultiLocaleAPI(),
        "app1",
        str(tmp_path),
        dry_run=True,
        reporter=reporter,
    )

    phases = [e["phase"] for e in sink.progress_events]
    assert "scan" in phases
    assert "upload" in phases

    file_progress = [
        e
        for e in sink.progress_events
        if e["phase"] == "upload" and e["msg"].startswith("截图 ")
    ]
    assert len(file_progress) == 6
    assert file_progress[-1]["msg"] == "截图 6/6 文件"
    assert file_progress[-1]["pct"] == 100
    assert file_progress[0]["phase_index"] == 2
    assert file_progress[0]["phase_total"] == 2

    pcts = [e["pct"] for e in sink.progress_events]
    assert pcts == sorted(pcts)


def test_upload_screenshots_core_logs_summaries_via_reporter(tmp_path):
    """Key start / per-locale / end lines go to reporter.log (Web TaskStore path)."""
    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    locale_dir = tmp_path / "en-US"
    locale_dir.mkdir()
    _make_png(locale_dir / "1.png", 1290, 2796)

    _upload_screenshots_core(
        ScreenshotFakeAPI(),
        "app1",
        str(tmp_path),
        dry_run=True,
        reporter=reporter,
    )

    info_logs = [msg for level, msg in sink.logs if level == "info"]
    assert any("上传截图" in msg for msg in info_logs)
    assert any("locale: en-US" in msg or "文件夹:" in msg for msg in info_logs)
    assert any("截图上传完成" in msg for msg in info_logs)


def test_screenshots_source_has_no_progress_protocol():
    import asc.commands.screenshots as screenshots_mod

    src = Path(screenshots_mod.__file__).read_text(encoding="utf-8")
    assert "[PROGRESS:" not in src


def test_combined_metadata_and_screenshots_progress_is_monotonic(tmp_path):
    """Same reporter: combined phases, no mid-task done(), pct never decreases."""
    from asc.commands.metadata import _upload_metadata_core

    sink = RecordingSink()
    reporter = TaskReporter(sinks=[sink], verbose=False)
    reporter.set_phases([
        ("check", 5, "校验"),
        ("locales", 45, "元数据"),
        ("scan", 5, "扫描"),
        ("upload", 45, "截图"),
    ])

    class CombinedAPI(ScreenshotFakeAPI):
        def get_app_infos(self, app_id):
            return [{
                "id": "appinfo_1",
                "attributes": {"state": "PREPARE_FOR_SUBMISSION"},
                "relationships": {
                    "appStoreVersions": {"data": [{"id": self.version_id}]}
                },
            }]

        def get_app_info_localizations(self, app_info_id):
            return []

        def create_app_info_localization(self, app_info_id, locale, attrs):
            self.calls.append(("create_app_info_localization", locale))
            return {"id": f"info_{locale}"}

        def create_version_localization(self, version_id, locale, attrs):
            self.calls.append(("create_version_localization", locale))
            return {"id": f"ver_{locale}"}

        def update_app_info_localization(self, loc_id, attrs):
            self.calls.append(("update_app_info_localization", loc_id))

        def update_version_localization(self, loc_id, attrs):
            self.calls.append(("update_version_localization", loc_id))

        def get_version_localizations(self, version_id):
            return [
                {"id": "loc_en", "attributes": {"locale": "en-US"}},
                {"id": "loc_zh", "attributes": {"locale": "zh-Hans"}},
            ]

    api = CombinedAPI()
    locale_dir = tmp_path / "en-US"
    locale_dir.mkdir()
    for i in range(1, 3):
        _make_png(locale_dir / f"{i}.png", 1290, 2796)

    _upload_metadata_core(
        api,
        "app1",
        [
            {"locale": "en-US", "name": "Test", "description": "desc"},
            {"locale": "zh-Hans", "name": "测试", "description": "描述"},
        ],
        dry_run=True,
        reporter=reporter,
        manage_phases=False,
        finalize=False,
    )
    after_meta = sink.progress_events[-1]["pct"]
    assert after_meta < 100

    _upload_screenshots_core(
        api,
        "app1",
        str(tmp_path),
        dry_run=True,
        reporter=reporter,
        manage_phases=False,
        finalize=True,
    )
    pcts = [e["pct"] for e in sink.progress_events]
    assert pcts == sorted(pcts)
    assert pcts[-1] == 100
    assert any(e["phase"] == "upload" for e in sink.progress_events)
    assert after_meta <= pcts[-1]


def test_metadata_web_starter_screenshots_branch_uses_reporter():
    """Combined metadata+screenshots path must not drain [PROGRESS:] for screenshots."""
    import asc.web.routes_api as routes_api

    src = Path(routes_api.__file__).read_text(encoding="utf-8")
    start = src.index("def _start_metadata_task")
    end = src.index("def _start_build_task", start)
    starter = src[start:end]
    assert "_PROGRESS_RE" not in starter
    assert "capture_stdout_to_queue" not in starter
    assert "reporter=reporter" in starter
    assert "manage_phases=not combined" in starter
    assert "finalize=not combined" in starter
    assert "reporter._sinks" not in starter
