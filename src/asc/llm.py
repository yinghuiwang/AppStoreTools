from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import requests


class LLMHTTPError(Exception):
    def __init__(
        self,
        status_code: int,
        retry_after: float | None = None,
        *,
        detail: str = "",
        url: str = "",
    ) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        self.detail = detail
        self.url = url
        extra = f" {detail}" if detail else ""
        super().__init__(f"LLM HTTP {status_code}{extra}")


def provider_error_detail(response: Any) -> str:
    """Best-effort provider error text. Truncated; no secrets assumed in body."""
    raw = (getattr(response, "text", None) or "").strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw[:300]
    if not isinstance(data, dict):
        return raw[:300]
    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("msg") or err.get("status_msg")
        if msg:
            return str(msg)[:300]
    if isinstance(err, str) and err.strip():
        return err.strip()[:300]
    base = data.get("base_resp")
    if isinstance(base, dict):
        msg = base.get("status_msg") or base.get("message")
        code = base.get("status_code")
        if msg and code is not None:
            return f"{code}: {msg}"[:300]
        if msg:
            return str(msg)[:300]
    msg = data.get("message") or data.get("msg")
    if msg:
        return str(msg)[:300]
    return json.dumps(data, ensure_ascii=False)[:300]


def _raise_http_error(
    response: Any,
    retry_after: float | None = None,
) -> None:
    detail = provider_error_detail(response)
    url = str(getattr(response, "url", "") or "")
    closer = getattr(response, "close", None)
    if callable(closer):
        closer()
    raise LLMHTTPError(
        int(getattr(response, "status_code", 0) or 0),
        retry_after=retry_after,
        detail=detail,
        url=url,
    )


class LLMClient:
    """OpenAI-compatible chat completion client with retry and timeout."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 180,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, messages: list[dict], temperature: float = 0.3) -> str:
        """Send a chat completion request and return the assistant's message."""
        url = self._chat_completions_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            "response_format": {"type": "json_object"},
        }

        for attempt in range(3):
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "1")
                time.sleep(float(retry_after))
                continue

            if response.status_code >= 500:
                time.sleep(1)
                continue

            data = self._parse_response_data(response)

            if not data.get("choices"):
                raise ValueError(f"Unexpected response: {data}")

            choice = data["choices"][0]
            if "message" not in choice:
                raise ValueError(f"Unexpected response: {data}")

            return choice["message"]["content"]

        raise ValueError("Max retries exceeded")

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.3,
    ) -> Iterator[dict[str, Any]]:
        url = self._chat_completions_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        response = requests.post(
            url, json=payload, headers=headers, timeout=self.timeout, stream=True,
        )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "1")
            try:
                wait = float(retry_after)
            except ValueError:
                wait = 1.0
            _raise_http_error(response, retry_after=wait)
        if response.status_code >= 500:
            _raise_http_error(response, retry_after=1.0)
        if response.status_code >= 400:
            _raise_http_error(response)
        try:
            for raw in response.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                line = raw.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                usage = obj.get("usage")
                if usage:
                    yield {"usage": usage}
                for choice in obj.get("choices") or []:
                    delta = choice.get("delta") or {}
                    event: dict[str, Any] = {}
                    if delta.get("role"):
                        event["role"] = delta["role"]
                    if delta.get("content"):
                        event["content"] = delta["content"]
                    if delta.get("tool_calls"):
                        event["tool_calls"] = delta["tool_calls"]
                    finish = choice.get("finish_reason")
                    if finish:
                        event["finish_reason"] = finish
                    if event:
                        yield event
        finally:
            response.close()

    def _chat_completions_url(self) -> str:
        """Return a usable chat-completions URL for root or fully-qualified base URLs."""
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    @staticmethod
    def _parse_response_data(response: requests.Response) -> dict[str, Any]:
        """Parse OpenAI-compatible JSON, with fallbacks for concatenated/SSE payloads."""
        try:
            data = response.json()
            if isinstance(data, dict):
                return data
        except ValueError:
            pass

        text = (response.text or "").strip()
        if not text:
            raise ValueError("Unexpected empty response")

        parsed = LLMClient._parse_concatenated_json(text)
        if parsed is not None:
            return parsed

        parsed = LLMClient._parse_sse_data_lines(text)
        if parsed is not None:
            return parsed

        raise ValueError(f"Unexpected response: {text[:200]}")

    @staticmethod
    def _parse_concatenated_json(text: str) -> dict[str, Any] | None:
        decoder = json.JSONDecoder()
        index = 0
        while index < len(text):
            while index < len(text) and text[index].isspace():
                index += 1
            if index >= len(text):
                break
            try:
                obj, end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                return None
            if isinstance(obj, dict) and "choices" in obj:
                return obj
            index = end
        return None

    @staticmethod
    def _parse_sse_data_lines(text: str) -> dict[str, Any] | None:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("data:"):
                continue
            payload = stripped[5:].strip()
            if payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "choices" in obj:
                return obj
        return None
