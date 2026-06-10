from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any
from urllib.parse import quote

import requests


def build_feishu_payload(text: str, secret: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": text},
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
            "title": "ASC 任务通知",
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
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}timestamp={timestamp}&sign={sign}"


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

    if 200 <= response.status_code < 300:
        return {"provider": provider, "ok": True}

    return {"provider": provider, "ok": False, "error": f"HTTP {response.status_code}"}
