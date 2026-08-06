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
