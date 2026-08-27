from __future__ import annotations

import json

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
        assert m.call_count >= 2


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
        assert m.call_count >= 2


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
        assert m.call_count >= 3


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
        assert body["response_format"] == {"type": "json_object"}


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


def test_chat_accepts_full_chat_completions_base_url():
    """Supports configs that already include /chat/completions in base_url."""
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.minimaxi.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "OK"}}]},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.minimaxi.com/v1/chat/completions",
            model="MiniMax-M2.7",
        )
        result = client.chat([{"role": "user", "content": "Hi"}])
        assert result == "OK"
        assert m.last_request.url == "https://api.minimaxi.com/v1/chat/completions"


def test_chat_falls_back_to_concatenated_json_response():
    """Falls back when a proxy returns concatenated JSON objects."""
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            text='{"meta":true}{"choices":[{"message":{"content":"Fallback OK"}}]}',
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        result = client.chat([{"role": "user", "content": "Hi"}])
        assert result == "Fallback OK"


def test_chat_falls_back_to_sse_data_lines():
    """Falls back when a proxy returns SSE-style data lines."""
    from asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            text='data: {"choices":[{"message":{"content":"SSE OK"}}]}\n\ndata: [DONE]\n',
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4",
        )
        result = client.chat([{"role": "user", "content": "Hi"}])
        assert result == "SSE OK"


def test_chat_timeout_defaults_to_180():
    """Default timeout is 180s."""
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

        assert captured_timeout == 180


def test_chat_stream_yields_content_and_tool_call_deltas():
    from src.asc.llm import LLMClient

    sse = (
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"get_task","arguments":"{"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"}"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            text=sse,
            headers={"Content-Type": "text/event-stream"},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
        )
        events = list(
            client.chat_stream(
                [{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "get_task"}}],
            )
        )
    body = json.loads(m.last_request.text)
    assert body["stream"] is True
    assert "response_format" not in body
    assert body["tools"][0]["function"]["name"] == "get_task"
    contents = "".join(e.get("content", "") for e in events)
    assert "Hello" in contents
    assert any(e.get("finish_reason") == "tool_calls" for e in events)
    assert any("tool_calls" in e for e in events)


def test_chat_stream_raises_llm_http_error_on_429():
    from src.asc.llm import LLMClient, LLMHTTPError

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            status_code=429,
            headers={"Retry-After": "2"},
            json={"error": "rate limited"},
        )
        client = LLMClient(api_key="k", base_url="https://api.openai.com/v1", model="gpt-4o")
        with pytest.raises(LLMHTTPError) as exc:
            list(client.chat_stream([], tools=[]))
        assert exc.value.status_code == 429
        assert exc.value.retry_after == 2.0
        assert exc.value.detail == "rate limited"


def test_chat_stream_captures_minimax_error_body():
    from src.asc.llm import LLMClient, LLMHTTPError

    with rm.Mocker() as m:
        m.post(
            "https://api.minimaxi.com/v1/chat/completions",
            status_code=401,
            json={"base_resp": {"status_code": 2049, "status_msg": "invalid api key"}},
        )
        client = LLMClient(
            api_key="k",
            base_url="https://api.minimaxi.com/v1",
            model="MiniMax-M2.5",
        )
        with pytest.raises(LLMHTTPError) as exc:
            list(client.chat_stream([], tools=[]))
        assert exc.value.status_code == 401
        assert "invalid api key" in exc.value.detail
        assert "api.minimaxi.com" in exc.value.url


def test_chat_still_sends_json_object_without_tools():
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "{}"}}]},
        )
        LLMClient(api_key="k", base_url="https://api.openai.com/v1", model="gpt-4o").chat(
            [{"role": "user", "content": "x"}]
        )
        body = json.loads(m.last_request.text)
        assert body["stream"] is False
        assert body["response_format"] == {"type": "json_object"}
        assert "tools" not in body
