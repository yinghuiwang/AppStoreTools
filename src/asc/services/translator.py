from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.asc.llm import LLMClient


class Translator(ABC):
    """Abstract base class for translation services."""

    @abstractmethod
    def translate(self, text: str, target_locale: str, source_locale: str) -> str:
        """Translate `text` from source_locale to target_locale."""
        ...


class OpenAITranslator(Translator):
    """OpenAI-based translation service using LLMClient."""

    SYSTEM_PROMPT = (
        "You are a professional App Store update-notes translator.\n"
        "Translate the following update notes into the target language.\n\n"
        "Requirements:\n"
        "- Keep the original tone and format\n"
        "- Preserve professional terminology (e.g. do not translate 'TestFlight')\n"
        "- Keep character length close to the original\n"
        "- Do not add explanations\n\n"
        "Return a JSON object with a single key named `translation` and no extra text.\n\n"
        "{source_lang}"
        "Target language: {target_locale}\n\n"
        "Original text:\n"
        "{text}"
    )

    def __init__(self, client: "LLMClient") -> None:
        self.client = client

    def translate(self, text: str, target_locale: str, source_locale: str) -> str:
        source_lang = f"Source language: {source_locale}\n" if source_locale and source_locale != "auto" else ""
        prompt = self.SYSTEM_PROMPT.format(
            source_lang=source_lang,
            target_locale=target_locale,
            text=text,
        )
        messages = [
            {"role": "system", "content": "You are a professional translator."},
            {"role": "user", "content": prompt},
        ]
        content = self.client.chat(messages=messages, temperature=0.3)
        return self._extract_translation(content)

    @staticmethod
    def _extract_translation(content: str) -> str:
        """Extract translated text from JSON responses or strip stray thinking blocks."""
        text = (content or "").strip()
        if not text:
            return ""

        if "<think>" in text and "</think>" in text:
            text = text.split("</think>", 1)[-1].strip()

        text = OpenAITranslator._strip_code_fence(text)

        if text.startswith("{") and text.endswith("}"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return text

            if isinstance(data, dict):
                for key in ("translation", "text", "content", "result"):
                    value = data.get(key)
                    if isinstance(value, str):
                        return value.strip()
                if len(data) == 1:
                    value = next(iter(data.values()))
                    if isinstance(value, str):
                        return value.strip()

        return text

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """Remove a single fenced markdown code block wrapper if present."""
        match = re.fullmatch(r"```(?:[a-zA-Z0-9_-]+)?\s*\n?(.*?)\n?```", text, flags=re.DOTALL)
        if match:
            return match.group(1).strip()
        return text
