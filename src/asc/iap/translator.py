"""IAP display-name / description translator (not What's New release notes)."""
from __future__ import annotations

import json
from typing import Any, Optional

from asc.iap.models import DESCRIPTION_MAX, NAME_MAX, NAME_MIN
from asc.services.translator import OpenAITranslator

TRANSLATE_PROMPT = (
    "You are a professional App Store in-app purchase copy translator.\n"
    "Translate IAP / subscription customer-facing text into the target language.\n\n"
    "Hard limits (Apple):\n"
    "- display name: {name_min}–{name_max} characters\n"
    "- description: at most {desc_max} characters (omit if the source has no description)\n\n"
    "Requirements:\n"
    "- Keep the product meaning; do not add slogans, poetry, or marketing fluff\n"
    "- Do not mention App Store review, prices, or legal terms unless they are in the source\n"
    "- Do not wrap the result in quotes\n"
    "- Return JSON only, no markdown:\n"
    '  {{"name": "...", "description": "..."}}\n'
    "- If there is no description to translate, return description as an empty string\n\n"
    "{source_lang}"
    "Target language: {target_locale}\n\n"
    "Source name: {name}\n"
    "Source description: {description}\n"
)

REWRITE_PROMPT = (
    "You are a professional App Store in-app purchase copywriter.\n"
    "Rewrite the customer-facing IAP / subscription text in the target language.\n\n"
    "Hard limits (Apple):\n"
    "- display name: {name_min}–{name_max} characters\n"
    "- description: at most {desc_max} characters (omit if the source has no description)\n\n"
    "Requirements:\n"
    "- Keep the same product meaning\n"
    "- Prefer clear, specific wording over hype\n"
    "- Do not add slogans, poetry, or extra benefits that are not in the source\n"
    "- Return JSON only:\n"
    '  {{"name": "...", "description": "..."}}\n\n'
    "{source_lang}"
    "Target language: {target_locale}\n\n"
    "Current name: {name}\n"
    "Current description: {description}\n"
)


def clip_name(value: str) -> str:
    text = (value or "").strip()
    if len(text) > NAME_MAX:
        text = text[:NAME_MAX].rstrip()
    return text


def clip_description(value: str) -> str:
    text = (value or "").strip()
    if len(text) > DESCRIPTION_MAX:
        text = text[:DESCRIPTION_MAX].rstrip()
    return text


class IapTranslator:
    """Translate or rewrite IAP localizations via LLMClient."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def translate_fields(
        self,
        *,
        source_locale: str,
        target_locale: str,
        name: str,
        description: Optional[str] = None,
        mode: str = "translate",
    ) -> dict[str, str]:
        include_desc = description is not None
        source_lang = (
            f"Source language: {source_locale}\n"
            if source_locale and source_locale != "auto"
            else ""
        )
        template = REWRITE_PROMPT if mode == "rewrite" else TRANSLATE_PROMPT
        prompt = template.format(
            name_min=NAME_MIN,
            name_max=NAME_MAX,
            desc_max=DESCRIPTION_MAX,
            source_lang=source_lang,
            target_locale=target_locale,
            name=name or "",
            description=description if include_desc else "",
        )
        messages = [
            {
                "role": "system",
                "content": "You write App Store IAP display names within Apple character limits.",
            },
            {"role": "user", "content": prompt},
        ]
        content = self.client.chat(messages=messages, temperature=0.3)
        parsed = _extract_fields(content)
        out_name = clip_name(parsed.get("name") or name)
        out_desc = clip_description(parsed.get("description") or "") if include_desc else ""
        result = {"locale": target_locale, "name": out_name}
        if include_desc:
            result["description"] = out_desc
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
            name = data.get("name") or data.get("translation") or ""
            desc = data.get("description") or ""
            return {
                "name": str(name).strip() if isinstance(name, str) else "",
                "description": str(desc).strip() if isinstance(desc, str) else "",
            }
    # Fallback: whole blob is the name.
    return {"name": candidate, "description": ""}


def make_iap_translator(config) -> IapTranslator:
    from asc.llm import LLMClient

    client = LLMClient(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
    )
    return IapTranslator(client)
