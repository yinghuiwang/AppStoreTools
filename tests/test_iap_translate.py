"""Tests for IAP-specific translator prompt and character limits."""
from __future__ import annotations

from asc.iap.models import DESCRIPTION_MAX, NAME_MAX
from asc.iap.translator import (
    REWRITE_PROMPT,
    TRANSLATE_PROMPT,
    IapTranslator,
    clip_description,
    clip_name,
)


class _FakeClient:
    def __init__(self, content: str):
        self.content = content
        self.messages = None

    def chat(self, messages, temperature=0.3):
        self.messages = messages
        self.temperature = temperature
        return self.content


def test_prompts_are_iap_not_whats_new():
    assert "in-app purchase" in TRANSLATE_PROMPT.lower() or "IAP" in TRANSLATE_PROMPT
    assert "update notes" not in TRANSLATE_PROMPT.lower()
    assert "TestFlight" not in TRANSLATE_PROMPT
    assert "{name_max}" in TRANSLATE_PROMPT
    assert "{desc_max}" in TRANSLATE_PROMPT
    assert "rewrite" in REWRITE_PROMPT.lower() or "Rewrite" in REWRITE_PROMPT


def test_clip_name_and_description():
    assert len(clip_name("x" * 80)) == NAME_MAX
    assert len(clip_description("d" * 80)) == DESCRIPTION_MAX


def test_translate_fields_parses_json_and_clips():
    client = _FakeClient(
        '{"name": "' + ("N" * 40) + '", "description": "' + ("D" * 60) + '"}'
    )
    translator = IapTranslator(client)
    result = translator.translate_fields(
        source_locale="en-US",
        target_locale="zh-Hans",
        name="Coins",
        description="Get coins now.",
        mode="translate",
    )
    assert result["locale"] == "zh-Hans"
    assert len(result["name"]) <= NAME_MAX
    assert len(result["description"]) <= DESCRIPTION_MAX
    prompt = client.messages[1]["content"]
    assert "Coins" in prompt
    assert "Get coins now." in prompt
    assert "poetry" in prompt.lower() or "fluff" in prompt.lower() or "slogan" in prompt.lower()


def test_rewrite_mode_uses_rewrite_prompt():
    client = _FakeClient('{"name": "Pro", "description": "Full access."}')
    translator = IapTranslator(client)
    translator.translate_fields(
        source_locale="en-US",
        target_locale="en-US",
        name="Pro",
        description="Full access.",
        mode="rewrite",
    )
    prompt = client.messages[1]["content"]
    assert "Rewrite" in prompt or "rewrite" in prompt


def test_group_localization_omits_description_key():
    client = _FakeClient('{"name": "Premium", "description": "ignored"}')
    translator = IapTranslator(client)
    result = translator.translate_fields(
        source_locale="en-US",
        target_locale="ja",
        name="Premium",
        description=None,
        mode="translate",
    )
    assert "description" not in result
    assert result["name"] == "Premium"
