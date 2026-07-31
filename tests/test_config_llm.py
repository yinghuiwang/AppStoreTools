"""Unit tests for Config LLM properties."""
from __future__ import annotations

import pytest
from asc.config import Config


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep tests independent from the developer's ~/.config/asc/llm.toml."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


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


def test_save_llm_config_keeps_secret_private_and_preserves_blank_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    cfg.save_llm_config("main", "https://api.example.com/v1", "secret", "model")
    cfg.save_llm_config(
        "main", "https://api.example.com/v1", "", "new-model", preserve_blank_api_key=True
    )
    path = tmp_path / ".config" / "asc" / "llm.toml"
    assert path.stat().st_mode & 0o777 == 0o600
    assert cfg.get_llm_config("main")["api_key"] == "secret"
    assert cfg.get_llm_config("main")["model"] == "new-model"


def test_save_app_profile_escapes_toml_values_and_keeps_profile_private(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    issuer = 'issuer"\n[unexpected]\nvalue = "injected'
    cfg.save_app_profile("demo", issuer, "key", "/tmp/key.p8", "app", "data.csv", "shots")
    path = tmp_path / ".config" / "asc" / "profiles" / "demo.toml"
    assert path.stat().st_mode & 0o777 == 0o600
    profile = cfg.get_app_profile("demo")
    assert profile is not None
    assert profile["issuer_id"] == issuer
