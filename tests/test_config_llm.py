"""Unit tests for Config LLM properties."""
from __future__ import annotations

import pytest
from asc.config import Config


def test_llm_api_key_from_toml(tmp_path, monkeypatch):
    """reads api_key from [llm] section in TOML"""
    monkeypatch.chdir(tmp_path)
    asc_dir = tmp_path / ".asc"
    asc_dir.mkdir()
    (asc_dir / "config.toml").write_text(
        '[llm]\n'
        'api_key = "sk-toml-key"\n'
    )
    cfg = Config()
    assert cfg.llm_api_key == "sk-toml-key"


def test_llm_base_url_from_toml(tmp_path, monkeypatch):
    """reads base_url from [llm] section in TOML"""
    monkeypatch.chdir(tmp_path)
    asc_dir = tmp_path / ".asc"
    asc_dir.mkdir()
    (asc_dir / "config.toml").write_text(
        '[llm]\n'
        'base_url = "https://api.example.com/v1"\n'
    )
    cfg = Config()
    assert cfg.llm_base_url == "https://api.example.com/v1"


def test_llm_model_from_toml(tmp_path, monkeypatch):
    """reads model from [llm] section in TOML"""
    monkeypatch.chdir(tmp_path)
    asc_dir = tmp_path / ".asc"
    asc_dir.mkdir()
    (asc_dir / "config.toml").write_text(
        '[llm]\n'
        'model = "gpt-4-turbo"\n'
    )
    cfg = Config()
    assert cfg.llm_model == "gpt-4-turbo"


def test_llm_model_defaults_to_gpt_4o(tmp_path, monkeypatch):
    """returns 'gpt-4o' when not configured"""
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    assert cfg.llm_model == "gpt-4o"


def test_llm_base_url_defaults_to_openai(tmp_path, monkeypatch):
    """returns 'https://api.openai.com/v1' when not configured"""
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    assert cfg.llm_base_url == "https://api.openai.com/v1"


def test_llm_api_key_falls_back_to_env_var(tmp_path, monkeypatch):
    """falls back to OPENAI_API_KEY env var when not in TOML"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
    cfg = Config()
    assert cfg.llm_api_key == "sk-env-key"


def test_llm_api_key_toml_overrides_env(tmp_path, monkeypatch):
    """TOML api_key takes precedence over OPENAI_API_KEY env var"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
    asc_dir = tmp_path / ".asc"
    asc_dir.mkdir()
    (asc_dir / "config.toml").write_text(
        '[llm]\n'
        'api_key = "sk-toml-key"\n'
    )
    cfg = Config()
    assert cfg.llm_api_key == "sk-toml-key"
