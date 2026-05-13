"""Tests for src/asc/utils.py"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from asc.utils import (
    extract_locale,
    is_interactive,
    list_valid_profiles,
    md5_of_file,
    parse_csv,
    resolve_locale,
)


# ── extract_locale ──

def test_extract_locale_chinese_format():
    assert extract_locale("简体中文(zh-Hans)") == "zh-Hans"


def test_extract_locale_english_format():
    assert extract_locale("英文(en-US)") == "en-US"


def test_extract_locale_bare_code():
    assert extract_locale("en") == "en"


def test_extract_locale_strips_whitespace():
    assert extract_locale("  en-US  ") == "en-US"


# ── parse_csv ──

DATA_CSV = Path(__file__).parents[1] / "data" / "appstore_info.csv"


def test_parse_real_csv_row_count():
    rows = parse_csv(str(DATA_CSV))
    assert len(rows) == 2


def test_parse_real_csv_locale_codes():
    rows = parse_csv(str(DATA_CSV))
    locales = [r["语言"] for r in rows]
    assert "zh-Hans" in locales
    assert "en-US" in locales


def test_parse_real_csv_app_name_present():
    rows = parse_csv(str(DATA_CSV))
    for row in rows:
        assert "应用名称" in row
        assert row["应用名称"]


def test_parse_csv_with_bom(tmp_path):
    csv_file = tmp_path / "test.csv"
    # utf-8-sig BOM 编码
    content = "语言,应用名称\n简体中文(zh-Hans),测试应用\n"
    csv_file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
    rows = parse_csv(str(csv_file))
    assert len(rows) == 1
    assert rows[0]["语言"] == "zh-Hans"
    assert rows[0]["应用名称"] == "测试应用"


def test_parse_csv_skips_rows_without_locale(tmp_path):
    csv_file = tmp_path / "test.csv"
    content = "语言,应用名称\n,无语言行\n英文(en-US),有语言行\n"
    csv_file.write_text(content, encoding="utf-8")
    rows = parse_csv(str(csv_file))
    assert len(rows) == 1
    assert rows[0]["语言"] == "en-US"


# ── resolve_locale ──

def test_resolve_exact_match():
    assert resolve_locale("en-US", ["en-US", "zh-Hans"]) == "en-US"


def test_resolve_csv_alias_via_mapping():
    # "en" 通过 CSV_LOCALE_TO_ASC 映射到 "en-US"
    result = resolve_locale("en", ["en-US", "zh-Hans"])
    assert result == "en-US"


def test_resolve_prefix_match():
    result = resolve_locale("zh", ["en-US", "zh-Hans"])
    assert result == "zh-Hans"


def test_resolve_no_match_returns_fallback():
    # 无法匹配时返回 CSV_LOCALE_TO_ASC 的值或原始输入
    result = resolve_locale("fr", ["en-US", "zh-Hans"])
    # fr 通过 CSV_LOCALE_TO_ASC 映射为 fr-FR
    assert result == "fr-FR"


def test_resolve_unknown_code_returns_input():
    result = resolve_locale("xx-XX", ["en-US"])
    assert result == "xx-XX"


# ── md5_of_file ──

def test_md5_of_file(tmp_path):
    data = b"hello world"
    f = tmp_path / "data.bin"
    f.write_bytes(data)
    expected = hashlib.md5(data).hexdigest()
    assert md5_of_file(f) == expected


# ── is_interactive ──

def test_is_interactive_returns_bool():
    """is_interactive should return a boolean"""
    result = is_interactive()
    assert isinstance(result, bool)


# ── list_valid_profiles ──

def test_list_valid_profiles_filters_incomplete():
    """list_valid_profiles should only return profiles with complete credentials"""
    mock_config = MagicMock()
    mock_config.list_apps.return_value = ["app1", "app2", "app3"]
    mock_config.get_app_profile.side_effect = [
        {"issuer_id": "abc", "key_id": "def", "key_file": "/path", "app_id": "1"},
        {"issuer_id": "abc", "key_id": "def", "app_id": "2"},  # missing key_file
        {"issuer_id": "abc", "key_id": "def", "key_file": "/path", "app_id": "3"},
    ]
    result = list_valid_profiles(mock_config)
    assert len(result) == 2
    assert result[0][0] == "app1"
    assert result[1][0] == "app3"


# ── Config _ASC_LOCAL_CONFIG_PATH ──


def test_config_loads_from_local_env_path(tmp_path, monkeypatch):
    """当 _ASC_LOCAL_CONFIG_PATH 设置时，Config 从该路径加载 .env"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        'ISSUER_ID=env-issuer\nKEY_ID=env-key\nKEY_FILE=/tmp/key.p8\nAPP_ID=123456\n',
        encoding="utf-8"
    )
    monkeypatch.setenv("_ASC_LOCAL_CONFIG_PATH", str(env_file))
    monkeypatch.delenv("ISSUER_ID", raising=False)

    from asc.config import Config
    cfg = Config(app_name="__local__")
    assert cfg.issuer_id == "env-issuer"
    assert cfg.key_id == "env-key"
    assert cfg.app_id == "123456"


# ── detect_local_app_config ──

def test_detect_local_app_config_finds_env(tmp_path):
    """检测到 AppStore/Config/.env 时返回凭证 dict"""
    appstore = tmp_path / "AppStore"
    config_dir = appstore / "Config"
    config_dir.mkdir(parents=True)
    env_file = config_dir / ".env"
    env_file.write_text(
        "ISSUER_ID=abc\nKEY_ID=def\nKEY_FILE=key.p8\nAPP_ID=123\n",
        encoding="utf-8"
    )
    (appstore / "data" / "screenshots").mkdir(parents=True)

    from asc.utils import detect_local_app_config
    result = detect_local_app_config(tmp_path)
    assert result is not None
    assert result["issuer_id"] == "abc"
    assert result["key_id"] == "def"
    assert result["app_id"] == "123"
    assert result["project_name"] == tmp_path.name
    assert result["screenshots_path"] == str(appstore / "data" / "screenshots")


def test_detect_local_app_config_missing_env_returns_none(tmp_path):
    """没有 AppStore/Config/.env 时返回 None"""
    from asc.utils import detect_local_app_config
    result = detect_local_app_config(tmp_path)
    assert result is None


def test_is_local_config_imported_true(tmp_path):
    """.env 凭证与已有 profile 一致时返回 True"""
    from asc.utils import detect_local_app_config, is_local_config_imported
    appstore = tmp_path / "AppStore"
    config_dir = appstore / "Config"
    config_dir.mkdir(parents=True)
    (config_dir / ".env").write_text(
        "ISSUER_ID=abc\nKEY_ID=def\nKEY_FILE=key.p8\nAPP_ID=123\n",
        encoding="utf-8"
    )
    local = detect_local_app_config(tmp_path)
    existing = [
        {"issuer_id": "abc", "key_id": "def", "app_id": "123"},
        {"issuer_id": "xyz", "key_id": "other", "app_id": "456"},
    ]
    assert is_local_config_imported(local, existing) is True


def test_is_local_config_imported_false(tmp_path):
    """.env 凭证与任何 profile 都不一致时返回 False"""
    from asc.utils import detect_local_app_config, is_local_config_imported
    appstore = tmp_path / "AppStore"
    config_dir = appstore / "Config"
    config_dir.mkdir(parents=True)
    (config_dir / ".env").write_text(
        "ISSUER_ID=abc\nKEY_ID=def\nKEY_FILE=key.p8\nAPP_ID=123\n",
        encoding="utf-8"
    )
    local = detect_local_app_config(tmp_path)
    existing = [
        {"issuer_id": "xyz", "key_id": "other", "app_id": "456"},
    ]
    assert is_local_config_imported(local, existing) is False


# ── prompt_local_config_usage ──


def test_prompt_local_config_usage_choose_use_once(monkeypatch):
    """选择 '1'（仅本次使用）返回 '__local__'"""
    from asc.utils import prompt_local_config_usage

    call_count = 0
    def mock_input(prompt):
        nonlocal call_count
        call_count += 1
        return "1"

    monkeypatch.setattr("asc.utils._read_line", mock_input)
    result = prompt_local_config_usage({})
    assert result == "__local__"


def test_prompt_local_config_usage_choose_import(monkeypatch):
    """选择 '2'（导入为 profile）返回 '__import__'"""
    from asc.utils import prompt_local_config_usage

    call_count = 0
    def mock_input(prompt):
        nonlocal call_count
        call_count += 1
        return "2"

    monkeypatch.setattr("asc.utils._read_line", mock_input)
    result = prompt_local_config_usage({})
    assert result == "__import__"


def test_prompt_local_config_usage_cancel_raises(monkeypatch):
    """选择 '3'（取消）抛出 Abort"""
    from asc.utils import prompt_local_config_usage
    import typer

    call_count = 0
    def mock_input(prompt):
        nonlocal call_count
        call_count += 1
        return "3"

    monkeypatch.setattr("asc.utils._read_line", mock_input)
    with pytest.raises(typer.Abort):
        prompt_local_config_usage({})


def test_prompt_local_config_usage_invalid_raises(monkeypatch):
    """无效输入抛出 Abort"""
    from asc.utils import prompt_local_config_usage
    import typer

    def mock_input(prompt):
        return "99"  # invalid

    monkeypatch.setattr("asc.utils._read_line", mock_input)
    with pytest.raises(typer.Abort):
        prompt_local_config_usage({})


# ── resolve_app_profile with local config ──


def test_resolve_app_profile_includes_local_config_in_choices(monkeypatch, tmp_path):
    """当存在未导入的本地配置时，选择列表显示它"""
    from unittest.mock import MagicMock
    from asc.utils import resolve_app_profile

    # Create AppStore/Config/.env in tmp_path
    appstore = tmp_path / "AppStore"
    config_dir = appstore / "Config"
    config_dir.mkdir(parents=True)
    (config_dir / ".env").write_text(
        "ISSUER_ID=local-issuer\nKEY_ID=local-key\nKEY_FILE=key.p8\nAPP_ID=local-app\n",
        encoding="utf-8"
    )
    (appstore / "data" / "screenshots").mkdir(parents=True)

    # Mock is_interactive to return True
    monkeypatch.setattr("asc.utils.is_interactive", lambda: True)

    # Mock _read_line: return "2" to select local config, then "1" for "use once"
    inputs = iter(["2", "1"])
    def mock_read_line(prompt=""):
        return next(inputs)
    monkeypatch.setattr("asc.utils._read_line", mock_read_line)
    monkeypatch.chdir(tmp_path)

    mock_config = MagicMock()
    mock_config.list_apps.return_value = ["profile1"]
    mock_config.get_app_profile.return_value = {
        "issuer_id": "other", "key_id": "other", "key_file": "/p", "app_id": "1"
    }

    import os
    # Make sure env vars are not set before test
    monkeypatch.delenv("_ASC_LOCAL_CONFIG_PATH", raising=False)

    result = resolve_app_profile(None, mock_config)

    # Should return "__local__" since we chose "use once"
    assert result == "__local__"
    assert os.environ.get("_ASC_LOCAL_CONFIG_PATH") is not None
