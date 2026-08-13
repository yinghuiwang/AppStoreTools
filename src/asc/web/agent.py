"""Web failure-agent orchestrator: stream, gated tools, stop, draft promotion."""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import requests

from asc.llm import LLMHTTPError
from asc.web.agent_redact import redact_obj, redact_text
from asc.web.agent_tools import AgentToolContext, OPENAI_TOOLS, execute_model_tool
from asc.web.i18n import t

AGENT_TOOL_LOOP_MAX = 8
AGENT_TURN_TIMEOUT_SEC = 600
_TOOL_RESULT_LLM_MAX = 2048
_SUMMARY_MAX = 200
_ASSISTANT_TOOL_CALLS_MARK = "_tool_calls"

_ERROR_KEYS = {
    "llm_not_configured": "agent.error.llm_not_configured",
    "llm_rate_limited": "agent.error.llm_rate_limited",
    "llm_unavailable": "agent.error.llm_unavailable",
    "timeout": "agent.error.timeout",
    "tool_limit": "agent.error.tool_limit",
}

_ERROR_FALLBACKS = {
    "llm_not_configured": {
        "zh": "未配置 LLM，请到设置页添加 API Key",
        "en": "LLM is not configured. Add an API key on the Settings page",
    },
    "llm_rate_limited": {
        "zh": "LLM 请求过于频繁，请稍后重试",
        "en": "LLM rate limited. Please try again later",
    },
    "llm_unavailable": {
        "zh": "LLM 服务暂不可用，请稍后重试",
        "en": "LLM is temporarily unavailable. Please try again later",
    },
    "timeout": {
        "zh": "本轮分析超时，未写入任何文件",
        "en": "This analysis timed out. No files were written",
    },
    "tool_limit": {
        "zh": "本轮工具次数已用尽，请再问一次",
        "en": "This turn used up its tool calls. Please ask again",
    },
}

_NET_ERRORS = (
    TimeoutError,
    ConnectionError,
    requests.Timeout,
    requests.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
)


class _TurnLLMError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _localized(key: str, lang: str, *, zh: str, en: str) -> str:
    text = t(key, lang=lang)
    if text != key:
        return text
    return zh if lang == "zh" else en


def _error_message(code: str, lang: str) -> str:
    key = _ERROR_KEYS.get(code, f"agent.error.{code}")
    fallbacks = _ERROR_FALLBACKS.get(code) or {}
    return _localized(
        key,
        lang,
        zh=fallbacks.get("zh") or key,
        en=fallbacks.get("en") or key,
    )


def _system_prompt(lang: str) -> str:
    language = "Chinese" if lang == "zh" else "English"
    return (
        f"You are an App Store Connect web-task failure assistant. Answer in {language}. "
        "Explain this failure first. "
        "If it is locally fixable, call propose_fix. Otherwise give manual steps only. "
        "Never claim files were already changed or that a task was rerun. "
        "Never ask for or repeat secrets, API keys, issuer_id, key_id, .p8 paths, or PEM keys. "
        "Available tools: get_task, list_failed_tasks, get_task_log, get_profile_context, "
        "inspect_local, propose_fix. Do not call apply_fix or rerun_task."
    )


def _auto_analyze_text(lang: str, task_id: str) -> str:
    label = _localized(
        "agent.auto_analyze_label",
        lang,
        zh="请解释这次失败",
        en="Please explain this failure",
    )
    return (
        f"{label}\n"
        f"task_id={task_id}\n"
        "First call get_task and get_task_log for this task. "
        "Then inspect_local if needed. Explain the failure. "
        "If it is locally fixable, call propose_fix; otherwise give manual steps only."
    )


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _accumulate_tool_calls(buckets: dict[int, dict[str, str]], deltas: list) -> None:
    for delta in deltas:
        if not isinstance(delta, dict):
            continue
        idx = int(delta.get("index") or 0)
        slot = buckets.setdefault(idx, {"id": "", "name": "", "arguments": ""})
        if delta.get("id"):
            slot["id"] = str(delta["id"])
        fn = delta.get("function") or {}
        if not isinstance(fn, dict):
            fn = {}
        if fn.get("name"):
            slot["name"] = str(fn["name"])
        if fn.get("arguments"):
            slot["arguments"] += str(fn["arguments"])


def _ordered_calls(buckets: dict[int, dict[str, str]]) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []
    for idx in sorted(buckets):
        slot = buckets[idx]
        calls.append(
            {
                "id": slot["id"] or f"call_{idx}",
                "name": slot["name"],
                "arguments": slot["arguments"] or "{}",
            }
        )
    return calls


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_summary(name: str, result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return redact_text(str(result))[:_SUMMARY_MAX]
    if not result.get("ok"):
        return redact_text(str(result.get("error") or "error"))[:_SUMMARY_MAX]
    if name == "get_task":
        return redact_text(
            f"{result.get('kind') or ''} {result.get('status') or ''}".strip() or "ok"
        )[:_SUMMARY_MAX]
    if name == "get_task_log":
        lines = result.get("lines") or []
        return f"{len(lines)} log lines"
    if name == "propose_fix":
        return redact_text(str(result.get("plan_id") or "draft"))[:_SUMMARY_MAX]
    if name == "list_failed_tasks":
        tasks = result.get("tasks") or []
        return f"{len(tasks)} failed tasks"
    return "ok"


def _row_to_openai(row: dict[str, Any]) -> dict[str, Any]:
    role = row.get("role") or "user"
    content = row.get("content") or ""
    if role == "tool":
        if len(content) > _TOOL_RESULT_LLM_MAX:
            content = content[:_TOOL_RESULT_LLM_MAX]
        message: dict[str, Any] = {
            "role": "tool",
            "content": content,
            "tool_call_id": row.get("tool_call_id") or "",
        }
        tool_name = row.get("tool_name")
        if tool_name:
            message["name"] = tool_name
        return message
    if role == "assistant" and row.get("tool_name") == _ASSISTANT_TOOL_CALLS_MARK:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return {"role": "assistant", "content": content}
        message = {
            "role": "assistant",
            "content": payload.get("content"),
            "tool_calls": payload.get("tool_calls") or [],
        }
        return message
    return {"role": role, "content": content}


def _llm_ready(llm_client: Any) -> bool:
    if llm_client is None:
        return False
    if hasattr(llm_client, "api_key") and not getattr(llm_client, "api_key"):
        return False
    return True


class WebAgent:
    """Sync generator orchestrator for one Agent turn."""

    _STOPS: dict[str, threading.Event] = {}
    _STOP_LOCK = threading.Lock()

    def __init__(
        self,
        *,
        agent_store: Any | None = None,
        task_store: Any | None = None,
        project_root: Path | str | None = None,
    ) -> None:
        if agent_store is None:
            from asc.web.agent_store import agent_store as default_agent_store

            agent_store = default_agent_store
        if task_store is None:
            from asc.web.tasks import task_store as default_task_store

            task_store = default_task_store
        self.agent_store = agent_store
        self.task_store = task_store
        self.project_root = (
            Path(project_root).resolve() if project_root is not None else Path.cwd()
        )

    def request_stop(self, session_id: str) -> None:
        self._stop_event(session_id).set()

    def _stop_event(self, session_id: str) -> threading.Event:
        with self._STOP_LOCK:
            return self._STOPS.setdefault(session_id, threading.Event())

    def _is_stopped(self, session_id: str) -> bool:
        with self._STOP_LOCK:
            event = self._STOPS.get(session_id)
        return bool(event and event.is_set())

    def _profile_for_task(self, task_id: str | None) -> str:
        if not task_id:
            return ""
        state = self.task_store.get_state(str(task_id))
        if not state:
            return ""
        return str(state.get("profile") or "")

    def _messages_for_llm(self, session_id: str, lang: str) -> list[dict[str, Any]]:
        rows = self.agent_store.list_messages(session_id, limit=20)
        messages: list[dict[str, Any]] = [{"role": "system", "content": _system_prompt(lang)}]
        for row in rows:
            messages.append(_row_to_openai(row))
        return redact_obj(messages)

    def _persist(self, session_id: str, role: str, content: str, **kwargs: Any) -> int:
        return self.agent_store.append_message(
            session_id, role, redact_text(content), **kwargs
        )

    def _persist_tool_calls(
        self,
        session_id: str,
        calls: list[dict[str, str]],
        content: str,
    ) -> None:
        tool_calls = [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": call["arguments"]},
            }
            for call in calls
        ]
        payload = redact_obj({"tool_calls": tool_calls, "content": content or None})
        self.agent_store.append_message(
            session_id,
            "assistant",
            json.dumps(payload, ensure_ascii=False),
            tool_name=_ASSISTANT_TOOL_CALLS_MARK,
        )

    def _stream_llm(self, llm_client: Any, messages: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
        last_code = "llm_unavailable"
        for attempt in range(3):
            emitted = False
            try:
                for event in llm_client.chat_stream(
                    messages, OPENAI_TOOLS, temperature=0.3
                ):
                    emitted = True
                    yield event
                return
            except LLMHTTPError as exc:
                rate_limited = exc.status_code == 429
                last_code = "llm_rate_limited" if rate_limited else "llm_unavailable"
                if emitted or attempt >= 2:
                    raise _TurnLLMError(last_code) from exc
                if rate_limited:
                    wait = exc.retry_after if exc.retry_after is not None else 1.0
                    time.sleep(wait)
                    continue
                if exc.status_code >= 500:
                    time.sleep(1.0)
                    continue
                raise _TurnLLMError("llm_unavailable") from exc
            except _NET_ERRORS as exc:
                last_code = "llm_unavailable"
                if emitted or attempt >= 2:
                    raise _TurnLLMError(last_code) from exc
                time.sleep(1.0)
        raise _TurnLLMError(last_code)

    def run_turn(
        self,
        *,
        session_id: str | None,
        task_id: str | None,
        message: str,
        auto_analyze: bool,
        lang: str,
        llm_client: Any,
    ) -> Iterator[tuple[str, str]]:
        session_id = session_id or None
        task_id = task_id or None
        if not session_id and not task_id:
            return

        session = self.agent_store.get_session(session_id) if session_id else None
        if session is None:
            if not task_id:
                return
            session = self.agent_store.get_or_create_session(
                task_id, self._profile_for_task(task_id)
            )
        session_id = session["id"]
        bound_task_id = task_id or session.get("task_id")
        lang = lang or "en"
        started = time.monotonic()
        turn_seq: int | None = None
        finished_done = False
        self._stop_event(session_id).clear()

        def timed_out() -> bool:
            return (time.monotonic() - started) >= AGENT_TURN_TIMEOUT_SEC

        try:
            yield (
                "session",
                _dump({"session_id": session_id, "task_id": bound_task_id}),
            )
            if not _llm_ready(llm_client):
                yield (
                    "error",
                    _dump(
                        {
                            "code": "llm_not_configured",
                            "message": _error_message("llm_not_configured", lang),
                        }
                    ),
                )
                return
            if self._is_stopped(session_id):
                yield ("stopped", _dump({"session_id": session_id}))
                return
            if timed_out():
                yield (
                    "error",
                    _dump(
                        {
                            "code": "timeout",
                            "message": _error_message("timeout", lang),
                        }
                    ),
                )
                return

            user_content = (message or "").strip()
            if auto_analyze and bound_task_id:
                injected = _auto_analyze_text(lang, str(bound_task_id))
                user_content = f"{injected}\n{user_content}".strip() if user_content else injected
            turn_seq = self._persist(session_id, "user", user_content)

            ctx = AgentToolContext(
                self.task_store,
                self.agent_store,
                bound_task_id,
                self.project_root,
                turn_seq=turn_seq,
                session_id=session_id,
            )
            tool_batches = 0
            while True:
                if self._is_stopped(session_id):
                    yield ("stopped", _dump({"session_id": session_id}))
                    return
                if timed_out():
                    yield (
                        "error",
                        _dump(
                            {
                                "code": "timeout",
                                "message": _error_message("timeout", lang),
                            }
                        ),
                    )
                    return
                if tool_batches >= AGENT_TOOL_LOOP_MAX:
                    limit_text = _error_message("tool_limit", lang)
                    yield ("token", limit_text)
                    self._persist(session_id, "assistant", limit_text)
                    plan_ids = self.agent_store.promote_drafts(session_id, turn_seq)
                    finished_done = True
                    yield ("done", _dump({"session_id": session_id, "plan_ids": plan_ids}))
                    return

                content_parts: list[str] = []
                buckets: dict[int, dict[str, str]] = {}
                finish: str | None = None
                try:
                    for event in self._stream_llm(
                        llm_client, self._messages_for_llm(session_id, lang)
                    ):
                        if self._is_stopped(session_id):
                            yield ("stopped", _dump({"session_id": session_id}))
                            return
                        if timed_out():
                            yield (
                                "error",
                                _dump(
                                    {
                                        "code": "timeout",
                                        "message": _error_message("timeout", lang),
                                    }
                                ),
                            )
                            return
                        deltas = event.get("tool_calls")
                        if deltas:
                            _accumulate_tool_calls(buckets, deltas)
                        elif event.get("content"):
                            fragment = str(event["content"])
                            content_parts.append(fragment)
                            yield ("token", fragment)
                        if event.get("finish_reason"):
                            finish = str(event["finish_reason"])
                except _TurnLLMError as exc:
                    yield (
                        "error",
                        _dump(
                            {
                                "code": exc.code,
                                "message": _error_message(exc.code, lang),
                            }
                        ),
                    )
                    return

                text = "".join(content_parts)
                if finish == "tool_calls" or buckets:
                    calls = _ordered_calls(buckets)
                    self._persist_tool_calls(session_id, calls, text)
                    for call in calls:
                        if self._is_stopped(session_id):
                            yield ("stopped", _dump({"session_id": session_id}))
                            return
                        if timed_out():
                            yield (
                                "error",
                                _dump(
                                    {
                                        "code": "timeout",
                                        "message": _error_message("timeout", lang),
                                    }
                                ),
                            )
                            return
                        name = call["name"]
                        yield ("tool_start", _dump({"id": call["id"], "name": name}))
                        result = execute_model_tool(
                            ctx, name, _parse_arguments(call["arguments"])
                        )
                        result = redact_obj(result if isinstance(result, dict) else {"ok": False})
                        encoded = json.dumps(result, ensure_ascii=False, default=str)
                        self.agent_store.append_message(
                            session_id,
                            "tool",
                            redact_text(encoded),
                            tool_name=name or None,
                            tool_call_id=call["id"],
                        )
                        yield (
                            "tool_result",
                            _dump(
                                {
                                    "id": call["id"],
                                    "name": name,
                                    "ok": bool(result.get("ok")),
                                    "summary": _tool_summary(name, result),
                                }
                            ),
                        )
                    tool_batches += 1
                    continue

                if text:
                    self._persist(session_id, "assistant", text)
                plan_ids = self.agent_store.promote_drafts(session_id, turn_seq)
                finished_done = True
                yield ("done", _dump({"session_id": session_id, "plan_ids": plan_ids}))
                return
        except GeneratorExit:
            raise
        finally:
            if not finished_done and session_id and turn_seq is not None:
                self.agent_store.abandon_drafts(session_id, turn_seq)
