from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from typing import Any
from urllib.parse import quote

import requests

_BOLD_SEGMENT_RE = re.compile(r"\*\*(.+?)\*\*")


def strip_markdown_bold(text: str) -> str:
    return _BOLD_SEGMENT_RE.sub(r"\1", text)


def _first_line_title(text: str) -> str:
    first = str(text).split("\n", 1)[0]
    return strip_markdown_bold(first).strip() or "ASC 任务通知"


def build_feishu_payload(text: str, secret: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": strip_markdown_bold(text)},
    }
    if not secret:
        return payload

    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        b"",
        digestmod=hashlib.sha256,
    ).digest()
    payload["timestamp"] = timestamp
    payload["sign"] = base64.b64encode(digest).decode("utf-8")
    return payload


def build_wecom_payload(text: str, secret: str = "") -> dict[str, Any]:
    return {"msgtype": "markdown", "markdown": {"content": text}}


def build_dingtalk_payload(text: str, secret: str = "") -> dict[str, Any]:
    return {
        "msgtype": "markdown",
        "markdown": {
            "title": _first_line_title(text),
            "text": text,
        },
    }


def build_dingtalk_url(url: str, secret: str = "") -> str:
    if not secret:
        return url

    timestamp = str(int(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = quote(base64.b64encode(digest).decode("utf-8"), safe="")
    if url.endswith(("?", "&")):
        separator = ""
    else:
        separator = "&" if "?" in url else "?"
    return f"{url}{separator}timestamp={timestamp}&sign={sign}"


def _response_json(response: Any) -> dict[str, Any] | None:
    parser = getattr(response, "json", None)
    if not callable(parser):
        return None
    try:
        body = parser()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def _nonzero_code(body: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in body:
            continue
        value = body[key]
        if value not in (0, "0", None, ""):
            return value
    return None


def _provider_http_error(provider: str, response: Any) -> str | None:
    if not (200 <= response.status_code < 300):
        return f"HTTP {response.status_code}"
    body = _response_json(response)
    if not body:
        return None
    provider_name = provider.lower()
    if provider_name == "feishu":
        code = _nonzero_code(body, "code", "StatusCode")
        if code is None:
            return None
        message = str(body.get("msg") or body.get("StatusMessage") or "request failed")
        return f"{code} {message}"[:200]
    if provider_name in {"wecom", "dingtalk"}:
        code = _nonzero_code(body, "errcode")
        if code is None:
            return None
        message = str(body.get("errmsg") or "request failed")
        return f"{code} {message}"[:200]
    return None


def send_provider(
    provider: str,
    config: dict[str, Any],
    text: str,
    *,
    timeout: int = 5,
) -> dict[str, Any]:
    url = str(config.get("url") or "")
    secret = str(config.get("secret") or "")
    provider_name = provider.lower()
    from asc.web.security import is_safe_outbound_url

    if url and not is_safe_outbound_url(url, resolve=True):
        return {"provider": provider, "ok": False, "error": "Unsafe URL"}

    try:
        if provider_name == "feishu":
            payload = build_feishu_payload(text, secret)
        elif provider_name == "wecom":
            payload = build_wecom_payload(text, secret)
        elif provider_name == "dingtalk":
            payload = build_dingtalk_payload(text, secret)
            url = build_dingtalk_url(url, secret)
        else:
            return {"provider": provider, "ok": False, "error": "Unsupported provider"}

        response = requests.post(url, json=payload, timeout=timeout)
    except Exception as exc:
        return {"provider": provider, "ok": False, "error": exc.__class__.__name__}

    error = _provider_http_error(provider_name, response)
    if error:
        return {"provider": provider, "ok": False, "error": error}
    return {"provider": provider, "ok": True}
