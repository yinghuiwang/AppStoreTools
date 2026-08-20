"""App Store listing copy translator (name / subtitle / keywords / description)."""
from __future__ import annotations

import json
from typing import Any, Optional

from asc.listing.models import (
    DESCRIPTION_MAX,
    KEYWORDS_MAX,
    NAME_MAX,
    NAME_MIN,
    SUBTITLE_MAX,
    TEXT_FIELDS,
)
from asc.services.translator import OpenAITranslator

TRANSLATE_PROMPT = (
    "You are a professional App Store product-page copy translator.\n"
    "Translate App Store listing text into the target language.\n\n"
    "Hard limits (Apple):\n"
    "- name: {name_min}–{name_max} characters\n"
    "- subtitle: at most {subtitle_max} characters\n"
    "- keywords: at most {keywords_max} characters (comma-separated, no space after commas)\n"
    "- description: at most {desc_max} characters, plain text, no HTML\n\n"
    "Requirements:\n"
    "- Keep the product meaning; do not add slogans or extra claims\n"
    "- Do not wrap the result in quotes\n"
    "- Return JSON only, no markdown:\n"
    '  {{"name": "...", "subtitle": "...", "keywords": "...", "description": "..."}}\n'
    "- Omit a key or use an empty string if that field was not in the source\n\n"
    "{source_lang}"
    "Target language: {target_locale}\n\n"
    "Source name: {name}\n"
    "Source subtitle: {subtitle}\n"
    "Source keywords: {keywords}\n"
    "Source description: {description}\n"
)

REWRITE_PROMPT = (
    "You are a professional App Store product-page copywriter.\n"
    "Rewrite the listing text in the target language.\n\n"
    "Hard limits (Apple):\n"
    "- name: {name_min}–{name_max} characters\n"
    "- subtitle: at most {subtitle_max} characters\n"
    "- keywords: at most {keywords_max} characters (comma-separated, no space after commas)\n"
    "- description: at most {desc_max} characters, plain text, no HTML\n\n"
    "Requirements:\n"
    "- Keep the same product meaning\n"
    "- Prefer clear, specific wording over hype\n"
    "- Return JSON only:\n"
    '  {{"name": "...", "subtitle": "...", "keywords": "...", "description": "..."}}\n\n'
    "{source_lang}"
    "Target language: {target_locale}\n\n"
    "Current name: {name}\n"
    "Current subtitle: {subtitle}\n"
    "Current keywords: {keywords}\n"
    "Current description: {description}\n"
)

KEYWORDS_PROMPT = (
    "You are a professional App Store keyword writer.\n"
    "Write search keywords for the App Store product page in the target language.\n\n"
    "Hard limits (Apple):\n"
    "- at most {keywords_max} characters\n"
    "- comma-separated, no space after commas\n"
    "- do not repeat the app name or company name\n"
    "- no # or @ unless part of the brand\n\n"
    "Return JSON only: {{\"keywords\": \"...\"}}\n\n"
    "{source_lang}"
    "Target language: {target_locale}\n\n"
    "Source name: {name}\n"
    "Source subtitle: {subtitle}\n"
    "Source keywords: {keywords}\n"
    "Source description: {description}\n"
)


def clip_name(value: str) -> str:
    text = (value or "").strip()
    if len(text) > NAME_MAX:
        text = text[:NAME_MAX].rstrip()
    return text


def clip_subtitle(value: str) -> str:
    text = (value or "").strip()
    if len(text) > SUBTITLE_MAX:
        text = text[:SUBTITLE_MAX].rstrip()
    return text


def clip_keywords(value: str) -> str:
    text = (value or "").strip()
    if len(text) > KEYWORDS_MAX:
        text = text[:KEYWORDS_MAX].rstrip().rstrip(",")
    return text


def clip_description(value: str) -> str:
    text = (value or "").strip()
    if len(text) > DESCRIPTION_MAX:
        text = text[:DESCRIPTION_MAX].rstrip()
    return text


class ListingTranslator:
    """Translate or rewrite listing copy via LLMClient."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def translate_fields(
        self,
        *,
        source_locale: str,
        target_locale: str,
        fields: dict[str, str],
        mode: str = "translate",
    ) -> dict[str, str]:
        source_lang = (
            f"Source language: {source_locale}\n"
            if source_locale and source_locale != "auto"
            else ""
        )
        if mode == "keywords":
            template = KEYWORDS_PROMPT
        elif mode == "rewrite":
            template = REWRITE_PROMPT
        else:
            template = TRANSLATE_PROMPT
        prompt = template.format(
            name_min=NAME_MIN,
            name_max=NAME_MAX,
            subtitle_max=SUBTITLE_MAX,
            keywords_max=KEYWORDS_MAX,
            desc_max=DESCRIPTION_MAX,
            source_lang=source_lang,
            target_locale=target_locale,
            name=fields.get("name") or "",
            subtitle=fields.get("subtitle") or "",
            keywords=fields.get("keywords") or "",
            description=fields.get("description") or "",
        )
        messages = [
            {
                "role": "system",
                "content": "You write App Store listing copy within Apple character limits.",
            },
            {"role": "user", "content": prompt},
        ]
        content = self.client.chat(messages=messages, temperature=0.3)
        parsed = _extract_fields(content)
        result = {"locale": target_locale}
        if mode == "keywords":
            result["keywords"] = clip_keywords(parsed.get("keywords") or fields.get("keywords") or "")
            return result
        for name in TEXT_FIELDS:
            raw = parsed.get(name)
            if raw is None and name not in fields:
                continue
            value = raw if raw is not None else fields.get(name) or ""
            if name == "name":
                result[name] = clip_name(value)
            elif name == "subtitle":
                result[name] = clip_subtitle(value)
            elif name == "keywords":
                result[name] = clip_keywords(value)
            else:
                result[name] = clip_description(value)
        return result


def _extract_fields(content: str) -> dict[str, str]:
    text = OpenAITranslator._extract_translation(content)
    if not text:
        return {}
    candidate = text.strip()
    if candidate.startswith("{") and candidate.endswith("}"):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            out: dict[str, str] = {}
            for key in (*TEXT_FIELDS, "translation"):
                value = data.get(key)
                if isinstance(value, str):
                    out["name" if key == "translation" else key] = value.strip()
            return out
    return {"name": candidate, "description": ""}


def make_listing_translator(config) -> ListingTranslator:
    from asc.llm import LLMClient

    client = LLMClient(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
    )
    return ListingTranslator(client)
