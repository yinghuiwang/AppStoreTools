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
