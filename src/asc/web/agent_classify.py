"""Rule-based classification of failed web tasks from logs and result."""
from __future__ import annotations

import json
import re
from typing import Any

from asc.web.agent_redact import redact_text
from asc.web.agent_tools import _select_log_lines
from asc.web.i18n import t

_HINT_KEYS = {
    "no_editable_version": "agent.failure.no_editable_version",
    "screenshot_size": "agent.failure.screenshot_size",
    "territory_code": "agent.failure.territory_code",
    "create_only_skip": "agent.failure.create_only_skip",
    "rate_limited": "agent.failure.rate_limited",
    "auth": "agent.failure.auth",
    "unknown": "agent.failure.unknown",
}

_HINT_FALLBACKS = {
    "no_editable_version": {
        "zh": "没有可编辑的 App Store 版本，请先在 Connect 创建或打开可编辑版本。",
        "en": "No editable App Store version. Create or open an editable version in App Store Connect.",
    },
    "screenshot_size": {
        "zh": "截图尺寸无法映射到设备类型，请核对像素与文件夹命名。",
        "en": "Screenshot size does not map to a device type. Check pixels and folder names.",
    },
    "territory_code": {
        "zh": "地区代码应为 3 位（如 USA），不要用 US/CN。",
        "en": "Territory codes must be 3-letter (e.g. USA), not two-letter US/CN.",
    },
    "create_only_skip": {
        "zh": "默认只创建、不覆盖已有项；需要覆盖请使用 --update-existing。",
        "en": "Create-only mode skipped existing items. Use --update-existing to overwrite.",
    },
    "rate_limited": {
        "zh": "触发了 App Store Connect 速率限制，请稍后重试。",
        "en": "App Store Connect rate limit hit. Wait and retry.",
    },
    "auth": {
        "zh": "鉴权失败，请检查 API Key / issuer / token 是否有效。",
        "en": "Authentication failed. Check the API key, issuer, and token.",
    },
    "unknown": {
        "zh": "未能归类失败原因，请查看任务日志。",
        "en": "Could not classify this failure. Inspect the task log.",
    },
}

_RULES: list[tuple[str, list[re.Pattern[str]]]] = [
    (
        "no_editable_version",
        [
            re.compile(r"PREPARE_FOR_SUBMISSION", re.I),
            re.compile(r"no editable", re.I),
            re.compile(r"不可编辑"),
            re.compile(r"没有.*版本"),
        ],
    ),
    (
        "screenshot_size",
        [
            re.compile(r"unmapped", re.I),
            re.compile(r"display type", re.I),
            re.compile(r"\bUNKNOWN\b"),
            re.compile(r"pixel", re.I),
            re.compile(r"尺寸"),
        ],
    ),
    (
        "territory_code",
        [
            re.compile(r"baseTerritory", re.I),
            re.compile(r"3-letter", re.I),
            re.compile(r"\bUSA\b"),
            re.compile(r"two-letter|2-letter|2 letter", re.I),
            re.compile(r"\b(?:US|CN)\b.*territor|\bterritor.*\b(?:US|CN)\b", re.I),
        ],
    ),
    (
        "create_only_skip",
        [
            re.compile(r"create-only", re.I),
            re.compile(r"already exists", re.I),
            re.compile(r"skipped", re.I),
            re.compile(r"已存在"),
        ],
    ),
    (
        "rate_limited",
        [
            re.compile(r"\b429\b"),
            re.compile(r"rate limit", re.I),
            re.compile(r"Retry-After", re.I),
        ],
    ),
    (
        "auth",
        [
            re.compile(r"\b401\b"),
            re.compile(r"\b403\b"),
            re.compile(r"unauthorized", re.I),
            re.compile(r"invalid token", re.I),
        ],
    ),
]


def _localized_hint(code: str, lang: str) -> str:
    key = _HINT_KEYS.get(code, f"agent.failure.{code}")
    fallbacks = _HINT_FALLBACKS.get(code) or {}
    text = t(key, lang=lang)
    if text != key:
        return text
    return fallbacks.get("zh" if lang == "zh" else "en") or key


def _state_corpus(state: dict[str, Any] | None) -> list[str]:
    if not state:
        return []
    chunks: list[str] = []
    result = state.get("result")
    if isinstance(result, str) and result.strip():
        chunks.append(result)
    elif result is not None:
        chunks.append(json.dumps(result, ensure_ascii=False, default=str))
    for key in ("error", "message", "title"):
        value = state.get(key)
        if value:
            chunks.append(str(value))
    return chunks


def _log_corpus(task_store: Any, task_id: str) -> list[str]:
    try:
        entries = task_store.get_logs_after(str(task_id), 0)
    except Exception:
        return []
    if not isinstance(entries, list):
        return []
    selected = _select_log_lines(entries, tail=80)
    return [str(entry.get("message") or "") for entry in selected]


def _match_code(text: str) -> tuple[str, str]:
    for code, patterns in _RULES:
        for pattern in patterns:
            found = pattern.search(text)
            if found:
                start = max(0, found.start() - 40)
                end = min(len(text), found.end() + 40)
                return code, text[start:end]
    return "unknown", text.strip()[:80]


def classify_task_failure(task_store: Any, task_id: str, *, lang: str = "en") -> dict[str, Any]:
    state = None
    try:
        state = task_store.get_state(str(task_id))
    except Exception:
        state = None
    chunks = _state_corpus(state if isinstance(state, dict) else None)
    if state:
        chunks.extend(_log_corpus(task_store, str(task_id)))
    text = "\n".join(chunk for chunk in chunks if chunk)
    code, evidence_raw = _match_code(text)
    evidence = redact_text(evidence_raw).replace("\n", " ").strip()[:160]
    hint = redact_text(_localized_hint(code, lang or "en"))
    return {"ok": True, "code": code, "hint": hint, "evidence": evidence}
