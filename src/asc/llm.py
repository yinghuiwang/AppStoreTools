from __future__ import annotations

import time
from typing import Any

import requests


class LLMClient:
    """OpenAI-compatible chat completion client with retry and timeout."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, messages: list[dict], temperature: float = 0.3) -> str:
        """Send a chat completion request and return the assistant's message."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
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

            data = response.json()

            if not data.get("choices"):
                raise ValueError(f"Unexpected response: {data}")

            choice = data["choices"][0]
            if "message" not in choice:
                raise ValueError(f"Unexpected response: {data}")

            return choice["message"]["content"]

        raise ValueError("Max retries exceeded")
