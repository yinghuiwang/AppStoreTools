"""Tests for built-in LLM provider presets."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from asc.llm_presets import (
    apply_llm_preset_fields,
    get_llm_preset,
    is_loopback_llm_base_url,
    list_llm_presets,
    match_llm_preset,
)
from asc.web.server import create_app


REQUIRED_PRESET_IDS = {
    "openai",
    "minimax-cn",
    "minimax",
    "deepseek",
    "anthropic",
    "moonshot",
    "qwen",
    "gemini",
    "openrouter",
    "groq",
    "siliconflow",
    "ollama",
    "custom",
}

FEATURED_PRESET_ORDER = ("openai", "minimax-cn", "minimax", "deepseek")


def test_list_llm_presets_covers_common_providers():
    presets = list_llm_presets()
    ids = [item["id"] for item in presets]
    assert tuple(ids[:4]) == FEATURED_PRESET_ORDER
    assert ids[-1] == "custom"
    assert REQUIRED_PRESET_IDS <= set(ids)
    by_id = {item["id"]: item for item in presets}

    assert by_id["openai"]["base_url"] == "https://api.openai.com/v1"
    assert by_id["minimax-cn"]["base_url"] == "https://api.minimaxi.com/v1"
    assert by_id["minimax-cn"]["default_model"] == "MiniMax-M3"
    assert "MiniMax-M2" in by_id["minimax-cn"]["models"]
    assert by_id["minimax"]["base_url"] == "https://api.minimax.io/v1"
    assert by_id["minimax"]["default_model"] == "MiniMax-M3"
    assert by_id["anthropic"]["base_url"] == "https://api.anthropic.com/v1"
    assert by_id["deepseek"]["base_url"] == "https://api.deepseek.com"
    assert by_id["moonshot"]["base_url"] == "https://api.moonshot.cn/v1"
    assert by_id["qwen"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert by_id["gemini"]["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert by_id["openrouter"]["base_url"] == "https://openrouter.ai/api/v1"
    assert by_id["groq"]["base_url"] == "https://api.groq.com/openai/v1"
    assert by_id["siliconflow"]["base_url"] == "https://api.siliconflow.cn/v1"
    assert by_id["ollama"]["base_url"] == "http://127.0.0.1:11434/v1"
    assert by_id["ollama"]["api_key_optional"] is True
    assert by_id["custom"]["custom"] is True
    assert by_id["custom"]["base_url"] == ""

    for item in presets:
        assert item["api_style"] == "openai"
        if item["custom"]:
            continue
        assert 2 <= len(item["models"]) <= 6
        assert item["default_model"] in item["models"]


def test_apply_llm_preset_fields_fills_blanks_but_keeps_overrides():
    name, url, model = apply_llm_preset_fields(
        preset_id="deepseek",
        name="",
        base_url="",
        model="",
    )
    assert name == "deepseek"
    assert url == "https://api.deepseek.com"
    assert model == "deepseek-chat"

    name, url, model = apply_llm_preset_fields(
        preset_id="deepseek",
        name="work",
        base_url="https://proxy.example.com/v1",
        model="deepseek-reasoner",
    )
    assert name == "work"
    assert url == "https://proxy.example.com/v1"
    assert model == "deepseek-reasoner"


def test_apply_llm_preset_fields_ignores_custom():
    name, url, model = apply_llm_preset_fields(
        preset_id="custom",
        name="",
        base_url="",
        model="",
    )
    assert (name, url, model) == ("", "", "")


def test_match_llm_preset_by_base_url():
    matched = match_llm_preset("https://api.openai.com/v1/")
    assert matched is not None
    assert matched.id == "openai"
    assert match_llm_preset("https://api.minimaxi.com/v1").id == "minimax-cn"
    assert match_llm_preset("https://api.minimax.io/v1/").id == "minimax"
    assert match_llm_preset("https://example.com/v1") is None
    assert get_llm_preset("QWEN") is not None
    assert get_llm_preset("MiniMax-CN").id == "minimax-cn"


def test_is_loopback_llm_base_url():
    assert is_loopback_llm_base_url("http://127.0.0.1:11434/v1") is True
    assert is_loopback_llm_base_url("http://localhost:11434/v1") is True
    assert is_loopback_llm_base_url("https://api.openai.com/v1") is False


def test_get_llm_presets_endpoint():
    client = TestClient(create_app())
    response = client.get("/api/settings/llm/presets")
    assert response.status_code == 200
    data = response.json()
    ids = [item["id"] for item in data["presets"]]
    assert tuple(ids[:4]) == FEATURED_PRESET_ORDER
    assert REQUIRED_PRESET_IDS <= set(ids)


def test_settings_llm_get_includes_presets():
    mock_config = MagicMock()
    mock_config.llm_configs = {}
    mock_config.llm_default = None
    client = TestClient(create_app())
    with patch("asc.config.Config", return_value=mock_config):
        response = client.get("/api/settings/llm")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()["presets"]} >= REQUIRED_PRESET_IDS


def test_settings_llm_post_preset_id_fills_base_url():
    mock_config = MagicMock()
    client = TestClient(create_app())
    with patch("asc.config.Config", return_value=mock_config):
        response = client.post(
            "/api/settings/llm",
            json={"preset_id": "deepseek", "api_key": "sk-test", "model": "deepseek-chat"},
        )
    assert response.status_code == 200
    mock_config.save_llm_config.assert_called_once()
    args = mock_config.save_llm_config.call_args
    assert args.args[0] == "deepseek"
    assert args.args[1] == "https://api.deepseek.com"
    assert args.args[2] == "sk-test"
    assert args.args[3] == "deepseek-chat"


def test_settings_llm_post_custom_empty_url_rejected():
    client = TestClient(create_app())
    response = client.post(
        "/api/settings/llm",
        json={"preset_id": "custom", "name": "mine", "base_url": "", "api_key": "k", "model": "x"},
    )
    assert response.status_code == 400
    assert "base_url" in response.json()["error"]
