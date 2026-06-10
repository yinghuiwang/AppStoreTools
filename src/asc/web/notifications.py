"""Webhook notification configuration helpers for the Web UI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import toml

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.9/3.10 fallback
    try:
        import tomli as tomllib
    except ImportError:  # pragma: no cover
        tomllib = None  # type: ignore[assignment]


PROVIDERS = ("feishu", "wecom", "dingtalk")
DEFAULT_NOTIFY_STATUSES = ["done", "error", "canceled"]
DEFAULT_NOTIFY_KINDS = ["metadata", "build", "whats-new", "iap", "urls"]
TERMINAL_STATUSES = tuple(DEFAULT_NOTIFY_STATUSES)
TASK_KINDS = tuple(DEFAULT_NOTIFY_KINDS)


def webhook_config_path() -> Path:
    """Return the webhook config path, honoring the environment override."""
    configured = os.getenv("ASC_WEBHOOK_CONFIG_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "asc" / "webhook.toml"


def default_webhook_config() -> dict[str, Any]:
    """Return a fresh default webhook config."""
    return {
        "enabled": False,
        "notify_statuses": list(TERMINAL_STATUSES),
        "notify_kinds": list(TASK_KINDS),
        "providers": {
            provider: {
                "enabled": False,
                "url": "",
                "secret": "",
            }
            for provider in PROVIDERS
        },
    }


def _read_toml(path: Path) -> dict[str, Any]:
    if tomllib is None:
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_string_list(value: Any, allowed: tuple[str, ...]) -> list[str]:
    if not isinstance(value, list):
        return list(allowed)

    normalized = [item for item in value if isinstance(item, str) and item in allowed]
    return normalized or list(allowed)


def _normalize_bool(value: Any) -> bool:
    return value if isinstance(value, bool) else False


def _normalize_string(value: Any, *, strip: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip() if strip else value


def _normalize_provider(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    return {
        "enabled": _normalize_bool(data.get("enabled", False)),
        "url": _normalize_string(data.get("url", ""), strip=True),
        "secret": _normalize_string(data.get("secret", "")),
    }


def normalize_webhook_config(config: Any) -> dict[str, Any]:
    """Normalize partial or malformed webhook config data."""
    data = config if isinstance(config, dict) else {}
    providers = data.get("providers")
    provider_data = providers if isinstance(providers, dict) else {}

    return {
        "enabled": _normalize_bool(data.get("enabled", False)),
        "notify_statuses": _normalize_string_list(
            data.get("notify_statuses"),
            TERMINAL_STATUSES,
        ),
        "notify_kinds": _normalize_string_list(
            data.get("notify_kinds"),
            TASK_KINDS,
        ),
        "providers": {
            provider: _normalize_provider(provider_data.get(provider))
            for provider in PROVIDERS
        },
    }


def load_webhook_config() -> dict[str, Any]:
    """Load webhook config, returning defaults when missing or unreadable."""
    path = webhook_config_path()
    if not path.exists():
        return default_webhook_config()
    return normalize_webhook_config(_read_toml(path))


def save_webhook_config(
    config: dict[str, Any],
    *,
    preserve_blank_secrets: bool = False,
) -> dict[str, Any]:
    """Normalize and persist webhook config to TOML."""
    normalized = normalize_webhook_config(config)

    if preserve_blank_secrets:
        existing = load_webhook_config()
        for provider in PROVIDERS:
            incoming = normalized["providers"][provider]
            existing_secret = existing["providers"][provider]["secret"]
            if incoming["secret"] == "" and existing_secret:
                incoming["secret"] = existing_secret

    path = webhook_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(toml.dumps(normalized), encoding="utf-8")
    return normalized


def load_public_webhook_config() -> dict[str, Any]:
    """Load webhook config for UI/API responses without exposing secrets."""
    public = load_webhook_config()
    for provider in PROVIDERS:
        data = public["providers"][provider]
        secret = data.get("secret", "")
        data["secret"] = ""
        data["has_secret"] = bool(secret)
    return public
