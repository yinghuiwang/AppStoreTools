from __future__ import annotations

import pytest
import requests_mock as rm


def test_chat_returns_assistant_message():
    """Successful response returns content."""
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={
                "choices": [{"message": {"content": "Hello, world!"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        result = client.chat([{"role": "user", "content": "Hi"}])
        assert result == "Hello, world!"


def test_chat_retries_on_429_then_succeeds():
    """Retries on 429, succeeds on 2nd attempt."""
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            [
                {"status_code": 429, "headers": {"Retry-After": "2"}, "json": {"error": "rate limited"}},
                {"json": {"choices": [{"message": {"content": "Success after retry"}}]}},
            ],
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        result = client.chat([{"role": "user", "content": "Hi"}])
        assert result == "Success after retry"
        assert m.call_count == 2


def test_chat_retries_on_5xx_then_succeeds():
    """Retries on 5xx, succeeds on 2nd attempt."""
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            [
                {"status_code": 500, "json": {"error": "internal error"}},
                {"json": {"choices": [{"message": {"content": "Success after retry"}}]}},
            ],
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        result = client.chat([{"role": "user", "content": "Hi"}])
        assert result == "Success after retry"
        assert m.call_count == 2


def test_chat_raises_after_max_retries():
    """Raises ValueError after 3 failures."""
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            [
                {"status_code": 429, "headers": {"Retry-After": "1"}, "json": {"error": "rate limited"}},
                {"status_code": 429, "headers": {"Retry-After": "1"}, "json": {"error": "rate limited"}},
                {"status_code": 429, "headers": {"Retry-After": "1"}, "json": {"error": "rate limited"}},
            ],
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        with pytest.raises(ValueError, match="Max retries exceeded"):
            client.chat([{"role": "user", "content": "Hi"}])
        assert m.call_count == 3


def test_chat_raises_on_empty_choices():
    """Raises ValueError when choices is empty."""
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10}},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        with pytest.raises(ValueError, match="Unexpected response"):
            client.chat([{"role": "user", "content": "Hi"}])


def test_chat_raises_on_missing_message_field():
    """Raises ValueError when choice missing 'message'."""
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"finish_reason": "stop"}], "usage": {}},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        with pytest.raises(ValueError, match="Unexpected response"):
            client.chat([{"role": "user", "content": "Hi"}])


def test_chat_sends_correct_headers():
    """Authorization Bearer + Content-Type sent."""
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "OK"}}]},
        )
        client = LLMClient(
            api_key="my-secret-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        client.chat([{"role": "user", "content": "Hi"}])

        assert m.last_request.headers["Authorization"] == "Bearer my-secret-key"
        assert m.last_request.headers["Content-Type"] == "application/json"


def test_chat_sends_correct_payload():
    """model, messages, temperature in body."""
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "OK"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
        )
        messages = [{"role": "user", "content": "Hello"}]
        client.chat(messages, temperature=0.7)

        import json

        body = json.loads(m.last_request.text)
        assert body["model"] == "gpt-4o"
        assert body["messages"] == messages
        assert body["temperature"] == 0.7


def test_chat_base_url_trailing_slash_stripped():
    """No double slash in URL."""
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "OK"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1/",  # trailing slash
            model="gpt-4",
        )
        client.chat([{"role": "user", "content": "Hi"}])
        assert m.last_request.url == "https://api.openai.com/v1/chat/completions"


def test_chat_timeout_defaults_to_60():
    """Default timeout is 60s."""
    import requests
    from src.asc.llm import LLMClient

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
        # Patch post to capture timeout argument
        original_post = requests.post

        captured_timeout = None

        def capture_post(url, **kwargs):
            nonlocal captured_timeout
            captured_timeout = kwargs.get("timeout")
            return original_post(url, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(requests, "post", capture_post)
            client.chat([{"role": "user", "content": "Hi"}])

        assert captured_timeout == 60
