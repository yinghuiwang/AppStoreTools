from __future__ import annotations

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
        return self.client.chat(messages=messages, temperature=0.3)
