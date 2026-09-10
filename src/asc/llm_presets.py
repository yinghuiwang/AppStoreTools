"""Shared LLM provider presets for Web settings and validation.

All presets use the OpenAI-compatible chat-completions surface already
implemented by ``LLMClient``. Native Anthropic Messages is not added here;
Anthropic is included via its official OpenAI-compatible base URL.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class LlmPreset:
    id: str
    name: str
    base_url: str
    models: tuple[str, ...]
    default_model: str = ""
    api_style: str = "openai"
    api_key_optional: bool = False
    custom: bool = False

    def public_dict(self) -> dict[str, Any]:
        default_model = self.default_model or (self.models[0] if self.models else "")
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "api_style": self.api_style,
            "models": list(self.models),
            "default_model": default_model,
            "api_key_optional": self.api_key_optional,
            "custom": self.custom,
        }


LLM_PRESETS: tuple[LlmPreset, ...] = (
    LlmPreset(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        models=("gpt-4o", "gpt-4o-mini", "gpt-4.1", "o4-mini", "o3"),
        default_model="gpt-4o",
    ),
    LlmPreset(
        id="minimax-cn",
        name="MiniMax CN",
        base_url="https://api.minimaxi.com/v1",
        models=(
            "MiniMax-M3",
            "MiniMax-M2.7",
            "MiniMax-M2.5",
            "MiniMax-M2.1",
            "MiniMax-M2",
            "M2-her",
        ),
        default_model="MiniMax-M3",
    ),
    LlmPreset(
        id="minimax",
        name="MiniMax",
        base_url="https://api.minimax.io/v1",
        models=(
            "MiniMax-M3",
            "MiniMax-M2.7",
            "MiniMax-M2.5",
            "MiniMax-M2.1",
            "MiniMax-M2",
            "MiniMax-M2.7-highspeed",
        ),
        default_model="MiniMax-M3",
    ),
    LlmPreset(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        models=("deepseek-chat", "deepseek-reasoner", "deepseek-coder"),
        default_model="deepseek-chat",
    ),
    LlmPreset(
        id="anthropic",
        name="Anthropic",
        base_url="https://api.anthropic.com/v1",
        models=(
            "claude-sonnet-4-5",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "claude-haiku-4-5",
            "claude-3-5-haiku-latest",
        ),
        default_model="claude-sonnet-4-5",
    ),
    LlmPreset(
        id="moonshot",
        name="Moonshot / Kimi",
        base_url="https://api.moonshot.cn/v1",
        models=(
            "kimi-k2-0711-preview",
            "kimi-latest",
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
        ),
        default_model="kimi-k2-0711-preview",
    ),
    LlmPreset(
        id="qwen",
        name="Qwen / DashScope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=("qwen-plus", "qwen-turbo", "qwen-max", "qwen-long", "qwen3-coder-plus"),
        default_model="qwen-plus",
    ),
    LlmPreset(
        id="gemini",
        name="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        models=(
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ),
        default_model="gemini-2.5-flash",
    ),
    LlmPreset(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        models=(
            "openai/gpt-4o",
            "anthropic/claude-sonnet-4",
            "google/gemini-2.5-flash",
            "deepseek/deepseek-chat",
            "qwen/qwen-2.5-72b-instruct",
        ),
        default_model="openai/gpt-4o",
    ),
    LlmPreset(
        id="groq",
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        models=(
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
            "openai/gpt-oss-120b",
        ),
        default_model="llama-3.3-70b-versatile",
    ),
    LlmPreset(
        id="siliconflow",
        name="SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        models=(
            "deepseek-ai/DeepSeek-V3",
            "Qwen/Qwen2.5-72B-Instruct",
            "Qwen/Qwen3-8B",
            "THUDM/glm-4-9b-chat",
            "moonshotai/Kimi-K2-Instruct",
        ),
        default_model="deepseek-ai/DeepSeek-V3",
    ),
    LlmPreset(
        id="ollama",
        name="Ollama",
        base_url="http://127.0.0.1:11434/v1",
        models=("llama3.2", "llama3.1", "qwen2.5", "deepseek-r1", "mistral", "gemma3"),
        default_model="llama3.2",
        api_key_optional=True,
    ),
    LlmPreset(
        id="custom",
        name="Custom",
        base_url="",
        models=(),
        custom=True,
    ),
)

PRESET_BY_ID: dict[str, LlmPreset] = {preset.id: preset for preset in LLM_PRESETS}


def list_llm_presets() -> list[dict[str, Any]]:
    return [preset.public_dict() for preset in LLM_PRESETS]


def get_llm_preset(preset_id: str | None) -> LlmPreset | None:
    if not preset_id:
        return None
    return PRESET_BY_ID.get(str(preset_id).strip().lower())


def normalize_llm_base_url(url: str) -> str:
    return str(url or "").strip().rstrip("/")


def match_llm_preset(base_url: str) -> LlmPreset | None:
    needle = normalize_llm_base_url(base_url)
    if not needle:
        return None
    for preset in LLM_PRESETS:
        if preset.custom:
            continue
        if normalize_llm_base_url(preset.base_url) == needle:
            return preset
    return None


def is_loopback_llm_base_url(url: str) -> bool:
    """True for localhost LLM endpoints such as Ollama."""
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def apply_llm_preset_fields(
    *,
    preset_id: str | None,
    name: str,
    base_url: str,
    model: str,
) -> tuple[str, str, str]:
    """Fill blank name / URL / model from a known preset. Overrides win."""
    preset = get_llm_preset(preset_id)
    if preset is None or preset.custom:
        return name, base_url, model
    out_name = str(name or "").strip() or preset.id
    out_url = str(base_url or "").strip() or preset.base_url
    out_model = (
        str(model or "").strip()
        or preset.default_model
        or (preset.models[0] if preset.models else "")
    )
    return out_name, out_url, out_model
