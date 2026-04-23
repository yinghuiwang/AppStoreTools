"""Tests for src/asc/constants.py"""
from __future__ import annotations

import pytest

from asc.constants import DISPLAY_TYPE_BY_SIZE, normalize_locale_code


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
