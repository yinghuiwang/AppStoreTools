from __future__ import annotations

import json

import pytest

from asc.locales_catalog import LocaleCatalogError, filter_locales, list_locales

REQUIRED_V1 = {"en-US", "zh-Hans", "zh-Hant", "ja"}

SAMPLE = [
    {"code": "zh-Hans", "name_en": "Chinese (Simplified)", "name_zh": "简体中文"},
    {"code": "zh-Hant", "name_en": "Chinese (Traditional)", "name_zh": "繁体中文"},
    {"code": "en-US", "name_en": "English (U.S.)", "name_zh": "英语（美国）"},
    {"code": "ja", "name_en": "Japanese", "name_zh": "日语"},
]


def test_list_locales_loads_packaged_catalog():
    items = list_locales()
    assert len(items) == 50
    codes = [row["code"] for row in items]
    assert len(codes) == len(set(codes))
    assert REQUIRED_V1 <= set(codes)
    for row in items:
        assert set(row) == {"code", "name_en", "name_zh"}
        assert row["code"].strip() == row["code"] != ""
        assert row["name_en"].strip() == row["name_en"] != ""
        assert row["name_zh"].strip() == row["name_zh"] != ""


def test_list_locales_reads_override_path(tmp_path):
    p = tmp_path / "catalog.json"
    p.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")
    items = list_locales(p)
    assert [row["code"] for row in items] == ["zh-Hans", "zh-Hant", "en-US", "ja"]


def test_list_locales_strips_and_drops_unknown_fields(tmp_path):
    p = tmp_path / "catalog.json"
    p.write_text(
        json.dumps(
            [
                {
                    "code": "  ja  ",
                    "name_en": " Japanese ",
                    "name_zh": " 日语 ",
                    "extra": "ignore-me",
                }
            ]
        ),
        encoding="utf-8",
    )
    items = list_locales(p)
    assert items == [{"code": "ja", "name_en": "Japanese", "name_zh": "日语"}]


@pytest.mark.parametrize(
    "payload",
    [
        {"locales": SAMPLE},
        [{"name_en": "Japanese", "name_zh": "日语"}],
        [{"code": "", "name_en": "Japanese", "name_zh": "日语"}],
        [{"code": "ja", "name_en": "   ", "name_zh": "日语"}],
        [{"code": "ja", "name_en": "Japanese", "name_zh": "日语"}, {"code": "ja", "name_en": "J", "name_zh": "日"}],
        ["ja"],
    ],
)
def test_list_locales_rejects_corrupt_catalog(tmp_path, payload):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(LocaleCatalogError):
        list_locales(p)


def test_list_locales_rejects_missing_and_invalid_json(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(LocaleCatalogError):
        list_locales(missing)
    p = tmp_path / "not.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(LocaleCatalogError):
        list_locales(p)


def test_filter_locales_empty_query_returns_all_sorted():
    out = filter_locales("  ", SAMPLE)
    assert [row["code"] for row in out] == ["en-US", "ja", "zh-Hans", "zh-Hant"]


def test_filter_locales_hans_simplified_chinese():
    items = filter_locales("hans", SAMPLE)
    assert [row["code"] for row in items] == ["zh-Hans"]
    items = filter_locales("简体", SAMPLE)
    assert [row["code"] for row in items] == ["zh-Hans"]
    items = filter_locales("chinese", SAMPLE)
    assert [row["code"] for row in items] == ["zh-Hans", "zh-Hant"]
    items = filter_locales("CHINESE", SAMPLE)
    assert [row["code"] for row in items] == ["zh-Hans", "zh-Hant"]
