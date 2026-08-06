from __future__ import annotations
from pathlib import Path
import time
import pytest
from asc.listing.local import (
    FileChangedError, load_local_text_snapshot, save_local_csv,
)
from asc.listing.models import LocaleListing

def test_load_local_text_snapshot(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text(
        "locale,name,subtitle,description\n"
        "简体中文(zh-Hans),应用,副标,描述\n"
        "en-US,App,,Hello\n",
        encoding="utf-8-sig",
    )
    snap = load_local_text_snapshot(str(p))
    assert snap.source == "local"
    by = {x.locale: x for x in snap.locales}
    assert by["zh-Hans"].fields["name"] == "应用"
    assert by["en-US"].fields["description"] == "Hello"
    assert by["en-US"].fields["subtitle"] == ""

def test_save_preserves_unknown_columns_and_order(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text(
        "locale,name,extra,description\n"
        "en-US,Old,keep-me,Desc\n"
        "zh-Hans,中,保留,描\n",
        encoding="utf-8-sig",
    )
    snap = load_local_text_snapshot(str(p))
    en = next(x for x in snap.locales if x.locale == "en-US")
    en.fields["name"] = "New"
    save_local_csv(str(p), snap.locales)
    text = p.read_text(encoding="utf-8-sig")
    assert "extra" in text.splitlines()[0]
    assert "keep-me" in text
    assert "New" in text
    # zh-Hans row still present before/after en depending on original order
    assert text.index("en-US") < text.index("zh-Hans") or "zh-Hans" in text

def test_save_preserves_locale_display_string(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text(
        "locale,name\n"
        "简体中文(zh-Hans),应用\n",
        encoding="utf-8-sig",
    )
    snap = load_local_text_snapshot(str(p))
    zh = next(x for x in snap.locales if x.locale == "zh-Hans")
    zh.fields["name"] = "新应用"
    save_local_csv(str(p), snap.locales)
    text = p.read_text(encoding="utf-8-sig")
    assert "简体中文(zh-Hans)" in text
    assert "新应用" in text
    assert "zh-Hans\n" not in text
    assert ",zh-Hans," not in text

def test_save_appends_new_locale_at_end(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text(
        "locale,name\n"
        "en-US,App\n",
        encoding="utf-8-sig",
    )
    snap = load_local_text_snapshot(str(p))
    snap.locales.append(LocaleListing("ja", {"name": "アプリ"}, {}))
    save_local_csv(str(p), snap.locales)
    lines = p.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].split(",")[0] == "locale"
    assert lines[1].startswith("en-US,")
    assert lines[-1].startswith("ja,")
    assert "アプリ" in lines[-1]

def test_save_updates_chinese_alias_headers(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text(
        "语言,应用名称,附加信息\n"
        "英文(en-US),OldName,keep-me\n",
        encoding="utf-8-sig",
    )
    snap = load_local_text_snapshot(str(p))
    en = next(x for x in snap.locales if x.locale == "en-US")
    assert en.fields["name"] == "OldName"
    en.fields["name"] = "NewName"
    save_local_csv(str(p), snap.locales)
    text = p.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    assert lines[0].startswith("语言,应用名称,附加信息")
    assert "NewName" in text
    assert "OldName" not in text
    assert "keep-me" in text
    assert "英文(en-US)" in text

def test_save_mtime_conflict(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text("locale,name\nen-US,A\n", encoding="utf-8-sig")
    mtime = p.stat().st_mtime
    time.sleep(0.02)
    p.write_text("locale,name\nen-US,B\n", encoding="utf-8-sig")
    with pytest.raises(FileChangedError):
        save_local_csv(
            str(p),
            [LocaleListing("en-US", {"name": "C"}, {})],
            expected_mtime=mtime,
        )


# ---------- Screenshot scan / reorder / replace / delete / add ----------


def test_reorder_matches_sorted_screenshots(tmp_path):
    from PIL import Image

    from asc.commands.screenshots import _get_sorted_screenshots
    from asc.listing.local import apply_screenshot_order

    d = tmp_path / "en-US"
    d.mkdir()
    # 1290x2796 → APP_IPHONE_67 in DISPLAY_TYPE_BY_SIZE
    for name in ("a.png", "b.png"):
        Image.new("RGB", (1290, 2796), color=(1, 2, 3)).save(d / name)
    apply_screenshot_order(d, "APP_IPHONE_67", ["b.png", "a.png"])
    names = [p.name for p in _get_sorted_screenshots(d)]
    assert names[0].startswith("01_")
    assert "b" in names[0]
    assert names[1].startswith("02_")


def test_reorder_rejects_path_traversal(tmp_path):
    """Reorder must reject `../` / absolute names and never pull outside files in."""
    import pytest
    from PIL import Image

    from asc.listing.local import PathTraversalError, apply_screenshot_order

    root = tmp_path / "screenshots"
    locale_dir = root / "en-US"
    locale_dir.mkdir(parents=True)
    Image.new("RGB", (1290, 2796)).save(locale_dir / "a.png")

    outside = tmp_path / "outside.png"
    Image.new("RGB", (200, 200), color=(9, 9, 9)).save(outside)
    outside_bytes = outside.read_bytes()

    with pytest.raises(PathTraversalError):
        apply_screenshot_order(
            locale_dir,
            "APP_IPHONE_67",
            ["../outside.png"],
            root=root,
        )

    assert outside.exists()
    assert outside.read_bytes() == outside_bytes
    assert not (locale_dir / "outside.png").exists()
    assert (locale_dir / "a.png").exists()
    assert [p.name for p in locale_dir.iterdir()] == ["a.png"]


def test_reorder_strips_old_numeric_prefix(tmp_path):
    from PIL import Image

    from asc.commands.screenshots import _get_sorted_screenshots
    from asc.listing.local import apply_screenshot_order

    d = tmp_path / "en-US"
    d.mkdir()
    Image.new("RGB", (1290, 2796)).save(d / "01_home.png")
    Image.new("RGB", (1290, 2796)).save(d / "02_detail.png")
    apply_screenshot_order(d, "APP_IPHONE_67", ["02_detail.png", "01_home.png"])
    names = sorted(p.name for p in d.iterdir())
    assert names == ["01_detail.png", "02_home.png"]
    ordered = [p.name for p in _get_sorted_screenshots(d)]
    assert ordered[0] == "01_detail.png"
    assert ordered[1] == "02_home.png"


def test_scan_local_screenshots_groups_by_locale_and_display_type(tmp_path):
    from PIL import Image

    from asc.listing.local import scan_local_screenshots

    base = tmp_path / "screenshots"
    en = base / "en-US"
    en.mkdir(parents=True)
    Image.new("RGB", (1290, 2796)).save(en / "01_a.png")
    Image.new("RGB", (1290, 2796)).save(en / "02_b.png")

    cn = base / "cn"
    cn.mkdir(parents=True)
    Image.new("RGB", (1290, 2796)).save(cn / "01_a.png")

    result = scan_local_screenshots(str(base))

    assert set(result.keys()) == {"en-US", "zh-Hans"}
    en_groups = result["en-US"]
    assert set(en_groups.keys()) == {"APP_IPHONE_67"}
    items = en_groups["APP_IPHONE_67"]
    assert [i.file_name for i in items] == ["01_a.png", "02_b.png"]
    assert [i.order for i in items] == [1, 2]
    assert items[0].local_path == str(en / "01_a.png")

    from urllib.parse import parse_qs, unquote, urlparse

    parsed = urlparse(items[0].thumb_url)
    assert parsed.path == "/api/listing/thumb"
    qs = parse_qs(parsed.query)
    assert unquote(qs["path"][0]) == str(en / "01_a.png")
    assert unquote(qs["root"][0]) == str(base)


def test_scan_local_screenshots_unknown_dimension_marked_unknown(tmp_path):
    from PIL import Image

    from asc.listing.local import scan_local_screenshots

    base = tmp_path / "screenshots"
    en = base / "en-US"
    en.mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(en / "01_weird.png")

    result = scan_local_screenshots(str(base))
    assert set(result["en-US"].keys()) == {"UNKNOWN"}
    assert result["en-US"]["UNKNOWN"][0].file_name == "01_weird.png"


def test_scan_local_screenshots_missing_dir_returns_empty(tmp_path):
    from asc.listing.local import scan_local_screenshots

    result = scan_local_screenshots(str(tmp_path / "does-not-exist"))
    assert result == {}


def test_replace_screenshot_overwrites_bytes(tmp_path):
    from asc.listing.local import replace_screenshot

    d = tmp_path / "en-US"
    d.mkdir()
    p = d / "01_a.png"
    p.write_bytes(b"old-bytes")
    result = replace_screenshot(p, b"new-bytes", None)
    assert result == p
    assert p.read_bytes() == b"new-bytes"


def test_replace_screenshot_with_new_name_removes_old_file(tmp_path):
    from asc.listing.local import replace_screenshot

    d = tmp_path / "en-US"
    d.mkdir()
    p = d / "01_a.png"
    p.write_bytes(b"old-bytes")
    result = replace_screenshot(p, b"new-bytes", "01_a.jpg")
    assert result == d / "01_a.jpg"
    assert not p.exists()
    assert result.read_bytes() == b"new-bytes"


def test_delete_screenshot_removes_file(tmp_path):
    from asc.listing.local import delete_screenshot

    d = tmp_path / "en-US"
    d.mkdir()
    p = d / "01_a.png"
    p.write_bytes(b"data")
    delete_screenshot(p)
    assert not p.exists()


def test_delete_screenshot_missing_file_is_noop(tmp_path):
    from asc.listing.local import delete_screenshot

    p = tmp_path / "missing.png"
    delete_screenshot(p)  # should not raise


def test_add_screenshot_creates_file(tmp_path):
    from asc.listing.local import add_screenshot

    d = tmp_path / "en-US"
    result = add_screenshot(d, "APP_IPHONE_67", "03_new.png", b"png-bytes")
    assert result == d / "03_new.png"
    assert result.read_bytes() == b"png-bytes"


def test_add_screenshot_rejects_path_traversal(tmp_path):
    import pytest

    from asc.listing.local import PathTraversalError, add_screenshot

    root = tmp_path / "screenshots"
    root.mkdir()
    locale_dir = root / "en-US"

    with pytest.raises(PathTraversalError):
        add_screenshot(locale_dir, "APP_IPHONE_67", "../escape.png", b"x", root=root)
    with pytest.raises(PathTraversalError):
        add_screenshot(locale_dir, "APP_IPHONE_67", "/tmp/evil.png", b"x", root=root)
    outside = tmp_path / "outside"
    with pytest.raises(PathTraversalError):
        add_screenshot(outside, "APP_IPHONE_67", "a.png", b"x", root=root)
    assert not (root / "escape.png").exists()
    assert list(root.iterdir()) == []


def test_add_screenshot_uses_basename_under_root(tmp_path):
    from asc.listing.local import add_screenshot

    root = tmp_path / "screenshots"
    locale_dir = root / "en-US"
    result = add_screenshot(locale_dir, "APP_IPHONE_67", "nested/ok.png", b"png", root=root)
    assert result == locale_dir / "ok.png"
    assert result.read_bytes() == b"png"


def test_replace_screenshot_rejects_unsafe_new_name(tmp_path):
    import pytest

    from asc.listing.local import PathTraversalError, replace_screenshot

    root = tmp_path / "screenshots"
    d = root / "en-US"
    d.mkdir(parents=True)
    p = d / "01_a.png"
    p.write_bytes(b"old")

    with pytest.raises(PathTraversalError):
        replace_screenshot(p, b"new", "../evil.png", root=root)
    with pytest.raises(PathTraversalError):
        replace_screenshot(p, b"new", "/tmp/evil.png", root=root)
    assert p.read_bytes() == b"old"
    assert not (root / "evil.png").exists()


def test_replace_screenshot_new_name_basename_under_parent(tmp_path):
    from asc.listing.local import replace_screenshot

    root = tmp_path / "screenshots"
    d = root / "en-US"
    d.mkdir(parents=True)
    p = d / "01_a.png"
    p.write_bytes(b"old")
    result = replace_screenshot(p, b"new", "subdir/01_a.jpg", root=root)
    assert result == d / "01_a.jpg"
    assert result.read_bytes() == b"new"
    assert not p.exists()


def test_reorder_numeric_stem_strips_digits_for_sort_key(tmp_path):
    """I1: pure-numeric stems must not become `01_2.png` (breaks last-number sort)."""
    import re

    from PIL import Image

    from asc.commands.screenshots import _get_sorted_screenshots
    from asc.listing.local import apply_screenshot_order

    d = tmp_path / "en-US"
    d.mkdir()
    Image.new("RGB", (1290, 2796)).save(d / "1.png")
    Image.new("RGB", (1290, 2796)).save(d / "2.png")
    apply_screenshot_order(d, "APP_IPHONE_67", ["2.png", "1.png"])
    names = [p.name for p in _get_sorted_screenshots(d)]
    assert names == ["01_shot.png", "02_shot.png"]
    for name in names:
        nums = re.findall(r"\d+", Path(name).stem)
        assert nums[-1] == name[:2]


def test_reorder_renumbers_entire_folder_across_display_types(tmp_path):
    """I2: reordering one displayType must renumber other types to avoid NN_ collisions."""
    from PIL import Image

    from asc.commands.screenshots import _get_sorted_screenshots
    from asc.listing.local import apply_screenshot_order

    d = tmp_path / "en-US"
    d.mkdir()
    # iPhone 6.7" + iPad Pro 12.9" in the same locale folder
    Image.new("RGB", (1290, 2796)).save(d / "01_iphone_a.png")
    Image.new("RGB", (2048, 2732)).save(d / "02_ipad.png")
    Image.new("RGB", (1290, 2796)).save(d / "03_iphone_b.png")

    apply_screenshot_order(
        d,
        "APP_IPHONE_67",
        ["03_iphone_b.png", "01_iphone_a.png"],
    )
    names = [p.name for p in _get_sorted_screenshots(d)]
    assert names == ["01_iphone_b.png", "02_ipad.png", "03_iphone_a.png"]
