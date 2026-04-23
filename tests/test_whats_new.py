"""Tests for src/asc/commands/whats_new.py — _parse_whats_new_file"""
from __future__ import annotations

import pytest

from asc.commands.whats_new import _parse_whats_new_file


def _write(tmp_path, content: str):
    f = tmp_path / "whats_new.txt"
    f.write_text(content, encoding="utf-8")
    return str(f)


def test_parse_separator_format_three_locales(tmp_path):
    content = (
        "en-US:\n"
        "Bug fixes.\n"
        "---\n"
        "zh-Hans:\n"
        "错误修复。\n"
        "---\n"
        "ja:\n"
        "バグ修正。\n"
    )
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result["en-US"] == "Bug fixes."
    assert result["zh-Hans"] == "错误修复。"
    assert result["ja"] == "バグ修正。"


def test_parse_separator_multiline_content(tmp_path):
    content = (
        "en-US:\n"
        "Line 1.\n"
        "Line 2.\n"
        "---\n"
        "zh-Hans:\n"
        "第一行。\n"
    )
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result["en-US"] == "Line 1.\nLine 2."


def test_parse_inline_format(tmp_path):
    content = (
        "en-US: Bug fixes and improvements.\n"
        "zh-Hans: 错误修复和性能改进。\n"
    )
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result["en-US"] == "Bug fixes and improvements."
    assert result["zh-Hans"] == "错误修复和性能改进。"


def test_parse_mixed_formats(tmp_path):
    content = (
        "en-US: Bug fixes.\n"
        "---\n"
        "zh-Hans:\n"
        "多行内容\n"
        "第二行\n"
    )
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result["en-US"] == "Bug fixes."
    assert result["zh-Hans"] == "多行内容\n第二行"


def test_parse_only_separators_returns_empty(tmp_path):
    content = "---\n---\n"
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result == {}


def test_parse_empty_file_returns_empty(tmp_path):
    result = _parse_whats_new_file(_write(tmp_path, ""))
    assert result == {}


def test_parse_strips_trailing_whitespace(tmp_path):
    content = "en-US:\nBug fixes.   \n   \n"
    result = _parse_whats_new_file(_write(tmp_path, content))
    assert result["en-US"] == "Bug fixes."
