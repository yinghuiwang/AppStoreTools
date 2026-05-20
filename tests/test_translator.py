from __future__ import annotations

import json

import pytest
import requests_mock as rm

from src.asc.llm import LLMClient
from src.asc.services.translator import OpenAITranslator, Translator


def test_translate_calls_llm_with_correct_messages_structure():
    """sends system + user prompt, prompt contains locale info"""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "Translated text"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        translator = OpenAITranslator(client)
        translator.translate("Hello world", target_locale="zh-Hans", source_locale="en")

        body = json.loads(m.last_request.text)
        messages = body["messages"]

        # Should have system and user messages
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        # Prompt should contain locale info
        assert "zh-Hans" in messages[1]["content"]
        assert "en" in messages[1]["content"]


def test_translate_returns_assistant_content():
    """returns the assistant message content"""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "Translated: Bonjour monde"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        translator = OpenAITranslator(client)
        result = translator.translate("Hello world", target_locale="fr", source_locale="en")
        assert result == "Translated: Bonjour monde"


def test_translate_extracts_translation_from_json_object():
    """parses structured JSON content and returns the translation field."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": '{"translation":"测试应用"}'}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        translator = OpenAITranslator(client)
        result = translator.translate("test app", target_locale="zh-Hans", source_locale="auto")
        assert result == "测试应用"


def test_translate_extracts_translation_from_fenced_json_object():
    """parses fenced JSON content and returns the translation field."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "```json\n{\"translation\": \"test app\"}\n```"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        translator = OpenAITranslator(client)
        result = translator.translate("test app", target_locale="en-US", source_locale="auto")
        assert result == "test app"


def test_translate_strips_think_block_when_present():
    """strips stray think blocks if a provider still returns them."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "<think>reasoning</think>\n\n测试应用"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        translator = OpenAITranslator(client)
        result = translator.translate("test app", target_locale="zh-Hans", source_locale="auto")
        assert result == "测试应用"


def test_translate_passes_temperature_0_3():
    """uses temperature=0.3"""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "Result"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        translator = OpenAITranslator(client)
        translator.translate("Hello", target_locale="es", source_locale="en")

        body = json.loads(m.last_request.text)
        assert body["temperature"] == 0.3


def test_translate_uses_client_chat():
    """delegates to LLMClient.chat(), not raw HTTP"""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "OK"}}]},
        )
        llm_client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )

        # Spy on chat method
        original_chat = llm_client.chat
        chat_called = []

        def spy_chat(*args, **kwargs):
            chat_called.append((args, kwargs))
            return original_chat(*args, **kwargs)

        llm_client.chat = spy_chat

        translator = OpenAITranslator(llm_client)
        translator.translate("Test", target_locale="ja", source_locale="en")

        # Verify chat was called
        assert len(chat_called) == 1


def test_translate_multiline_text():
    """handles multiline text correctly in prompt"""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "Translated"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        translator = OpenAITranslator(client)

        multiline_text = "Line 1\nLine 2\nLine 3\n\nLine 5"

        translator.translate(multiline_text, target_locale="de", source_locale="en")

        body = json.loads(m.last_request.text)
        # The multiline text should be in the prompt
        assert "Line 1" in body["messages"][1]["content"]
        assert "Line 2" in body["messages"][1]["content"]
        assert "Line 3" in body["messages"][1]["content"]


def test_translate_special_chars_in_text():
    """handles quotes, newlines, unicode without JSON error"""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "OK"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        translator = OpenAITranslator(client)

        special_text = 'Hello "world" with\nnewlines\tand unicode: \u4e2d\u6587'

        # Should not raise JSON error
        translator.translate(special_text, target_locale="fr", source_locale="en")

        body = json.loads(m.last_request.text)
        assert "world" in body["messages"][1]["content"]


def test_translate_empty_text_raises():
    """empty text still calls API (returns empty string)"""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": ""}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        translator = OpenAITranslator(client)

        result = translator.translate("", target_locale="zh-Hans", source_locale="en")
        # Empty text still calls API and returns empty string
        assert result == ""
        # Verify API was called
        assert m.call_count == 1


def test_translator_is_instance_of_abstract():
    """OpenAITranslator is instance of Translator"""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "OK"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        translator = OpenAITranslator(client)
        assert isinstance(translator, Translator)


def test_translate_system_prompt_contains_requirements():
    """system prompt includes professional terminology preservation"""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "OK"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        translator = OpenAITranslator(client)
        translator.translate("TestFlight update", target_locale="ja", source_locale="en")

        body = json.loads(m.last_request.text)
        user_content = body["messages"][1]["content"]
        # Should preserve terminology instruction
        assert "TestFlight" in user_content
        # Should have requirements mentioned
        assert "Requirements" in user_content or "requirements" in user_content
