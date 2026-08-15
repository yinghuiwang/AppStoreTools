from __future__ import annotations

import json
import re
from typing import Any

from asc.web.notifications import _sanitize_message_text

P8_PATH_RE = re.compile(r"(?i)(?:[^\s'\"]+)?AuthKey_[A-Za-z0-9]+\.p8|[^\s'\"]+\.p8")
ISSUER_RE = re.compile(r"(?i)\b(issuer_id)\s*[=:]\s*([A-Za-z0-9-]+)")
KEY_ID_RE = re.compile(r"(?i)\b(key_id)\s*[=:]\s*([A-Za-z0-9]+)")
API_KEY_RE = re.compile(r"(?i)\b(api_key)\s*[=:]\s*(\S+)")
BARE_BEARER_RE = re.compile(r"(?i)\b(Bearer\s+)([^\s,;]+)")
PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)


def redact_text(value: Any) -> str:
    text = _sanitize_message_text(value)
    text = PEM_BLOCK_RE.sub("[redacted-pem]", text)
    text = P8_PATH_RE.sub("[redacted-p8]", text)
    text = ISSUER_RE.sub(r"\1=[redacted]", text)
    text = KEY_ID_RE.sub(r"\1=[redacted]", text)
    text = API_KEY_RE.sub(r"\1=[redacted]", text)
    text = BARE_BEARER_RE.sub(r"\1[redacted]", text)
    return text


def redact_obj(value: Any, *, max_chars: int | None = None) -> Any:
    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return redact_text(node)
        if isinstance(node, dict):
            return {str(k): walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    walked = walk(value)
    if max_chars is None:
        return walked
    encoded = json.dumps(walked, ensure_ascii=False)
    if len(encoded) <= max_chars:
        return walked
    return {"truncated": True, "preview": redact_text(encoded[:max_chars])}
