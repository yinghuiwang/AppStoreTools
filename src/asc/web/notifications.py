"""Webhook notification configuration helpers for the Web UI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import toml

from asc.web import webhook_clients

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
STATUS_LABELS = {
    "done": "完成",
    "error": "失败",
    "canceled": "已取消",
}
STATUS_TITLE_PREFIX = {
    "done": "ASC 任务完成",
    "error": "ASC 任务失败",
    "canceled": "ASC 任务已取消",
}


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


def _status_value(status: Any) -> str:
    return str(getattr(status, "value", status) or "")


def should_notify(task: dict[str, Any], config: dict[str, Any]) -> bool:
    """Return whether a terminal task matches the webhook notification filters."""
    if not config.get("enabled"):
        return False

    status = _status_value(task.get("status"))
    kind = str(task.get("kind") or "")
    return status in config.get("notify_statuses", []) and kind in config.get("notify_kinds", [])


def build_task_message(task: dict[str, Any]) -> str:
    """Build a concise Markdown message for a finished task."""
    status = _status_value(task.get("status"))
    title = str(task.get("title") or task.get("kind") or "未知任务")
    prefix = STATUS_TITLE_PREFIX.get(status, "ASC 任务通知")

    lines = [
        f"**{prefix}：{title}**",
        f"应用/Profile：{task.get('profile') or '-'}",
        f"状态：{STATUS_LABELS.get(status, status or '-')}",
        f"耗时：{task.get('duration_label') or '-'}",
        f"完成时间：{task.get('completed_at') or '-'}",
        f"任务 ID：{str(task.get('id') or '')[:8] or '-'}",
    ]

    result = task.get("result")
    result_error = result.get("error") if isinstance(result, dict) else None
    if status == "error" and result_error:
        lines.append(f"错误：{result_error}")
    elif status == "canceled":
        lines.append("结果：用户取消")

    if status == "error":
        logs = task.get("logs") if isinstance(task.get("logs"), list) else []
        excerpt = [str(line) for line in logs[-5:] if line is not None]
        if excerpt:
            lines.append("最近日志：")
            lines.extend(f"> {line}" for line in excerpt)

    return "\n".join(lines)


def notify_task_finished(task_id: str, *, task_store: Any) -> list[dict[str, Any]]:
    """Send configured webhook notifications for a finished task."""
    task = task_store.get(task_id)
    if task is None:
        return []

    config = load_webhook_config()
    if not should_notify(task, config):
        return []

    text = build_task_message(task)
    results = []
    providers = config.get("providers", {})
    for provider in PROVIDERS:
        provider_config = providers.get(provider, {})
        if not provider_config.get("enabled") or not provider_config.get("url"):
            continue

        result = webhook_clients.send_provider(provider, provider_config, text)
        results.append(result)
        if result.get("ok"):
            task_store.append_log(task_id, f"群通知已发送：{provider}")
        else:
            error = result.get("error") or "Unknown error"
            task_store.append_log(task_id, f"群通知发送失败：{provider} {error}")

    return results
