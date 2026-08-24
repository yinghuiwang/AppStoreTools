"""Tests for src/asc/constants.py"""
from __future__ import annotations

import pytest

from asc.constants import (
    CSV_HEADER_ALIASES,
    DISPLAY_TYPE_BY_SIZE,
    canonicalize_csv_header,
    normalize_locale_code,
)


# ── normalize_locale_code ──

def test_normalize_empty_string():
    assert normalize_locale_code("") == ""


def test_normalize_two_char_lowercased():
    assert normalize_locale_code("EN") == "en"


def test_normalize_zh_hans_variants():
    assert normalize_locale_code("zh-Hans") == "zh-Hans"
    assert normalize_locale_code("ZH-HANS") == "zh-Hans"
    assert normalize_locale_code("zh_hans") == "zh-Hans"


def test_normalize_zh_hant_variants():
    assert normalize_locale_code("zh-Hant") == "zh-Hant"
    assert normalize_locale_code("ZH-HANT") == "zh-Hant"


def test_normalize_underscore_to_hyphen():
    assert normalize_locale_code("en_US") == "en-US"


def test_normalize_en_us_passthrough():
    assert normalize_locale_code("en-US") == "en-US"


def test_normalize_strips_quotes():
    assert normalize_locale_code('"en-US"') == "en-US"


# ── DISPLAY_TYPE_BY_SIZE ──

def test_known_portrait_size():
    assert DISPLAY_TYPE_BY_SIZE[(1290, 2796)] == "APP_IPHONE_67"


def test_known_landscape_same_type():
    # 横屏与竖屏返回相同设备类型
    assert DISPLAY_TYPE_BY_SIZE[(2796, 1290)] == DISPLAY_TYPE_BY_SIZE[(1290, 2796)]


def test_unknown_size_not_in_dict():
    assert (100, 100) not in DISPLAY_TYPE_BY_SIZE


def test_ipad_pro_size():
    assert DISPLAY_TYPE_BY_SIZE[(2048, 2732)] == "APP_IPAD_PRO_3GEN_129"


def test_official_iphone_69_1260_maps_to_67():
    assert DISPLAY_TYPE_BY_SIZE[(1260, 2736)] == "APP_IPHONE_67"
    assert DISPLAY_TYPE_BY_SIZE[(2736, 1260)] == "APP_IPHONE_67"


def test_official_iphone_63_1206_maps_to_61():
    assert DISPLAY_TYPE_BY_SIZE[(1206, 2622)] == "APP_IPHONE_61"
    assert DISPLAY_TYPE_BY_SIZE[(2622, 1206)] == "APP_IPHONE_61"


def test_official_iphone_61_1080_maps_to_61():
    assert DISPLAY_TYPE_BY_SIZE[(1080, 2340)] == "APP_IPHONE_61"
    assert DISPLAY_TYPE_BY_SIZE[(2340, 1080)] == "APP_IPHONE_61"


def test_official_ipad_11_extra_sizes_map():
    assert DISPLAY_TYPE_BY_SIZE[(1488, 2266)] == "APP_IPAD_PRO_3GEN_11"
    assert DISPLAY_TYPE_BY_SIZE[(1668, 2420)] == "APP_IPAD_PRO_3GEN_11"
    assert DISPLAY_TYPE_BY_SIZE[(1640, 2360)] == "APP_IPAD_PRO_3GEN_11"


def test_canonicalize_english_headers():
    assert canonicalize_csv_header("locale") == "locale"
    assert canonicalize_csv_header("name") == "name"
    assert canonicalize_csv_header("supportUrl") == "supportUrl"
    assert canonicalize_csv_header("privacyPolicyUrl") == "privacyPolicyUrl"


def test_canonicalize_chinese_aliases():
    assert canonicalize_csv_header("语言") == "locale"
    assert canonicalize_csv_header("应用名称") == "name"
    assert canonicalize_csv_header("副标题") == "subtitle"
    assert canonicalize_csv_header("长描述") == "description"
    assert canonicalize_csv_header("描述") == "description"
    assert canonicalize_csv_header("关键词") == "keywords"
    assert canonicalize_csv_header("关键字") == "keywords"
    assert canonicalize_csv_header("技术支持链接") == "supportUrl"
    assert canonicalize_csv_header("技术支持网址") == "supportUrl"
    assert canonicalize_csv_header("营销网站") == "marketingUrl"
    assert canonicalize_csv_header("营销网址") == "marketingUrl"
    assert canonicalize_csv_header("隐私政策网址") == "privacyPolicyUrl"
    assert canonicalize_csv_header("隐私政策链接") == "privacyPolicyUrl"
    assert canonicalize_csv_header("隐私政策URL") == "privacyPolicyUrl"


def test_canonicalize_strips_whitespace_and_quotes():
    assert canonicalize_csv_header('  "语言"  ') == "locale"
    assert canonicalize_csv_header(" name ") == "name"


def test_canonicalize_unknown_and_wrong_case_return_none():
    assert canonicalize_csv_header("unknown") is None
    assert canonicalize_csv_header("SupportUrl") is None  # case-sensitive
    assert canonicalize_csv_header("") is None


def test_csv_header_aliases_cover_all_canonicals():
    canonicals = {
        "locale", "name", "subtitle", "description", "keywords",
        "supportUrl", "marketingUrl", "privacyPolicyUrl",
    }
    assert canonicals <= set(CSV_HEADER_ALIASES.values())
    for c in canonicals:
        assert CSV_HEADER_ALIASES[c] == c
