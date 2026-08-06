"""Tests for screenshot display-type grouping and scope filtering."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from asc.commands.screenshots import _filter_screenshot_jobs, _group_files_by_display_type


def test_group_files_by_display_type(tmp_path: Path):
    folder = tmp_path / "en-US"
    folder.mkdir()
    Image.new("RGB", (1290, 2796)).save(folder / "01_phone.png")
    Image.new("RGB", (2048, 2732)).save(folder / "01_pad.png")  # iPad 12.9
    groups = _group_files_by_display_type(folder)
    assert "APP_IPHONE_67" in groups
    assert "APP_IPAD_PRO_3GEN_129" in groups


def test_filter_scopes_keeps_matching_only():
    jobs = [
        ("en-US", "APP_IPHONE_67", [Path("a.png"), Path("b.png")]),
        ("zh-Hans", "APP_IPHONE_67", [Path("c.png")]),
    ]
    scopes = [{"locale": "en-US", "display_type": "APP_IPHONE_67", "file_names": ["b.png"]}]
    out = _filter_screenshot_jobs(jobs, scopes)
    assert len(out) == 1
    assert out[0][0] == "en-US"
    assert [p.name for p in out[0][2]] == ["b.png"]
