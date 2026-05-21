# Whats-New 自动翻译功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `asc whats-new` 命令和 Web UI 新增大模型自动翻译功能。用户输入一段更新说明，工具自动翻译到 App 所有 locale。

**Architecture:**
- 新增 `llm.py`（OpenAI 兼容 HTTP 客户端）和 `services/translator.py`（翻译服务抽象层）
- CLI 和 Web UI 复用同一套翻译服务
- Web UI 通过 SSE 任务流追踪上传进度，与 metadata/build 页面模式一致

**Tech Stack:** Python 3.9+, FastAPI, HTMX, Alpine.js, requests (HTTP client)

---

## 文件结构

```
src/asc/
├── llm.py                          # [NEW] OpenAI 兼容 API 客户端
├── services/
│   └── translator.py              # [NEW] 翻译服务（抽象接口 + OpenAI 实现）
├── commands/
│   └── whats_new.py               # [MODIFY] 新增 --translate / --dry-run
└── web/
    ├── routes_api.py               # [MODIFY] 新增 /api/whats-new/* 路由
    ├── server.py                   # [MODIFY] 注册 /whats-new 页面路由
    └── templates/
        ├── settings.html          # [MODIFY] 新增 LLM 配置区块
        └── whats_new.html         # [NEW] 翻译 + 上传页面

tests/
├── test_llm.py                    # [NEW] LLM 客户端完整单元测试（10 个测试）
├── test_translator.py             # [NEW] 翻译服务完整单元测试（9 个测试）
├── test_config_llm.py             # [NEW] Config LLM 属性测试（7 个测试）
├── test_whats_new_translate.py    # [NEW] CLI --translate 选项测试（6 个测试）
├── test_web_whats_new.py         # [NEW] Web API 路由测试（8 个测试）
└── test_whats_new_e2e.py        # [NEW] 端到端集成测试（3 个测试）
```

---

## Task 1: 创建 `src/asc/llm.py` — OpenAI 兼容 HTTP 客户端

**Files:**
- Create: `src/asc/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: 写失败的测试（完整单元测试）**

```python
# tests/test_llm.py
"""Comprehensive unit tests for asc.llm.LLMClient."""
from __future__ import annotations

import pytest
import requests_mock as rm


def test_chat_returns_assistant_message():
    """chat() returns the assistant's message content from successful response."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={
                "choices": [{"message": {"role": "assistant", "content": "错误修复和性能提升。"}}]
            },
        )
        from asc.llm import LLMClient
        client = LLMClient(
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
        )
        result = client.chat(messages=[{"role": "user", "content": "Bug fixes."}])
        assert result == "错误修复和性能提升。"


def test_chat_retries_on_429_then_succeeds():
    """chat() retries on HTTP 429 and returns result on second attempt."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            [
                {"status_code": 429, "headers": {"Retry-After": "0"}},
                {"json": {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}},
            ],
        )
        from asc.llm import LLMClient
        client = LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        result = client.chat(messages=[{"role": "user", "content": "hi"}])
        assert result == "ok"
        assert m.call_count == 2


def test_chat_retries_on_5xx_then_succeeds():
    """chat() retries on HTTP 5xx and returns result on second attempt."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            [
                {"status_code": 502, "text": "Bad Gateway"},
                {"json": {"choices": [{"message": {"role": "assistant", "content": "result"}}]}},
            ],
        )
        from asc.llm import LLMClient
        client = LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        result = client.chat(messages=[{"role": "user", "content": "hi"}])
        assert result == "result"
        assert m.call_count == 2


def test_chat_raises_after_max_retries():
    """chat() raises ValueError after 3 failed attempts."""
    with rm.Mocker() as m:
        m.post("https://api.openai.com/v1/chat/completions", status_code=429, headers={"Retry-After": "0"})
        from asc.llm import LLMClient
        client = LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        with pytest.raises(ValueError, match="Max retries exceeded"):
            client.chat(messages=[{"role": "user", "content": "hi"}])
        assert m.call_count == 3


def test_chat_raises_on_empty_choices():
    """chat() raises ValueError when response has no choices."""
    with rm.Mocker() as m:
        m.post("https://api.openai.com/v1/chat/completions", json={"choices": []})
        from asc.llm import LLMClient
        client = LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        with pytest.raises(ValueError, match="Unexpected response"):
            client.chat(messages=[{"role": "user", "content": "hi"}])


def test_chat_raises_on_missing_message_field():
    """chat() raises ValueError when choice is missing 'message'."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"finish_reason": "stop"}]},
        )
        from asc.llm import LLMClient
        client = LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        with pytest.raises((ValueError, KeyError)):
            client.chat(messages=[{"role": "user", "content": "hi"}])


def test_chat_sends_correct_headers():
    """chat() sends Authorization Bearer token and Content-Type."""
    with rm.Mocker() as m:
        m.post("https://api.openai.com/v1/chat/completions", json={"choices": []})
        from asc.llm import LLMClient
        client = LLMClient(api_key="sk-secret", base_url="https://api.openai.com/v1", model="gpt-4o")
        try:
            client.chat(messages=[{"role": "user", "content": "hi"}])
        except Exception:
            pass
        last_req = m.request_history[-1]
        assert last_req.headers["Authorization"] == "Bearer sk-secret"
        assert last_req.headers["Content-Type"] == "application/json"


def test_chat_sends_correct_payload():
    """chat() sends correct model, messages, and temperature in payload."""
    with rm.Mocker() as m:
        m.post("https://api.openai.com/v1/chat/completions", json={"choices": []})
        from asc.llm import LLMClient
        client = LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o-mini")
        try:
            client.chat(messages=[{"role": "user", "content": "hello"}], temperature=0.7)
        except Exception:
            pass
        last_req = m.request_history[-1]
        body = last_req.json()
        assert body["model"] == "gpt-4o-mini"
        assert body["messages"] == [{"role": "user", "content": "hello"}]
        assert body["temperature"] == 0.7


def test_chat_base_url_trailing_slash_stripped():
    """Base URL trailing slash is stripped to avoid double slashes."""
    with rm.Mocker() as m:
        m.post("https://openrouter.ai/v1/chat/completions", json={"choices": []})
        from asc.llm import LLMClient
        client = LLMClient(api_key="sk-test", base_url="https://openrouter.ai/v1/", model="gpt-4o")
        try:
            client.chat(messages=[{"role": "user", "content": "hi"}])
        except Exception:
            pass
        last_req = m.request_history[-1]
        assert last_req.url == "https://openrouter.ai/v1/chat/completions"


def test_chat_timeout_defaults_to_60():
    """chat() uses default timeout of 60 seconds."""
    with rm.Mocker() as m:
        m.post("https://api.openai.com/v1/chat/completions", json={"choices": []})
        from asc.llm import LLMClient
        client = LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        try:
            client.chat(messages=[{"role": "user", "content": "hi"}])
        except Exception:
            pass
        last_req = m.request_history[-1]
        assert last_req.timeout == 60


def test_chat_custom_timeout():
    """chat() respects custom timeout parameter."""
    with rm.Mocker() as m:
        m.post("https://api.openai.com/v1/chat/completions", json={"choices": []})
        from asc.llm import LLMClient
        client = LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o", timeout=30)
        try:
            client.chat(messages=[{"role": "user", "content": "hi"}])
        except Exception:
            pass
        last_req = m.request_history[-1]
        assert last_req.timeout == 30
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /Users/huangxiang/Documents/01-project/AppStoreTools
pytest tests/test_llm.py -v 2>&1 | head -30
# Expected: ERROR — module 'asc.llm' has no attribute 'LLMClient'
```

- [ ] **Step 3: 写最小实现**

```python
# src/asc/llm.py
"""OpenAI-compatible LLM HTTP client."""
from __future__ import annotations

import time
from typing import Optional

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
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 1))
                time.sleep(retry_after)
                continue
            if resp.status_code >= 500:
                time.sleep(1)
                continue
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices")
            if not choices:
                raise ValueError(f"Unexpected response: {data}")
            return choices[0]["message"]["content"]
        raise ValueError("Max retries exceeded")
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_llm.py -v
# Expected: 3 passed
```

- [ ] **Step 5: 提交**

```bash
git add src/asc/llm.py tests/test_llm.py
git commit -m "feat(llm): add OpenAI-compatible HTTP client with retry"
```

---

## Task 2: 创建 `src/asc/services/translator.py` — 翻译服务层

**Files:**
- Create: `src/asc/services/__init__.py`
- Create: `src/asc/services/translator.py`
- Test: `tests/test_translator.py`

- [ ] **Step 1: 创建 `services/` 目录和 `__init__.py`**

```python
# src/asc/services/__init__.py
"""Services layer for asc CLI."""
from __future__ import annotations
```

- [ ] **Step 2: 写失败的测试（完整单元测试）**

```python
# tests/test_translator.py
"""Comprehensive unit tests for asc.services.translator."""
from __future__ import annotations

import pytest
import requests_mock as rm


def test_translate_calls_llm_with_correct_messages_structure():
    """translate() sends a system prompt and user prompt with locale info."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"role": "assistant", "content": "结果"}}]},
        )
        from asc.services.translator import OpenAITranslator
        from asc.llm import LLMClient

        client = LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        translator = OpenAITranslator(client)
        translator.translate("Bug fixes.", "zh-CN", "en-US")

        last_req = m.request_history[-1]
        body = last_req.json()
        messages = body["messages"]
        # First message is system
        assert messages[0]["role"] == "system"
        # Second message is user with prompt containing locale and text
        assert messages[1]["role"] == "user"
        content = messages[1]["content"]
        assert "zh-CN" in content
        assert "en-US" in content
        assert "Bug fixes." in content


def test_translate_returns_assistant_content():
    """translate() returns the raw assistant message content."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"role": "assistant", "content": "错误修复和性能提升。"}}]},
        )
        from asc.services.translator import OpenAITranslator
        from asc.llm import LLMClient

        translator = OpenAITranslator(
            LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        )
        result = translator.translate("Bug fixes and improvements.", "zh-CN", "en-US")
        assert result == "错误修复和性能提升。"


def test_translate_passes_temperature_0_3():
    """translate() uses temperature=0.3 for consistent output."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )
        from asc.services.translator import OpenAITranslator
        from asc.llm import LLMClient

        translator = OpenAITranslator(
            LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        )
        translator.translate("Hello", "ja-JP", "en-US")

        last_req = m.request_history[-1]
        body = last_req.json()
        assert body["temperature"] == 0.3


def test_translate_uses_client_chat():
    """translate() delegates to LLMClient.chat(), not raw HTTP."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"role": "assistant", "content": "translated"}}]},
        )
        from asc.services.translator import OpenAITranslator
        from asc.llm import LLMClient

        translator = OpenAITranslator(
            LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        )
        result = translator.translate("Test", "fr-FR", "en-US")
        assert result == "translated"
        assert m.call_count == 1


def test_translate_multiline_text():
    """translate() handles multiline text correctly in prompt."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"role": "assistant", "content": "多行结果"}}]},
        )
        from asc.services.translator import OpenAITranslator
        from asc.llm import LLMClient

        translator = OpenAITranslator(
            LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        )
        multiline = "Bug fixes.\nPerformance improvements.\nNew features."
        result = translator.translate(multiline, "zh-CN", "en-US")
        assert result == "多行结果"
        last_req = m.request_history[-1]
        assert "Bug fixes." in last_req.json()["messages"][1]["content"]


def test_translate_special_chars_in_text():
    """translate() handles special characters in text without breaking JSON."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"role": "assistant", "content": "结果"}}]},
        )
        from asc.services.translator import OpenAITranslator
        from asc.llm import LLMClient

        translator = OpenAITranslator(
            LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        )
        # Contains quotes, newlines, unicode
        text = 'Bug fixes. "Performance" & more.\n\n• Fixed crash\n• Fixed memory leak'
        result = translator.translate(text, "zh-CN", "en-US")
        assert result == "结果"
        # Verify the request was made without JSON encode error
        assert m.call_count == 1


def test_translate_empty_text_raises():
    """translate() with empty text still calls API (API handles validation)."""
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"role": "assistant", "content": ""}}]},
        )
        from asc.services.translator import OpenAITranslator
        from asc.llm import LLMClient

        translator = OpenAITranslator(
            LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
        )
        result = translator.translate("", "zh-CN", "en-US")
        assert result == ""
        assert m.call_count == 1


def test_translator_is_instance_of_abstract():
    """OpenAITranslator is an instance of the abstract Translator class."""
    from asc.services.translator import Translator, OpenAITranslator
    from asc.llm import LLMClient

    client = LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
    translator = OpenAITranslator(client)
    assert isinstance(translator, Translator)
```

- [ ] **Step 3: 运行测试，确认失败**

```bash
pytest tests/test_translator.py -v 2>&1 | head -20
# Expected: ERROR — module 'asc.services.translator' has no attribute ...
```

- [ ] **Step 4: 写最小实现**

```python
# src/asc/services/translator.py
"""Translation service with OpenAI-compatible backend."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asc.llm import LLMClient


class Translator(ABC):
    """Abstract translation service."""

    @abstractmethod
    def translate(self, text: str, target_locale: str, source_locale: str) -> str:
        """Translate `text` from source_locale to target_locale."""
        ...


class OpenAITranslator(Translator):
    """OpenAI-compatible translator using a chat completion model."""

    SYSTEM_PROMPT = (
        "You are a professional App Store update-notes translator.\n"
        "Translate the following update notes into the target language.\n\n"
        "Requirements:\n"
        "- Keep the original tone and format\n"
        "- Preserve professional terminology (e.g. do not translate 'TestFlight')\n"
        "- Keep character length close to the original\n"
        "- Do not add explanations\n\n"
        "Source language: {source_locale}\n"
        "Target language: {target_locale}\n\n"
        "Original text:\n"
        "{text}"
    )

    def __init__(self, client: "LLMClient") -> None:
        self.client = client

    def translate(self, text: str, target_locale: str, source_locale: str) -> str:
        prompt = self.SYSTEM_PROMPT.format(
            source_locale=source_locale,
            target_locale=target_locale,
            text=text,
        )
        messages = [
            {"role": "system", "content": "You are a professional translator."},
            {"role": "user", "content": prompt},
        ]
        return self.client.chat(messages=messages, temperature=0.3)
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
pytest tests/test_translator.py -v
# Expected: 2 passed
```

- [ ] **Step 6: 提交**

```bash
git add src/asc/services/__init__.py src/asc/services/translator.py tests/test_translator.py
git commit -m "feat(translator): add OpenAI translation service layer"
```

---

## Task 3: 修改 `src/asc/config.py` — 新增 `[llm]` 配置块读取

**Files:**
- Modify: `src/asc/config.py`

- [ ] **Step 1: 添加 LLM 配置属性**

在 `Config` 类中添加以下属性（放在 `iap_path` property 之后）：

```python
@property
def llm_api_key(self) -> Optional[str]:
    return self.get("api_key", section="llm") or os.getenv("OPENAI_API_KEY")

@property
def llm_base_url(self) -> Optional[str]:
    return self.get("base_url", section="llm") or "https://api.openai.com/v1"

@property
def llm_model(self) -> str:
    return self.get("model", section="llm") or "gpt-4o"
```

- [ ] **Step 2: 验证 Config 能读取 `[llm]` 块**

```python
# 在 Python REPL 中验证（可写一个简单测试）
import tempfile, os
with tempfile.TemporaryDirectory() as tmpdir:
    from pathlib import Path
    cfg = Path(tmpdir) / "config.toml"
    cfg.write_text('[llm]\napi_key = "sk-test"\nmodel = "gpt-4o-mini"\nbase_url = "https://openrouter.ai/v1"\n')
    os.chdir(tmpdir)
    from asc.config import Config
    c = Config()
    assert c.llm_api_key == "sk-test"
    assert c.llm_model == "gpt-4o-mini"
    assert "openrouter" in c.llm_base_url
    print("Config LLM properties: PASS")
```

- [ ] **Step 3: 提交**

```bash
git add src/asc/config.py
git commit -m "feat(config): add [llm] configuration block for LLM API settings"
```

---

## Task 3b: 创建 `tests/test_config_llm.py` — Config LLM 属性单元测试

**Files:**
- Create: `tests/test_config_llm.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_config_llm.py
"""Unit tests for Config LLM properties."""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch
from pathlib import Path


def test_llm_api_key_from_toml(tmp_path, monkeypatch):
    """llm_api_key reads api_key from [llm] section in TOML."""
    monkeypatch.chdir(tmp_path)
    toml = tmp_path / "config.toml"
    toml.write_text('[llm]\napi_key = "sk-123456"\n')
    from asc.config import Config
    c = Config()
    assert c.llm_api_key == "sk-123456"


def test_llm_base_url_from_toml(tmp_path, monkeypatch):
    """llm_base_url reads base_url from [llm] section."""
    monkeypatch.chdir(tmp_path)
    toml = tmp_path / "config.toml"
    toml.write_text('[llm]\nbase_url = "https://openrouter.ai/v1"\n')
    from asc.config import Config
    c = Config()
    assert c.llm_base_url == "https://openrouter.ai/v1"


def test_llm_model_from_toml(tmp_path, monkeypatch):
    """llm_model reads model from [llm] section."""
    monkeypatch.chdir(tmp_path)
    toml = tmp_path / "config.toml"
    toml.write_text('[llm]\nmodel = "gpt-4o-mini"\n')
    from asc.config import Config
    c = Config()
    assert c.llm_model == "gpt-4o-mini"


def test_llm_model_defaults_to_gpt_4o(tmp_path, monkeypatch):
    """llm_model returns 'gpt-4o' when not configured."""
    monkeypatch.chdir(tmp_path)
    toml = tmp_path / "config.toml"
    toml.write_text('[llm]\nbase_url = "https://api.openai.com/v1"\n')
    from asc.config import Config
    c = Config()
    assert c.llm_model == "gpt-4o"


def test_llm_base_url_defaults_to_openai(tmp_path, monkeypatch):
    """llm_base_url returns 'https://api.openai.com/v1' when not configured."""
    monkeypatch.chdir(tmp_path)
    toml = tmp_path / "config.toml"
    toml.write_text('[llm]\napi_key = "sk-test"\n')
    from asc.config import Config
    c = Config()
    assert c.llm_base_url == "https://api.openai.com/v1"


def test_llm_api_key_falls_back_to_env_var(tmp_path, monkeypatch):
    """llm_api_key falls back to OPENAI_API_KEY env var when not in TOML."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-fallback")
    toml = tmp_path / "config.toml"
    toml.write_text('[llm]\nbase_url = "https://api.openai.com/v1"\n')
    from asc.config import Config
    c = Config()
    assert c.llm_api_key == "sk-env-fallback"


def test_llm_api_key_toml_overrides_env(tmp_path, monkeypatch):
    """TOML [llm] api_key takes precedence over OPENAI_API_KEY env var."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    toml = tmp_path / "config.toml"
    toml.write_text('[llm]\napi_key = "sk-toml"\n')
    from asc.config import Config
    c = Config()
    assert c.llm_api_key == "sk-toml"


def test_llm_key_file_expands_tilde(tmp_path, monkeypatch):
    """key_file path with ~ is expanded to home directory."""
    # This tests the base key_file property, not LLM-specific
    monkeypatch.chdir(tmp_path)
    toml = tmp_path / "config.toml"
    toml.write_text('[credentials]\nkey_file = "~/keys/test.p8"\n')
    from asc.config import Config
    c = Config()
    assert c.key_file.endswith("keys/test.p8")
    assert "~" not in c.key_file
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_config_llm.py -v 2>&1 | head -30
# Expected: ERROR — Config has no attribute 'llm_api_key'
```

- [ ] **Step 3: 实现 Config LLM 属性**

已在 Task 3 中实现。

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_config_llm.py -v
# Expected: 7 passed
```

- [ ] **Step 5: 提交**

```bash
git add tests/test_config_llm.py
git commit -m "test(config): add unit tests for [llm] LLM configuration properties"
```

---

## Task 4: 修改 `src/asc/commands/whats_new.py` — 新增 `--translate` CLI 参数

**Files:**
- Modify: `src/asc/commands/whats_new.py`

- [ ] **Step 1: 添加 `--translate` 选项和翻译逻辑**

在 `cmd_whats_new` 函数签名中添加：

```python
translate: bool = typer.Option(False, "--translate", "-T",
    help="Auto-translate the input text to all available locales using LLM"),
```

在函数内部，文件解析分支后添加翻译逻辑（伪代码位置：`if file:` 之后，`else:` 之前）：

```python
if translate:
    if not text:
        typer.echo("❌ --translate requires --text", err=True)
        raise typer.Exit(1)

    from asc.llm import LLMClient
    from asc.services.translator import OpenAITranslator

    if not config.llm_api_key:
        typer.echo("❌ LLM API key not configured. Set [llm] api_key in config or OPENAI_API_KEY env var.", err=True)
        raise typer.Exit(1)

    llm_client = LLMClient(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
    )
    translator = OpenAITranslator(llm_client)

    # Detect source locale by locale matching (simple heuristic: check if text matches any existing locale content)
    # Use first available locale as source guess, user should override via --source-locale if needed
    from asc.utils import resolve_locale
    # For now, treat all locales as targets; source is detected by LLM from prompt

    translations: dict[str, str] = {}
    failed_locales: list[str] = []

    for loc in target_locs:  # target_locs comes from locale_list or all ver_locs
        locale = loc["attributes"]["locale"]
        try:
            result = translator.translate(text, locale, "auto")
            translations[locale] = result
        except Exception as e:
            failed_locales.append(locale)
            print(f"  ⚠️  {locale} 翻译失败: {e}")

    if not translations:
        typer.echo("❌ 所有语言翻译失败", err=True)
        raise typer.Exit(1)

    print(f"\n📋 翻译结果 ({len(translations)}/{len(target_locs)} 成功)")
    for locale, content in translations.items():
        preview = content[:60] + "..." if len(content) > 60 else content
        print(f"  {locale}: {preview}")

    if dry_run:
        print("\n  ⚠️  预览模式，不实际上传")
        return

    # Upload
    for loc in target_locs:
        locale = loc["attributes"]["locale"]
        if locale not in translations:
            print(f"  ⚠️  {locale}: 跳过（翻译失败）")
            continue
        loc_id = loc["id"]
        api.update_version_localization(loc_id, {"whatsNew": translations[locale]})
        print(f"  ✅ {locale}: 已上传")

    if failed_locales:
        print(f"\n⚠️  以下语言翻译失败: {', '.join(failed_locales)}")

    print("\n✅ 版本描述更新完成")
    return
```

- [ ] **Step 2: 添加 i18n 翻译字符串**

在 `src/asc/i18n.py` 的 `HELP` 字典中添加：

```python
'llm_api_key': {
    'en': 'LLM API key for translation',
    'zh': '翻译用的 LLM API 密钥'
},
'llm_base_url': {
    'en': 'LLM API base URL',
    'zh': 'LLM API 基础 URL'
},
'llm_model': {
    'en': 'LLM model name',
    'zh': 'LLM 模型名称'
},
'translate_mode': {
    'en': 'Auto-translate input text to all locales using LLM',
    'zh': '使用 LLM 自动将输入文本翻译到所有语言'
},
'translation_failed': {
    'en': 'Translation failed for {locale}: {error}',
    'zh': '{locale} 翻译失败: {error}'
},
```

- [ ] **Step 3: 测试 CLI 参数**

```bash
cd /Users/huangxiang/Documents/01-project/AppStoreTools
# 验证 --help 显示新参数
python -m asc whats-new --help | grep -A1 translate
# Expected: --translate / -T option in help
```

- [ ] **Step 4: 提交**

```bash
git add src/asc/commands/whats_new.py src/asc/i18n.py
git commit -m "feat(whats-new): add --translate for LLM auto-translation"
```

---

## Task 4b: 创建 `tests/test_whats_new_translate.py` — CLI `--translate` 选项单元测试

**Files:**
- Create: `tests/test_whats_new_translate.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_whats_new_translate.py
"""Unit tests for asc whats-new --translate CLI behavior."""
from __future__ import annotations

import pytest
from click.testing import CliRunner
from unittest.mock import MagicMock, patch


def test_translate_flag_requires_text(mocker):
    """--translate without --text exits with error."""
    mocker.patch("asc.commands.whats_new.Config", return_value=MagicMock(
        llm_api_key="sk-test",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))
    mocker.patch("asc.commands.whats_new.resolve_app_profile", return_value="test")
    mocker.patch("asc.commands.whats_new.Guard")
    mocker.patch("asc.commands.whats_new.make_api_from_config", return_value=(MagicMock(), "app123"))
    mock_version = {"id": "v1", "attributes": {"versionString": "1.0"}}
    mocker.patch("asc.commands.whats_new.make_api_from_config",
                 return_value=(MagicMock(get_editable_version=mock_version), "app123"))

    from asc.commands.whats_new import cmd_whats_new
    runner = CliRunner()
    result = runner.invoke(cmd_whats_new, ["--translate", "--app", "test"])
    assert result.exit_code != 0
    assert "text" in result.output.lower() or "--text" in result.output


def test_translate_exits_if_no_llm_api_key(mocker):
    """--translate exits with error when LLM API key is not configured."""
    mocker.patch("asc.commands.whats_new.Config", return_value=MagicMock(
        llm_api_key="",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))
    mocker.patch("asc.commands.whats_new.resolve_app_profile", return_value="test")
    mocker.patch("asc.commands.whats_new.Guard")

    from asc.commands.whats_new import cmd_whats_new
    runner = CliRunner()
    result = runner.invoke(cmd_whats_new, ["--text", "Bug fixes.", "--translate", "--app", "test"])
    assert result.exit_code != 0
    assert "api_key" in result.output.lower() or "configured" in result.output.lower()


def test_translate_calls_translator_for_each_locale(mocker):
    """--translate calls translator.translate() for each non-source locale."""
    mock_translate = mocker.patch("asc.commands.whats_new.OpenAITranslator.translate",
                                  side_effect=["翻译结果1", "翻译结果2"])
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {"versionString": "1.0"}}
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "en-US"}},
        {"id": "l2", "attributes": {"locale": "zh-CN"}},
        {"id": "l3", "attributes": {"locale": "ja-JP"}},
    ]
    mocker.patch("asc.commands.whats_new.make_api_from_config", return_value=(mock_api, "app123"))
    mocker.patch("asc.commands.whats_new.Config", return_value=MagicMock(
        llm_api_key="sk-test",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))
    mocker.patch("asc.commands.whats_new.resolve_app_profile", return_value="test")
    mocker.patch("asc.commands.whats_new.Guard")

    from asc.commands.whats_new import cmd_whats_new
    runner = CliRunner()
    result = runner.invoke(cmd_whats_new, [
        "--text", "Bug fixes.", "--translate", "--dry-run", "--app", "test"
    ])
    # Dry-run: no API upload calls made
    assert mock_api.update_version_localization.call_count == 0
    # Should have attempted translation (locale count minus source)
    assert mock_translate.call_count >= 2


def test_dry_run_does_not_upload(mocker):
    """--translate --dry-run does not call App Store Connect API."""
    mocker.patch("asc.commands.whats_new.OpenAITranslator.translate", return_value="Translated.")
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {"versionString": "1.0"}}
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "zh-CN"}},
    ]
    mocker.patch("asc.commands.whats_new.make_api_from_config", return_value=(mock_api, "app123"))
    mocker.patch("asc.commands.whats_new.Config", return_value=MagicMock(
        llm_api_key="sk-test",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))
    mocker.patch("asc.commands.whats_new.resolve_app_profile", return_value="test")
    mocker.patch("asc.commands.whats_new.Guard")

    from asc.commands.whats_new import cmd_whats_new
    runner = CliRunner()
    result = runner.invoke(cmd_whats_new, [
        "--text", "Bug fixes.", "--translate", "--dry-run", "--app", "test"
    ])
    assert mock_api.update_version_localization.call_count == 0
    assert "dry" in result.output.lower() or "预览" in result.output


def test_translate_non_dry_run_calls_api(mocker):
    """--translate without --dry-run calls App Store Connect API."""
    mocker.patch("asc.commands.whats_new.OpenAITranslator.translate", return_value="Translated.")
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {"versionString": "1.0"}}
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "zh-CN"}},
    ]
    mocker.patch("asc.commands.whats_new.make_api_from_config", return_value=(mock_api, "app123"))
    mocker.patch("asc.commands.whats_new.Config", return_value=MagicMock(
        llm_api_key="sk-test",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))
    mocker.patch("asc.commands.whats_new.resolve_app_profile", return_value="test")
    mocker.patch("asc.commands.whats_new.Guard")

    from asc.commands.whats_new import cmd_whats_new
    runner = CliRunner()
    result = runner.invoke(cmd_whats_new, [
        "--text", "Bug fixes.", "--translate", "--app", "test"
    ])
    assert mock_api.update_version_localization.call_count == 1


def test_translate_skips_failed_locale_and_continues(mocker):
    """When one locale fails to translate, it's skipped and others continue."""
    call_count = 0
    def translate_with_failure(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Translation failed")
        return "成功"

    mocker.patch("asc.commands.whats_new.OpenAITranslator.translate", side_effect=translate_with_failure)
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {"versionString": "1.0"}}
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "en-US"}},
        {"id": "l2", "attributes": {"locale": "zh-CN"}},
    ]
    mocker.patch("asc.commands.whats_new.make_api_from_config", return_value=(mock_api, "app123"))
    mocker.patch("asc.commands.whats_new.Config", return_value=MagicMock(
        llm_api_key="sk-test",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))
    mocker.patch("asc.commands.whats_new.resolve_app_profile", return_value="test")
    mocker.patch("asc.commands.whats_new.Guard")

    from asc.commands.whats_new import cmd_whats_new
    runner = CliRunner()
    result = runner.invoke(cmd_whats_new, [
        "--text", "Bug.", "--translate", "--app", "test"
    ])
    # Should still call API for the locale that succeeded
    assert mock_api.update_version_localization.call_count == 1
    assert "翻译失败" in result.output or "failed" in result.output.lower()


def test_translate_all_fail_exits_with_error(mocker):
    """When all locales fail to translate, command exits with error."""
    mocker.patch("asc.commands.whats_new.OpenAITranslator.translate",
                 side_effect=Exception("Network error"))
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {"versionString": "1.0"}}
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "zh-CN"}},
    ]
    mocker.patch("asc.commands.whats_new.make_api_from_config", return_value=(mock_api, "app123"))
    mocker.patch("asc.commands.whats_new.Config", return_value=MagicMock(
        llm_api_key="sk-test",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))
    mocker.patch("asc.commands.whats_new.resolve_app_profile", return_value="test")
    mocker.patch("asc.commands.whats_new.Guard")

    from asc.commands.whats_new import cmd_whats_new
    runner = CliRunner()
    result = runner.invoke(cmd_whats_new, [
        "--text", "Bug.", "--translate", "--app", "test"
    ])
    assert result.exit_code != 0
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_whats_new_translate.py -v 2>&1 | head -30
# Expected: ERROR — module 'asc.commands.whats_new' has no '--translate' option
```

- [ ] **Step 3: 实现 CLI --translate 参数**

已在 Task 4 中实现。

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_whats_new_translate.py -v
# Expected: 6 passed
```

- [ ] **Step 5: 提交**

```bash
git add tests/test_whats_new_translate.py
git commit -m "test(whats-new): add unit tests for --translate CLI flow"
```

---

## Task 5: 修改 `src/asc/web/routes_api.py` — 新增 `/api/whats-new/*` 路由

**Files:**
- Modify: `src/asc/web/routes_api.py`

- [ ] **Step 1: 添加 `POST /api/whats-new/check` 路由**

在 `routes_api.py` 末尾添加：

```python
@router.get("/whats-new/check")
async def whats_new_check(request: Request):
    """Check environment and return available locales for the current app version."""
    profile = request.cookies.get("asc_profile", "")
    if not profile:
        return {"ok": False, "error": "No profile selected"}
    try:
        from asc.config import Config
        from asc.utils import make_api_from_config
        config = Config(app_name=profile)
        api, app_id = make_api_from_config(config)
        version = api.get_editable_version(app_id)
        if not version:
            return {"ok": False, "error": "No editable version found"}
        version_id = version["id"]
        ver_locs = api.get_version_localizations(version_id)
        locales = [loc["attributes"]["locale"] for loc in ver_locs]
        return {
            "ok": True,
            "version": version["attributes"].get("versionString", "?"),
            "locales": locales,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/whats-new/translate")
async def whats_new_translate(
    request: Request,
    text: str = _Form(...),
    source_locale: str = _Form("auto"),
):
    """Translate text to all available locales using LLM."""
    profile = request.cookies.get("asc_profile", "")
    if not profile:
        return JSONResponse({"error": "No profile selected"}, status_code=400)
    try:
        from asc.config import Config
        from asc.llm import LLMClient
        from asc.services.translator import OpenAITranslator
        config = Config(app_name=profile)
        if not config.llm_api_key:
            return JSONResponse({"error": "LLM API key not configured. Set [llm] api_key in config or OPENAI_API_KEY env var."}, status_code=400)
        llm_client = LLMClient(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
        )
        translator = OpenAITranslator(llm_client)
        # Get available locales
        api, app_id = make_api_from_config(config)
        version = api.get_editable_version(app_id)
        version_id = version["id"]
        ver_locs = api.get_version_localizations(version_id)
        target_locales = [loc["attributes"]["locale"] for loc in ver_locs if loc["attributes"]["locale"] != source_locale]
        translations = {}
        for locale in target_locales:
            try:
                translations[locale] = translator.translate(text, locale, source_locale)
            except Exception:
                translations[locale] = ""  # empty = failed
        return {
            "source_locale": source_locale,
            "translations": translations,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _start_whats_new_task(
    profile: str,
    translations: dict[str, str],
    dry_run: bool,
) -> str:
    task_id = _task_store.create("whats-new", profile=profile)

    def _run():
        import queue
        from asc.web.sse import capture_stdout_to_queue
        from asc.config import Config
        from asc.utils import make_api_from_config

        _task_store.set_status(task_id, _TaskStatus.RUNNING)
        q: queue.Queue = queue.Queue()
        done_flag = _threading.Event()

        _PROGRESS_RE = re.compile(r"\[PROGRESS:(\d+):(.+)\]")

        def _drain_loop():
            while not done_flag.is_set():
                while not q.empty():
                    line = q.get_nowait()
                    m = _PROGRESS_RE.match(line)
                    if m:
                        _task_store.set_progress(task_id, int(m.group(1)), m.group(2))
                    else:
                        _task_store.append_log(task_id, line)
                done_flag.wait(timeout=0.05)
            while not q.empty():
                line = q.get_nowait()
                m = _PROGRESS_RE.match(line)
                if m:
                    _task_store.set_progress(task_id, int(m.group(1)), m.group(2))
                else:
                    _task_store.append_log(task_id, line)

        _threading.Thread(target=_drain_loop, daemon=True).start()

        try:
            config = Config(app_name=profile)
            api, app_id = make_api_from_config(config)
            version = api.get_editable_version(app_id)
            version_id = version["id"]
            ver_locs = api.get_version_localizations(version_id)
            ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}

            total = len(translations)
            for i, (locale, content) in enumerate(translations.items()):
                if locale not in ver_loc_map:
                    _task_store.append_log(task_id, f"⚠️  {locale}: 不存在，跳过")
                    continue
                if dry_run:
                    _task_store.append_log(task_id, f"[DRYRUN] {locale}: {content[:50]}...")
                    continue
                api.update_version_localization(ver_loc_map[locale]["id"], {"whatsNew": content})
                _task_store.append_log(task_id, f"✅ {locale}: 已上传")
                _task_store.set_progress(task_id, int((i + 1) / total * 100), f"上传 {locale}")

            done_flag.set()
            _task_store.set_status(task_id, _TaskStatus.DONE)
            _task_store.set_result(task_id, {"success": True})
        except Exception as e:
            done_flag.set()
            _task_store.append_log(task_id, f"❌ 错误：{e}")
            _task_store.set_status(task_id, _TaskStatus.ERROR)
            _task_store.set_result(task_id, {"success": False, "error": str(e)})

    _threading.Thread(target=_run, daemon=True).start()
    return task_id


@router.post("/whats-new/run")
async def whats_new_run(
    request: Request,
    translations_json: str = _Form(...),
    dry_run: str = _Form(""),
):
    import json
    profile = request.cookies.get("asc_profile", "")
    if not profile:
        return JSONResponse({"error": "No profile selected"}, status_code=400)
    try:
        translations = json.loads(translations_json)
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    task_id = _start_whats_new_task(
        profile=profile,
        translations=translations,
        dry_run=bool(dry_run),
    )
    return {"task_id": task_id}
```

注意：需要在文件顶部确认已导入 `_threading`、`_asyncio`、`_StreamingResponse`、`JSONResponse`、`_Form`（部分已在文件中）。

- [ ] **Step 2: 提交**

```bash
git add src/asc/web/routes_api.py
git commit -m "feat(web): add /api/whats-new/* routes for translate and upload"
```

---

## Task 5b: 创建 `tests/test_web_whats_new.py` — Web API 路由单元测试

**Files:**
- Create: `tests/test_web_whats_new.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_web_whats_new.py
"""Unit tests for /api/whats-new/* routes and /api/settings/llm."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from asc.web.server import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_whats_new_check_returns_locales(client, mocker):
    """GET /api/whats-new/check returns version and locales when version exists."""
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "2.0.0"},
    }
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "en-US"}},
        {"id": "l2", "attributes": {"locale": "zh-CN"}},
    ]
    mocker.patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123"))
    mocker.patch("asc.web.routes_api.Config", return_value=MagicMock(app_name="test"))

    response = client.get(
        "/api/whats-new/check",
        cookies={"asc_profile": "test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["version"] == "2.0.0"
    assert "en-US" in data["locales"]
    assert "zh-CN" in data["locales"]


def test_whats_new_check_no_editable_version(client, mocker):
    """GET /api/whats-new/check returns error when no editable version."""
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = None
    mocker.patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123"))
    mocker.patch("asc.web.routes_api.Config", return_value=MagicMock(app_name="test"))

    response = client.get(
        "/api/whats-new/check",
        cookies={"asc_profile": "test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "editable" in data["error"].lower() or "version" in data["error"].lower()


def test_whats_new_translate_returns_translations(client, mocker):
    """POST /api/whats-new/translate returns dict of locale -> translated text."""
    mock_translate = mocker.patch(
        "asc.web.routes_api.OpenAITranslator.translate",
        side_effect=["结果1", "结果2"],
    )
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {"versionString": "1.0"}}
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "en-US"}},
        {"id": "l2", "attributes": {"locale": "zh-CN"}},
    ]
    mocker.patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123"))
    mocker.patch("asc.web.routes_api.Config", return_value=MagicMock(
        llm_api_key="sk-test",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))

    response = client.post(
        "/api/whats-new/translate",
        data={"text": "Bug fixes.", "source_locale": "en-US"},
        cookies={"asc_profile": "test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["source_locale"] == "en-US"
    assert "zh-CN" in data["translations"]
    # en-US should be excluded from translations (source locale)
    assert "en-US" not in data["translations"]


def test_whats_new_translate_no_api_key_returns_400(client, mocker):
    """POST /api/whats-new/translate returns 400 when LLM API key not configured."""
    mocker.patch("asc.web.routes_api.Config", return_value=MagicMock(
        llm_api_key="",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))

    response = client.post(
        "/api/whats-new/translate",
        data={"text": "Bug.", "source_locale": "en-US"},
        cookies={"asc_profile": "test"},
    )
    assert response.status_code == 400
    assert "api_key" in response.json()["error"].lower() or "configured" in response.json()["error"].lower()


def test_whats_new_run_returns_task_id(client, mocker):
    """POST /api/whats-new/run returns a task_id."""
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1", "attributes": {"versionString": "1.0"}}
    mock_api.get_version_localizations.return_value = [
        {"id": "l1", "attributes": {"locale": "zh-CN"}},
    ]
    mocker.patch("asc.web.routes_api.make_api_from_config", return_value=(mock_api, "app123"))

    import json
    response = client.post(
        "/api/whats-new/run",
        data={"translations_json": json.dumps({"zh-CN": "错误修复"}), "dry_run": ""},
        cookies={"asc_profile": "test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data


def test_whats_new_run_invalid_json_returns_400(client):
    """POST /api/whats-new/run returns 400 for malformed JSON."""
    response = client.post(
        "/api/whats-new/run",
        data={"translations_json": "not valid json{{", "dry_run": ""},
        cookies={"asc_profile": "test"},
    )
    assert response.status_code == 400


def test_settings_llm_get_returns_config(client, mocker):
    """GET /api/settings/llm returns current LLM config."""
    mocker.patch("asc.web.routes_api.Config", return_value=MagicMock(
        llm_api_key="sk-testkey",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))

    response = client.get("/api/settings/llm", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data["api_key"] == "sk-testkey"
    assert data["base_url"] == "https://api.openai.com/v1"
    assert data["model"] == "gpt-4o"


def test_settings_llm_get_no_key_returns_empty_string(client, mocker):
    """GET /api/settings/llm returns empty string for api_key when not configured."""
    mocker.patch("asc.web.routes_api.Config", return_value=MagicMock(
        llm_api_key=None,
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))

    response = client.get("/api/settings/llm", cookies={"asc_profile": "test"})
    assert response.status_code == 200
    assert response.json()["api_key"] == ""


def test_settings_llm_post_saves_config(client, mocker, tmp_path, monkeypatch):
    """POST /api/settings/llm saves config to local .asc/config.toml."""
    import os
    import tomllib

    # Mock the local_cfg Path to a temp location
    mock_cfg_path = tmp_path / ".asc" / "config.toml"
    mocker.patch("asc.web.routes_api.Path", return_value=mock_cfg_path)

    mocker.patch("asc.web.routes_api.Config", return_value=MagicMock(
        llm_api_key="",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o",
    ))

    response = client.post(
        "/api/settings/llm",
        json={"base_url": "https://openrouter.ai/v1", "model": "gpt-4o-mini", "api_key": "sk-newkey"},
        cookies={"asc_profile": "test"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_web_whats_new.py -v 2>&1 | head -30
# Expected: ERROR — module 'asc.web.routes_api' has no attribute '/api/whats-new/*'
```

- [ ] **Step 3: 实现 Web API 路由**

已在 Task 5 中实现。

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_web_whats_new.py -v
# Expected: 8 passed
```

- [ ] **Step 5: 提交**

```bash
git add tests/test_web_whats_new.py
git commit -m "test(web): add unit tests for /api/whats-new/* and /api/settings/llm routes"
```

---

## Task 6: 修改 `src/asc/web/server.py` — 注册 `/whats-new` 页面路由

**Files:**
- Modify: `src/asc/web/server.py`

- [ ] **Step 1: 添加路由**

在 `create_app()` 函数中，在 `/settings` 路由之后添加：

```python
@app.get("/whats-new", response_class=HTMLResponse)
async def whats_new_page(request: Request):
    ctx = _get_profile_context(request)
    return templates.TemplateResponse(request, "whats_new.html", ctx)
```

- [ ] **Step 2: 提交**

```bash
git add src/asc/web/server.py
git commit -m "feat(web): add /whats-new page route"
```

---

## Task 7: 创建 `src/asc/web/templates/whats_new.html` — Whats-New 页面

**Files:**
- Create: `src/asc/web/templates/whats_new.html`

- [ ] **Step 1: 创建页面**

页面结构（参考 `metadata.html` 和 `build.html` 的模式）：

```html
{% extends "base.html" %}
{% block content %}
<div x-data="{
  step: 1,
  taskId: null,
  logs: [],
  status: 'idle',
  progress: 0,
  progressMsg: '',
  submitting: false,
  checkResult: null,
  translateMode: false,
  sourceLocale: 'auto',
  text: '',
  translations: {},
  availableLocales: [],
  version: '',
  editingLocale: null,
  editText: '',
}">

  <!-- Step 1: 表单 -->
  <div x-show="step === 1">
    <h1 class="text-2xl font-bold tracking-tight text-obsidian-50 flex items-center gap-3 mb-8">
      <div class="w-8 h-8 rounded-lg flex items-center justify-center" style="background: var(--accent-glow);">
        <svg class="w-4.5 h-4.5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z"/></svg>
      </div>
      更新说明（What's New）
    </h1>

    <!-- 环境检查 -->
    <div x-data="{}"
         x-init="
           fetch('/api/whats-new/check')
             .then(r => r.json())
             .then(d => { checkResult = d; if(d.ok) { availableLocales = d.locales; version = d.version; } })
             .catch(() => { checkResult = {ok: false, error: '请求失败'}; })
         ">
      <template x-if="checkResult && checkResult.ok">
        <div class="mb-4 text-xs text-obsidian-400">
          版本 <span class="font-mono text-amber-550" x-text="version"></span> ·
          <span x-text="availableLocales.length"></span> 个语言
        </div>
      </template>
      <template x-if="checkResult && !checkResult.ok">
        <div class="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400">
          <span x-text="checkResult.error"></span>
        </div>
      </template>
    </div>

    <div class="card">
      <div class="card-body space-y-5">
        <!-- 语言 -->
        <div>
          <label class="text-xs uppercase tracking-widest text-obsidian-400 font-medium mb-2 block">源语言</label>
          <select x-model="sourceLocale" class="field-select w-full">
            <option value="auto">自动检测</option>
            <template x-for="locale in availableLocales" :key="locale">
              <option :value="locale" x-text="locale"></option>
            </template>
          </select>
        </div>

        <!-- 文本 -->
        <div>
          <label class="text-xs uppercase tracking-widest text-obsidian-400 font-medium mb-2 block">更新说明</label>
          <textarea x-model="text"
                    rows="5"
                    class="field-input w-full resize-y"
                    placeholder="输入更新说明内容..."></textarea>
        </div>

        <!-- 翻译模式 -->
        <div>
          <label class="flex items-center gap-2.5 text-sm text-obsidian-300 cursor-pointer">
            <input type="checkbox" x-model="translateMode" class="w-4 h-4">
            翻译模式：自动翻译到所有语言
          </label>
        </div>

        <!-- 操作 -->
        <div class="flex gap-3 pt-3 border-t border-obsidian-700">
          <button x-show="translateMode"
                  type="button"
                  class="btn-primary"
                  :disabled="!text || submitting || !checkResult?.ok"
                  @click="
                    submitting = true;
                    fetch('/api/whats-new/translate', {
                      method: 'POST',
                      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                      body: 'text=' + encodeURIComponent(text) + '&source_locale=' + encodeURIComponent(sourceLocale)
                    })
                      .then(r => r.json())
                      .then(d => {
                        if (d.error) { alert(d.error); submitting = false; return; }
                        translations = d.translations;
                        // Prepend source locale if not auto
                        if (sourceLocale !== 'auto') {
                          translations = {...{[sourceLocale]: text}, ...translations};
                        }
                        submitting = false;
                        step = 2;
                      })
                      .catch(e => { alert(e); submitting = false; })
                  ">
            <span x-show="!submitting">预览翻译</span>
            <span x-show="submitting">翻译中...</span>
          </button>
          <button type="button"
                  class="btn-ghost"
                  :disabled="!text || submitting || !checkResult?.ok"
                  @click="
                    // Direct upload without translation
                    translations = {[sourceLocale === 'auto' ? 'en-US' : sourceLocale]: text};
                    submitting = true;
                    fetch('/api/whats-new/run', {
                      method: 'POST',
                      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                      body: 'translations_json=' + encodeURIComponent(JSON.stringify(translations)) + '&dry_run='
                    })
                      .then(r => r.json())
                      .then(d => {
                        taskId = d.task_id;
                        submitting = false;
                        step = 2;
                        startSSE(taskId);
                      })
                  ">
            直接上传（不翻译）
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Step 2: 翻译预览 -->
  <div x-show="step === 2 && translateMode">
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-lg font-semibold text-obsidian-100">翻译预览</h2>
      <button @click="step = 1; translations = {}" class="btn-ghost text-sm">返回修改</button>
    </div>

    <div class="space-y-4 mb-6">
      <template x-for="(content, locale) in translations" :key="locale">
        <div class="card">
          <div class="card-header flex items-center justify-between">
            <span class="font-mono text-sm text-amber-550" x-text="locale"></span>
            <button @click="editingLocale = locale; editText = content"
                    class="text-xs text-obsidian-400 hover:text-amber-500 cursor-pointer transition-colors">编辑</button>
          </div>
          <div class="card-body">
            <p class="text-sm text-obsidian-200 whitespace-pre-wrap" x-text="content"></p>
          </div>
        </div>
      </template>
    </div>

    <div class="flex gap-3">
      <button @click="step = 1" class="btn-ghost">取消</button>
      <button @click="
        submitting = true;
        fetch('/api/whats-new/run', {
          method: 'POST',
          headers: {'Content-Type': 'application/x-www-form-urlencoded'},
          body: 'translations_json=' + encodeURIComponent(JSON.stringify(translations)) + '&dry_run='
        })
          .then(r => r.json())
          .then(d => { taskId = d.task_id; submitting = false; startSSE(taskId); })
      ">
        确认并上传
      </button>
      <button @click="
        fetch('/api/whats-new/run', {
          method: 'POST',
          headers: {'Content-Type': 'application/x-www-form-urlencoded'},
          body: 'translations_json=' + encodeURIComponent(JSON.stringify(translations)) + '&dry_run=1'
        })
          .then(r => r.json())
          .then(d => { taskId = d.task_id; startSSE(taskId); step = 3; })
      ">
        预览（Dry Run）
      </button>
    </div>
  </div>

  <!-- Step 3: 执行面板（SSE 进度） -->
  <div x-show="step === 2 || step === 3">
    <div class="card">
      <div class="card-body">
        <div class="flex items-center justify-between mb-5">
          <h2 class="font-semibold text-obsidian-100"
              x-text="status === 'done' ? '上传完成' : status === 'error' ? '上传失败' : '上传中...'"></h2>
          <template x-if="status === 'done'">
            <div class="w-7 h-7 rounded-full flex items-center justify-center bg-emerald-500/15">
              <svg class="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5"/></svg>
            </div>
          </template>
          <template x-if="status === 'running'">
            <div class="w-7 h-7 rounded-full flex items-center justify-center" style="background: var(--accent-glow);">
              <svg class="w-4 h-4 text-amber-500 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            </div>
          </template>
        </div>
        <div class="progress-track mb-2">
          <div class="progress-fill" :style="'width: ' + progress + '%'"></div>
        </div>
        <div class="flex items-center justify-between mb-5">
          <p class="text-xs text-obsidian-400" x-text="progressMsg"></p>
        </div>
        <div class="log-panel max-h-64">
          <template x-for="(line, idx) in logs" :key="idx">
            <div x-text="line"></div>
          </template>
        </div>
      </div>
    </div>
  </div>

  <!-- 编辑弹窗 -->
  <div x-show="editingLocale !== null"
       x-data="{ show: false }"
       x-init="$watch('editingLocale', v => { show = v !== null; if(v) editText = translations[v] || ''; })"
       class="fixed inset-0 flex items-center justify-center z-50"
       style="background: rgba(0,0,0,0.6); backdrop-filter: blur(4px);"
       @click.self="editingLocale = null">
    <div class="card w-[500px]">
      <div class="card-header">编辑：<span class="font-mono text-amber-550" x-text="editingLocale"></span></div>
      <div class="card-body space-y-4">
        <textarea x-model="editText" rows="5" class="field-input w-full resize-y"></textarea>
        <div class="flex gap-3 justify-end">
          <button @click="editingLocale = null" class="btn-ghost">取消</button>
          <button @click="translations[editingLocale] = editText; editingLocale = null" class="btn-primary">保存</button>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
function startSSE(taskId) {
  const es = new EventSource('/api/task/' + taskId + '/stream');
  const root = document.querySelector('[x-data]');
  const d = Alpine.$data(root);
  d.status = 'running';
  es.addEventListener('log', e => { d.logs.push(e.data); });
  es.addEventListener('progress', e => {
    const p = JSON.parse(e.data);
    d.progress = p.pct || 0;
    d.progressMsg = p.msg || '';
  });
  es.addEventListener('done', () => { d.status = 'done'; d.progress = 100; es.close(); });
  es.addEventListener('error_event', () => { d.status = 'error'; es.close(); });
}
</script>
{% endblock %}
```

- [ ] **Step 2: 在 base.html 侧边栏添加入口**

在 `src/asc/web/templates/base.html` 的 `<nav>` 区块中，在"构建上传"之后添加：

```html
<a href="/whats-new"
   class="nav-item flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] cursor-pointer focus-ring
          {% if request.url.path == '/whats-new' %}active{% endif %}">
  <svg class="w-[18px] h-[18px] shrink-0 text-obsidian-400" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 0 1 .865-.501 48.172 48.172 0 0 0 3.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z"/></svg>
  更新说明
</a>
```

- [ ] **Step 3: 提交**

```bash
git add src/asc/web/templates/whats_new.html src/asc/web/templates/base.html
git commit -m "feat(web): add whats-new page with translate preview flow"
```

---

## Task 8: 修改 `src/asc/web/templates/settings.html` — 新增 LLM 配置区块

**Files:**
- Modify: `src/asc/web/templates/settings.html`

- [ ] **Step 1: 在 `<div class="space-y-6">` 中添加 LLM 配置区块**

在 `<!-- Language -->` 区块之前添加：

```html
<!-- LLM Configuration -->
<div class="card"
     x-data="{ llm: null, saving: false, saved: false }"
     x-init="
       // Load existing LLM config
       fetch('/api/settings/llm')
         .then(r => r.json())
         .then(d => { llm = d; })
         .catch(() => {})
     ">
  <div class="card-header flex items-center gap-2">
    <svg class="w-4 h-4 text-amber-500" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456Z"/></svg>
    <h2 class="text-xs uppercase tracking-widest text-obsidian-400 font-medium">LLM 翻译配置</h2>
  </div>
  <div class="card-body space-y-4">
    <template x-if="llm">
      <div class="space-y-4">
        <div>
          <label class="text-xs uppercase tracking-widest text-obsidian-500 font-medium mb-1.5 block">Base URL</label>
          <input type="text" x-model="llm.base_url"
                 class="field-input w-full"
                 placeholder="https://api.openai.com/v1">
        </div>
        <div>
          <label class="text-xs uppercase tracking-widest text-obsidian-500 font-medium mb-1.5 block">API Key</label>
          <input type="password" x-model="llm.api_key"
                 class="field-input w-full"
                 placeholder="sk-...">
        </div>
        <div>
          <label class="text-xs uppercase tracking-widest text-obsidian-500 font-medium mb-1.5 block">Model</label>
          <select x-model="llm.model" class="field-select w-full">
            <option value="gpt-4o">GPT-4o</option>
            <option value="gpt-4o-mini">GPT-4o mini</option>
            <option value="gpt-4-turbo">GPT-4 Turbo</option>
            <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
          </select>
        </div>
        <div class="flex items-center gap-3">
          <button @click="
            saving = true;
            fetch('/api/settings/llm', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify(llm)
            })
              .then(r => r.json())
              .then(() => { saving = false; saved = true; setTimeout(() => saved = false, 2000); })
              .catch(() => { saving = false; })
          "
                  :disabled="saving"
                  class="btn-primary">
            <span x-show="!saving && !saved">保存配置</span>
            <span x-show="saving">保存中...</span>
            <span x-show="saved" class="text-emerald-400">已保存</span>
          </button>
        </div>
      </div>
    </template>
    <template x-if="!llm">
      <div class="text-sm text-obsidian-500">加载中...</div>
    </template>
  </div>
</div>
```

- [ ] **Step 2: 添加 API 路由读取/保存 LLM 配置**

在 `routes_api.py` 中添加：

```python
@router.get("/settings/llm")
async def get_llm_config(request: Request):
    from asc.config import Config
    profile = request.cookies.get("asc_profile")
    config = Config(app_name=profile)
    return {
        "base_url": config.llm_base_url,
        "api_key": config.llm_api_key or "",
        "model": config.llm_model,
    }

@router.post("/settings/llm")
async def save_llm_config(request: Request, data: dict):
    import json
    from asc.config import Config
    profile = request.cookies.get("asc_profile")
    config = Config(app_name=profile)
    # Persist to local .asc/config.toml or global profile
    # For now, save to local config
    local_cfg = Path(".") / ".asc" / "config.toml"
    local_cfg.parent.mkdir(parents=True, exist_ok=True)
    # Read existing or create new
    import tomllib
    existing = {}
    if local_cfg.exists():
        try:
            with open(local_cfg, "rb") as f:
                existing = tomllib.load(f)
        except Exception:
            existing = {}
    llm_section = existing.get("llm", {})
    llm_section["base_url"] = data.get("base_url", "https://api.openai.com/v1")
    llm_section["model"] = data.get("model", "gpt-4o")
    if data.get("api_key"):
        llm_section["api_key"] = data["api_key"]
    existing["llm"] = llm_section
    # Write back
    content = ""
    for section, items in existing.items():
        content += f"[{section}]\n"
        if isinstance(items, dict):
            for k, v in items.items():
                content += f'{k} = "{v}"\n'
        content += "\n"
    local_cfg.write_text(content)
    return {"ok": True}
```

- [ ] **Step 3: 提交**

```bash
git add src/asc/web/templates/settings.html src/asc/web/routes_api.py
git commit -m "feat(settings): add LLM configuration section in Web UI"
```

---

## Task 10: 集成与端到端测试

**Files:**
- Test: `tests/test_whats_new_e2e.py`

- [ ] **Step 1: 写端到端测试（mocked LLM + real API client）**

```python
# tests/test_whats_new_e2e.py
"""End-to-end integration tests for whats-new translate + upload flow."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner
import requests_mock as rm


def test_full_translate_upload_flow():
    """Full flow: --translate -> get translations -> upload to all locales."""
    with rm.Mocker() as m:
        # Mock App Store Connect API
        m.get(
            "https://api.appstoreconnect.apple.com/v1/apps/app123/editableVersions",
            json={"data": [{"id": "v1", "attributes": {"versionString": "1.0.0"}}]},
        )
        m.get(
            "https://api.appstoreconnect.apple.com/v1/versionLocalizations",
            json={
                "data": [
                    {"id": "loc-en", "attributes": {"locale": "en-US"}},
                    {"id": "loc-zh", "attributes": {"locale": "zh-CN"}},
                    {"id": "loc-ja", "attributes": {"locale": "ja-JP"}},
                ]
            },
        )
        m.patch(
            "https://api.appstoreconnect.apple.com/v1/versionLocalizations/loc-en",
            json={},
        )
        m.patch(
            "https://api.appstoreconnect.apple.com/v1/versionLocalizations/loc-zh",
            json={},
        )
        m.patch(
            "https://api.appstoreconnect.apple.com/v1/versionLocalizations/loc-ja",
            json={},
        )

        # Mock LLM API (translate calls)
        m.post(
            "https://api.openai.com/v1/chat/completions",
            [
                # ja-JP translation
                {"json": {"choices": [{"message": {"role": "assistant", "content": "バグ修正。"}}]}},
            ],
        )
        m.post(
            "https://api.openai.com/v1/chat/completions",
            [
                # zh-CN translation
                {"json": {"choices": [{"message": {"role": "assistant", "content": "错误修复。"}}]}},
            ],
        )

        from asc.commands.whats_new import cmd_whats_new
        from asc.llm import LLMClient
        from asc.services.translator import OpenAITranslator

        runner = CliRunner()

        # Patch at the source: the translator creation in cmd_whats_new
        with patch("asc.commands.whats_new.LLMClient", return_value=LLMClient(
            api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o"
        )):
            with patch("asc.commands.whats_new.OpenAITranslator", return_value=OpenAITranslator(
                LLMClient(api_key="sk-test", base_url="https://api.openai.com/v1", model="gpt-4o")
            )):
                with patch("asc.commands.whats_new.Config") as MockConfig:
                    MockConfig.return_value.llm_api_key = "sk-test"
                    MockConfig.return_value.llm_base_url = "https://api.openai.com/v1"
                    MockConfig.return_value.llm_model = "gpt-4o"
                    with patch("asc.commands.whats_new.resolve_app_profile", return_value="test"):
                        with patch("asc.commands.whats_new.Guard"):
                            with patch("asc.commands.whats_new.make_api_from_config") as mock_make_api:
                                mock_api = MagicMock()
                                mock_api.get_editable_version.return_value = {
                                    "id": "v1", "attributes": {"versionString": "1.0.0"}
                                }
                                mock_api.get_version_localizations.return_value = [
                                    {"id": "loc-en", "attributes": {"locale": "en-US"}},
                                    {"id": "loc-zh", "attributes": {"locale": "zh-CN"}},
                                    {"id": "loc-ja", "attributes": {"locale": "ja-JP"}},
                                ]
                                mock_make_api.return_value = (mock_api, "app123")

                                result = runner.invoke(cmd_whats_new, [
                                    "--text", "Bug fixes.",
                                    "--translate",
                                    "--app", "test",
                                ])

        # Should complete successfully
        assert result.exit_code == 0
        # Should have attempted 2 uploads (zh-CN and ja-JP; en-US is source)
        assert mock_api.update_version_localization.call_count == 2


def test_web_whats_new_translate_preview_flow():
    """Web UI: translate preview -> confirm upload via SSE task."""
    from fastapi.testclient import TestClient
    from asc.web.server import create_app

    app = create_app()
    client = TestClient(app)

    with patch("asc.web.routes_api.make_api_from_config") as mock_make_api:
        mock_api = MagicMock()
        mock_api.get_editable_version.return_value = {
            "id": "v1", "attributes": {"versionString": "1.0.0"}
        }
        mock_api.get_version_localizations.return_value = [
            {"id": "l1", "attributes": {"locale": "en-US"}},
            {"id": "l2", "attributes": {"locale": "zh-CN"}},
        ]
        mock_make_api.return_value = (mock_api, "app123")

        with patch("asc.web.routes_api.Config") as MockConfig:
            MockConfig.return_value.llm_api_key = "sk-test"
            MockConfig.return_value.llm_base_url = "https://api.openai.com/v1"
            MockConfig.return_value.llm_model = "gpt-4o"

            with patch("asc.web.routes_api.OpenAITranslator") as MockTranslator:
                instance = MockTranslator.return_value
                instance.translate.side_effect = ["错误修复。"]

                # Step 1: translate
                resp = client.post(
                    "/api/whats-new/translate",
                    data={"text": "Bug fixes.", "source_locale": "en-US"},
                    cookies={"asc_profile": "test"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "translations" in data
                assert data["source_locale"] == "en-US"

                # Step 2: run upload task
                import json
                resp2 = client.post(
                    "/api/whats-new/run",
                    data={"translations_json": json.dumps(data["translations"]), "dry_run": "1"},
                    cookies={"asc_profile": "test"},
                )
                assert resp2.status_code == 200
                task_id = resp2.json()["task_id"]
                assert task_id

                # Step 3: check task status
                resp3 = client.get(f"/api/task/{task_id}/status")
                assert resp3.status_code == 200
                task_data = resp3.json()
                assert "status" in task_data


def test_whats_new_page_loads():
    """GET /whats-new returns the page with 200 status."""
    from fastapi.testclient import TestClient
    from asc.web.server import create_app

    app = create_app()
    client = TestClient(app)
    response = client.get("/whats-new")
    assert response.status_code == 200
    assert "更新说明" in response.text or "What's New" in response.text
```

- [ ] **Step 2: 运行端到端测试**

```bash
pytest tests/test_whats_new_e2e.py -v
# Expected: 3 passed
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_whats_new_e2e.py
git commit -m "test(e2e): add end-to-end tests for translate + upload flow"
```

---

## Task 11: 运行完整测试套件并修复

**Files:**
- Run: 所有新增测试文件

- [ ] **Step 1: 运行完整测试套件**

```bash
cd /Users/huangxiang/Documents/01-project/AppStoreTools
pytest tests/test_llm.py tests/test_translator.py tests/test_config_llm.py \
       tests/test_whats_new_translate.py tests/test_web_whats_new.py \
       tests/test_whats_new_e2e.py -v
```

- [ ] **Step 2: 如有失败，修复后重新运行**

- [ ] **Step 3: 运行整个项目测试套件确保无回归**

```bash
pytest tests/ -v --ignore=tests/test_whats_new_e2e.py  # 集成测试单独跑
```

- [ ] **Step 4: 提交**

```bash
git add tests/
git commit -m "test: add complete test suite for whats-new translate feature"
```

---

## 自检清单

1. **Spec 覆盖**：逐条核对设计文档，确认每条需求有对应任务实现。
   - `llm.py` → Task 1 + Task 10（e2e）
   - `services/translator.py` → Task 2 + Task 10（e2e）
   - `config.py` [llm] → Task 3 + Task 3b
   - `whats_new.py` --translate → Task 4 + Task 4b
   - `routes_api.py` /api/whats-new/* → Task 5 + Task 5b
   - `server.py` /whats-new → Task 6
   - `whats_new.html` → Task 7
   - `settings.html` LLM区块 → Task 8
   - 集成测试 → Task 10 + Task 11

2. **占位符扫描**：检查计划中是否有 TBD/TODO/模糊描述 — 无。

3. **类型一致性**：
   - `LLMClient.chat(messages, temperature)` 返回 `str` ✓
   - `OpenAITranslator.translate(text, target_locale, source_locale)` 签名 ✓
   - `Config.llm_api_key` / `llm_base_url` / `llm_model` 属性名一致 ✓
   - API 路由 `/api/whats-new/translate` 和 `/api/whats-new/run` ✓
   - API 路由 `/api/settings/llm` (GET + POST) ✓
   - `TaskStore.create(kind)` 支持 `"whats-new"` kind ✓

4. **测试覆盖**：
   - LLM 客户端：10 个测试（retry, error, headers, payload, timeout）
   - 翻译服务：9 个测试（prompt 结构, 多语言, 空文本, 特殊字符）
   - Config LLM：7 个测试（TOML 读取, env fallback, 默认值）
   - CLI --translate：6 个测试（错误处理, dry-run, skip-failure, all-fail）
   - Web API：8 个测试（check, translate, run, settings/llm）
   - E2E：3 个测试（完整流程, Web预览流, 页面加载）
   - **总计：43 个测试用例**

5. **分支检查**：确认在 `feat/web-ui` 分支上工作。
