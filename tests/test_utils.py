"""Tests for src/asc/utils.py"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asc.utils import (
    extract_locale,
    is_interactive,
    list_valid_profiles,
    md5_of_file,
    parse_csv,
    resolve_csv_path,
    resolve_locale,
    resolve_screenshots_path,
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
    locales = [r["locale"] for r in rows]
    assert "zh-Hans" in locales
    assert "en-US" in locales


def test_parse_real_csv_app_name_present():
    rows = parse_csv(str(DATA_CSV))
    for row in rows:
        assert "name" in row
        assert row["name"]


def test_parse_csv_with_bom(tmp_path):
    csv_file = tmp_path / "test.csv"
    content = "语言,应用名称\n简体中文(zh-Hans),测试应用\n"
    csv_file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
    rows = parse_csv(str(csv_file))
    assert len(rows) == 1
    assert rows[0]["locale"] == "zh-Hans"
    assert rows[0]["name"] == "测试应用"


def test_parse_csv_skips_rows_without_locale(tmp_path):
    csv_file = tmp_path / "test.csv"
    content = "语言,应用名称\n,无语言行\n英文(en-US),有语言行\n"
    csv_file.write_text(content, encoding="utf-8")
    rows = parse_csv(str(csv_file))
    assert len(rows) == 1
    assert rows[0]["locale"] == "en-US"


def test_parse_csv_english_headers(tmp_path):
    csv_file = tmp_path / "en.csv"
    csv_file.write_text(
        "locale,name,subtitle,description,keywords,supportUrl,marketingUrl,privacyPolicyUrl\n"
        "en-US,App,Sub,Desc,kw,https://s.example,https://m.example,https://p.example\n",
        encoding="utf-8",
    )
    rows = parse_csv(str(csv_file))
    assert rows[0] == {
        "locale": "en-US",
        "name": "App",
        "subtitle": "Sub",
        "description": "Desc",
        "keywords": "kw",
        "supportUrl": "https://s.example",
        "marketingUrl": "https://m.example",
        "privacyPolicyUrl": "https://p.example",
    }


def test_parse_csv_mixed_headers(tmp_path):
    csv_file = tmp_path / "mixed.csv"
    csv_file.write_text(
        "locale,应用名称,keywords\nzh-Hans,测试,kw1\n",
        encoding="utf-8",
    )
    rows = parse_csv(str(csv_file))
    assert rows[0]["locale"] == "zh-Hans"
    assert rows[0]["name"] == "测试"
    assert rows[0]["keywords"] == "kw1"


def test_parse_csv_english_overrides_chinese_alias(tmp_path):
    csv_file = tmp_path / "conflict.csv"
    # Chinese first, English later → English wins
    csv_file.write_text(
        "关键字,keywords,语言\nchinese-kw,english-kw,en-US\n",
        encoding="utf-8",
    )
    rows = parse_csv(str(csv_file))
    assert rows[0]["keywords"] == "english-kw"


def test_parse_csv_first_chinese_alias_wins_when_no_english(tmp_path):
    csv_file = tmp_path / "alias_conflict.csv"
    csv_file.write_text(
        "关键词,关键字,语言\nfirst,second,en-US\n",
        encoding="utf-8",
    )
    rows = parse_csv(str(csv_file))
    assert rows[0]["keywords"] == "first"


def test_parse_csv_drops_unknown_columns(tmp_path):
    csv_file = tmp_path / "extra.csv"
    csv_file.write_text(
        "locale,name,extra_col\nen-US,App,ignored\n",
        encoding="utf-8",
    )
    rows = parse_csv(str(csv_file))
    assert rows[0] == {"locale": "en-US", "name": "App"}


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
    with patch.dict("os.environ", {}, clear=False):
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


# ── find_project_env / discover_local_import_candidates ──


def test_find_project_env_walks_upward(tmp_path):
    """从子目录向上找到 AppStore/Config/.env"""
    from asc.utils import find_project_env

    config_dir = tmp_path / "AppStore" / "Config"
    config_dir.mkdir(parents=True)
    env_file = config_dir / ".env"
    env_file.write_text("ISSUER_ID=a\n", encoding="utf-8")
    nested = tmp_path / "ios" / "Sources"
    nested.mkdir(parents=True)

    found = find_project_env(nested)
    assert found is not None
    assert found[0] == tmp_path.resolve()
    assert found[1] == env_file.resolve()


def test_find_project_env_returns_none_when_missing(tmp_path):
    from asc.utils import find_project_env

    assert find_project_env(tmp_path) is None


def test_discover_local_import_candidates_filters_imported(tmp_path):
    """已导入的凭证不会出现在候选列表中"""
    from unittest.mock import MagicMock, patch
    from asc.utils import discover_local_import_candidates

    config_dir = tmp_path / "AppStore" / "Config"
    config_dir.mkdir(parents=True)
    (config_dir / ".env").write_text(
        "ISSUER_ID=abc\nKEY_ID=def\nKEY_FILE=key.p8\nAPP_ID=123\n",
        encoding="utf-8",
    )
    (config_dir / "key.p8").write_text("fake-key", encoding="utf-8")

    mock_config = MagicMock()
    mock_config.list_apps.return_value = ["myapp"]
    mock_config.get_app_profile.return_value = {
        "issuer_id": "abc",
        "key_id": "def",
        "app_id": "123",
    }
    with patch("asc.config.Config", return_value=mock_config):
        assert discover_local_import_candidates(tmp_path) == []


def test_discover_local_import_candidates_returns_unimported(tmp_path):
    """未导入且完整的 .env 作为候选返回"""
    from unittest.mock import MagicMock, patch
    from asc.utils import discover_local_import_candidates

    config_dir = tmp_path / "AppStore" / "Config"
    config_dir.mkdir(parents=True)
    (config_dir / ".env").write_text(
        "ISSUER_ID=abc\nKEY_ID=def\nKEY_FILE=key.p8\nAPP_ID=123\n",
        encoding="utf-8",
    )
    (config_dir / "key.p8").write_text("fake-key", encoding="utf-8")
    (tmp_path / "AppStore" / "data" / "screenshots").mkdir(parents=True)

    mock_config = MagicMock()
    mock_config.list_apps.return_value = []
    mock_config.get_app_profile.return_value = None
    with patch("asc.config.Config", return_value=mock_config):
        candidates = discover_local_import_candidates(tmp_path)

    assert len(candidates) == 1
    c = candidates[0]
    assert c["app_id"] == "123"
    assert c["key_id"] == "def"
    assert c["key_file_exists"] is True
    assert c["suggested_name"] == tmp_path.name
    assert c["project_root"] == str(tmp_path.resolve())


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
    mock_config.app_name = None  # no default_app configured
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


def test_resolve_app_profile_falls_back_to_default_app(monkeypatch):
    """When no --app is given, resolve_app_profile uses config.app_name
    (loaded from local .asc/config.toml default_app)."""
    from unittest.mock import MagicMock
    from asc.utils import resolve_app_profile

    mock_config = MagicMock()
    mock_config.app_name = "mydefault"  # came from default_app in .asc/config.toml
    mock_config.get_app_profile.return_value = {
        "issuer_id": "i", "key_id": "k", "key_file": "/p.p8", "app_id": "1",
    }

    # Pass None for the CLI arg; it must resolve to the default_app
    result = resolve_app_profile(None, mock_config)
    assert result == "mydefault"
    mock_config.get_app_profile.assert_called_with("mydefault")


def test_resolve_csv_path_prefers_cli_over_config():
    config = MagicMock()
    config.csv_path = "from-profile.csv"
    config.app_name = "myapp"
    assert resolve_csv_path(config, "from-cli.csv") == "from-cli.csv"


def test_resolve_csv_path_uses_configured_when_cli_blank():
    config = MagicMock()
    config.csv_path = "from-profile.csv"
    config.app_name = "myapp"
    assert resolve_csv_path(config, None) == "from-profile.csv"
    assert resolve_csv_path(config, "  ") == "from-profile.csv"


def test_resolve_csv_path_errors_when_missing_and_non_interactive(monkeypatch):
    import typer

    monkeypatch.setattr("asc.utils.is_interactive", lambda: False)
    config = MagicMock()
    config.csv_path = ""
    config.app_name = "myapp"
    with pytest.raises(typer.Exit):
        resolve_csv_path(config, None)


def test_resolve_csv_path_prompts_and_persists(monkeypatch):
    monkeypatch.setattr("asc.utils.is_interactive", lambda: True)
    monkeypatch.setattr("asc.utils.typer.prompt", lambda *a, **k: "picked.csv")
    config = MagicMock()
    config.csv_path = ""
    config.app_name = "myapp"
    config._data = {}
    config.get_app_profile.return_value = {
        "issuer_id": "i",
        "key_id": "k",
        "key_file": "/k.p8",
        "app_id": "1",
        "csv": "",
        "screenshots": "",
    }
    assert resolve_csv_path(config, None) == "picked.csv"
    config.save_app_profile.assert_called_once_with(
        "myapp", "i", "k", "/k.p8", "1", "picked.csv", None,
    )


def test_resolve_screenshots_path_optional_returns_empty_when_non_interactive(monkeypatch):
    monkeypatch.setattr("asc.utils.is_interactive", lambda: False)
    config = MagicMock()
    config.screenshots_path = ""
    config.app_name = "myapp"
    assert resolve_screenshots_path(config, None, required=False) == ""
