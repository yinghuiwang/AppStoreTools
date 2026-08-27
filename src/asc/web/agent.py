"""Web failure-agent orchestrator: stream, gated tools, stop, draft promotion."""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from asc.llm import LLMHTTPError
from asc.web.agent_attachments import (
    attachment_form_paths,
    merge_user_content_with_attachments,
    normalize_attachments,
)
from asc.web.agent_vision import apply_current_turn_vision
from asc.web.agent_classify import classify_task_failure
from asc.web.agent_context import format_page_context, sanitize_page_context
from asc.web.agent_redact import redact_obj, redact_text
from asc.web.agent_tools import AgentToolContext, OPENAI_TOOLS, execute_model_tool
from asc.web.agent_workflow import format_workflow_line
from asc.web.i18n import t

AGENT_TOOL_LOOP_MAX = 8
AGENT_TURN_TIMEOUT_SEC = 600
_TOOL_RESULT_LLM_MAX = 2048
_SUMMARY_MAX = 200
_ASSISTANT_TOOL_CALLS_MARK = "_tool_calls"
# UI history stays short; the LLM window must be long enough to keep
# assistant tool_calls together with their role=tool results. MiniMax
# rejects orphan tool ids with HTTP 400 / 2013.
LLM_HISTORY_LIMIT = 80

_ERROR_KEYS = {
    "llm_not_configured": "agent.error.llm_not_configured",
    "llm_rate_limited": "agent.error.llm_rate_limited",
    "llm_unavailable": "agent.error.llm_unavailable",
    "timeout": "agent.error.timeout",
    "tool_limit": "agent.error.tool_limit",
    "internal": "agent.error.internal",
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
    "internal": {
        "zh": "Agent 内部出错",
        "en": "Agent hit an internal error",
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
    def __init__(self, code: str, *, detail: str = "", where: str = "") -> None:
        self.code = code
        self.detail = detail
        self.where = where
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


def format_agent_error(
    code: str,
    lang: str,
    *,
    detail: str = "",
    where: str = "",
) -> dict[str, str]:
    message = _error_message(code, lang)
    detail = redact_text(detail).strip()[:400]
    where = redact_text(where).strip()[:200]
    if where:
        message = (
            f"{message}（位置：{where}）"
            if lang == "zh"
            else f"{message} (where: {where})"
        )
    if detail:
        message = f"{message}\n{detail}"
    payload = {"code": code, "message": message}
    if where:
        payload["where"] = where
    if detail:
        payload["detail"] = detail
    return payload


def _llm_http_where(exc: LLMHTTPError) -> str:
    host = ""
    if exc.url:
        host = urlparse(exc.url).netloc
    if host:
        return f"LLM HTTP {exc.status_code} @ {host}"
    return f"LLM HTTP {exc.status_code}"


def _system_prompt(lang: str) -> str:
    language = "Chinese" if lang == "zh" else "English"
    return (
        f"You are an App Store Connect expert and web-task failure assistant. "
        f"Answer in {language}. "
        "For ASC listing copy, locales/languages, screenshots, IAP/subscriptions, "
        "version updates, What's New, or review rules: call search_knowledge or "
        "get_knowledge first, then combine with the current task/form. "
        "Those notes are packaged with this app; they are not in the user project. "
        "Do not use read_file, write_file, create_file, or delete_file on the knowledge base. "
        "Before generating listing or IAP assets, call get_knowledge(listing) or "
        "get_knowledge(iap) for those topic names. "
        "Prefer get_listing_snapshot, validate_listing, count_listing_fields, "
        "get_iap_snapshot, validate_iap, and inspect_screenshots over read_file "
        "for CSV, IAP JSON, and screenshots. "
        "Explain a failure first when one is in context. "
        "If it is locally fixable, call propose_fix. Otherwise give manual steps only. "
        "Never claim files were already changed or that a task was rerun. "
        "Never ask for or repeat secrets, API keys, issuer_id, key_id, .p8 paths, or PEM keys. "
        "Available tools: get_task, list_failed_tasks, get_task_log, get_profile_context, "
        "inspect_local, get_listing_snapshot, get_iap_snapshot, validate_listing, "
        "validate_iap, count_listing_fields, inspect_screenshots, search_knowledge, "
        "get_knowledge, grep, read_file, write_file, create_file, delete_file, propose_fix, "
        "offer_choices, set_workflow, get_asc_version, list_asc_iaps. "
        "Use offer_choices instead of listing 10 options as plain text. "
        "Prefer get_asc_version and list_asc_iaps over guessing version/IAP existence. "
        "Project paths stay inside the user workspace. Knowledge tools ignore project_root. "
        "Never read or write secrets (.env, *.p8, keys/, credentials, .git). "
        "write_file, create_file, and delete_file only draft a plan; the user must apply it. "
        "Do not call apply_fix, rerun_task, or choose. "
        "User messages may include an [attachments] section with workspace paths; "
        "read those files with read_file or inspect_local before answering."
    )


def _auto_analyze_text(lang: str, task_id: str, failure_hint: str = "") -> str:
    label = _localized(
        "agent.auto_analyze_label",
        lang,
        zh="请解释这次失败",
        en="Please explain this failure",
    )
    text = (
        f"{label}\n"
        f"task_id={task_id}\n"
        "First call get_task and get_task_log for this task. "
        "Then inspect_local if needed. Explain the failure. "
        "If it is locally fixable, call propose_fix; otherwise give manual steps only."
    )
    if failure_hint:
        text = f"{text}\n{failure_hint}"
    return text


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _usage_ints(usage: Any) -> dict[str, int] | None:
    if not isinstance(usage, dict):
        return None
    out: dict[str, int] = {}
    for key in _USAGE_KEYS:
        raw = usage.get(key)
        if raw is None:
            continue
        try:
            out[key] = int(raw)
        except (TypeError, ValueError):
            continue
    return out or None


def _done_metrics(started: float, tool_batches: int, usage: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
        "tool_batches": int(tool_batches),
    }
    usage_ints = _usage_ints(usage)
    if usage_ints:
        payload["usage"] = usage_ints
    return payload


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
    if name == "search_knowledge":
        hits = result.get("hits") or []
        topics = ", ".join(str(hit.get("topic") or "") for hit in hits[:3] if hit)
        return redact_text(topics or "ok")[:_SUMMARY_MAX]
    if name == "get_knowledge":
        return redact_text(str(result.get("topic") or "ok"))[:_SUMMARY_MAX]
    if result.get("summary"):
        return redact_text(str(result.get("summary")))[:_SUMMARY_MAX]
    return "ok"


_COMPACT_TOOL_KEYS = (
    "error",
    "summary",
    "error_count",
    "warning_count",
    "item_count",
    "group_count",
)
_COMPACT_DOMAIN_KEYS = frozenset(
    {
        "error_count",
        "warning_count",
        "item_count",
        "group_count",
        "locales",
        "issues",
    }
)


def _locale_codes_only(locales: Any) -> list[str]:
    codes: list[str] = []
    if not isinstance(locales, list):
        return codes
    for item in locales:
        if isinstance(item, str) and item:
            codes.append(item)
        elif isinstance(item, dict):
            code = item.get("locale")
            if code:
                codes.append(str(code))
    return codes


def _compact_tool_content(content: str) -> str:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content[:_TOOL_RESULT_LLM_MAX] if len(content) > _TOOL_RESULT_LLM_MAX else content
    if not isinstance(payload, dict) or "ok" not in payload:
        return content[:_TOOL_RESULT_LLM_MAX] if len(content) > _TOOL_RESULT_LLM_MAX else content
    has_domain = any(key in payload for key in _COMPACT_DOMAIN_KEYS)
    if not has_domain:
        return content[:_TOOL_RESULT_LLM_MAX] if len(content) > _TOOL_RESULT_LLM_MAX else content
    compact: dict[str, Any] = {"ok": payload.get("ok")}
    for key in _COMPACT_TOOL_KEYS:
        if key in payload and payload[key] not in (None, ""):
            compact[key] = payload[key]
    if "locales" in payload:
        compact["locales"] = _locale_codes_only(payload.get("locales"))
    if "issues" in payload:
        issues = payload.get("issues")
        compact["issues"] = issues[:12] if isinstance(issues, list) else issues
    return json.dumps(compact, ensure_ascii=False)


def _row_to_openai(row: dict[str, Any]) -> dict[str, Any]:
    role = row.get("role") or "user"
    content = row.get("content") or ""
    if role == "tool":
        content = _compact_tool_content(content)
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


def _tool_call_ids(message: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        ident = str(call.get("id") or "").strip()
        if ident:
            ids.append(ident)
    return ids


def sanitize_llm_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop incomplete tool groups so providers never see orphan tool ids.

    MiniMax (and OpenAI-compatible APIs) require every ``tool`` message's
    ``tool_call_id`` to appear on an earlier assistant ``tool_calls`` entry
    *in the same request*. A sliding history window can drop the assistant
    row while keeping the results, which MiniMax rejects as HTTP 400 / 2013.
    """
    declared_at: dict[str, int] = {}
    result_at: dict[str, int] = {}
    for idx, msg in enumerate(messages):
        role = str(msg.get("role") or "")
        if role == "assistant":
            for ident in _tool_call_ids(msg):
                declared_at[ident] = idx
        elif role == "tool":
            ident = str(msg.get("tool_call_id") or "").strip()
            if ident:
                result_at[ident] = idx

    drop: set[int] = set()
    for idx, msg in enumerate(messages):
        if str(msg.get("role") or "") != "tool":
            continue
        ident = str(msg.get("tool_call_id") or "").strip()
        declared_idx = declared_at.get(ident)
        if not ident or declared_idx is None or declared_idx >= idx:
            drop.add(idx)

    for idx, msg in enumerate(messages):
        if str(msg.get("role") or "") != "assistant":
            continue
        ids = _tool_call_ids(msg)
        if not ids:
            continue
        complete = True
        for ident in ids:
            result_idx = result_at.get(ident)
            if result_idx is None or result_idx in drop or result_idx <= idx:
                complete = False
                break
        if complete:
            continue
        drop.add(idx)
        for ident in ids:
            result_idx = result_at.get(ident)
            if result_idx is not None:
                drop.add(result_idx)

    cleaned: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        if idx not in drop:
            cleaned.append(msg)
            continue
        if str(msg.get("role") or "") != "assistant":
            continue
        if not _tool_call_ids(msg):
            continue
        text = str(msg.get("content") or "").strip()
        if text:
            cleaned.append({"role": "assistant", "content": text})
    return cleaned


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

    def _messages_for_llm(
        self,
        session_id: str,
        lang: str,
        extra_system: str = "",
        attachments: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.agent_store.list_messages(session_id, limit=LLM_HISTORY_LIMIT)
        system = _system_prompt(lang)
        workflow_line = format_workflow_line(self.agent_store.get_workflow(session_id))
        extras = [part for part in (extra_system, workflow_line) if part]
        if extras:
            system = f"{system}\n" + "\n".join(extras)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for row in rows:
            messages.append(_row_to_openai(row))
        messages = sanitize_llm_messages(messages)
        # Redact text rows first so image data URLs are not walked by redact_obj.
        messages = redact_obj(messages)
        return apply_current_turn_vision(messages, attachments)

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
        last_detail = ""
        last_where = "llm.chat_completions"
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
                last_where = _llm_http_where(exc)
                last_detail = exc.detail or str(exc)
                if emitted or attempt >= 2:
                    raise _TurnLLMError(
                        last_code, detail=last_detail, where=last_where
                    ) from exc
                if rate_limited:
                    wait = exc.retry_after if exc.retry_after is not None else 1.0
                    time.sleep(wait)
                    continue
                if exc.status_code >= 500:
                    time.sleep(1.0)
                    continue
                raise _TurnLLMError(
                    "llm_unavailable", detail=last_detail, where=last_where
                ) from exc
            except _NET_ERRORS as exc:
                last_code = "llm_unavailable"
                last_where = "llm.connect"
                last_detail = f"{type(exc).__name__}: {exc}"
                if emitted or attempt >= 2:
                    raise _TurnLLMError(
                        last_code, detail=last_detail, where=last_where
                    ) from exc
                time.sleep(1.0)
        raise _TurnLLMError(last_code, detail=last_detail, where=last_where)

    def run_turn(
        self,
        *,
        session_id: str | None,
        task_id: str | None,
        message: str,
        auto_analyze: bool,
        lang: str,
        llm_client: Any,
        form_paths: list[str] | None = None,
        profile: str = "",
        attachments: list[Any] | None = None,
        page_context: dict | None = None,
    ) -> Iterator[tuple[str, str]]:
        session_id = session_id or None
        task_id = task_id or None

        session = self.agent_store.get_session(session_id) if session_id else None
        if session is None:
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

        def emit_error(code: str, *, detail: str = "", where: str = "") -> tuple[str, str]:
            payload = format_agent_error(code, lang, detail=detail, where=where)
            if session_id:
                self._persist(session_id, "assistant", payload["message"])
            return ("error", _dump(payload))

        try:
            yield (
                "session",
                _dump({"session_id": session_id, "task_id": bound_task_id}),
            )
            if not _llm_ready(llm_client):
                yield emit_error("llm_not_configured", where="llm.config")
                return
            if self._is_stopped(session_id):
                yield ("stopped", _dump({"session_id": session_id}))
                return
            if timed_out():
                yield emit_error("timeout", where="agent.timeout")
                return

            user_content = (message or "").strip()
            page_block = format_page_context(sanitize_page_context(page_context), lang)
            if auto_analyze and bound_task_id:
                classified = classify_task_failure(
                    self.task_store, str(bound_task_id), lang=lang
                )
                hint_line = (
                    f"[failure_hint] code={classified.get('code') or 'unknown'} "
                    f"hint={classified.get('hint') or ''}\n"
                    "Treat this as a starting hypothesis. Still call get_task and get_task_log."
                )
                injected = _auto_analyze_text(lang, str(bound_task_id), hint_line)
                user_content = f"{injected}\n{user_content}".strip() if user_content else injected
            prepared = normalize_attachments(
                attachments,
                project_root=self.project_root,
                session_id=str(session_id),
            )
            extra_paths = attachment_form_paths(prepared)
            merged_form_paths = list(form_paths or [])
            merged_form_paths.extend(extra_paths)
            user_content = merge_user_content_with_attachments(user_content, prepared, lang)
            turn_seq = self._persist(session_id, "user", user_content)

            ctx = AgentToolContext(
                self.task_store,
                self.agent_store,
                bound_task_id,
                self.project_root,
                turn_seq=turn_seq,
                session_id=session_id,
                form_paths=merged_form_paths,
                attachment_paths=extra_paths,
                profile=profile or self._profile_for_task(bound_task_id),
            )
            tool_batches = 0
            last_usage: Any = None
            while True:
                if self._is_stopped(session_id):
                    yield ("stopped", _dump({"session_id": session_id}))
                    return
                if timed_out():
                    yield emit_error("timeout", where="agent.timeout")
                    return
                if tool_batches >= AGENT_TOOL_LOOP_MAX:
                    limit_text = _error_message("tool_limit", lang)
                    yield ("token", limit_text)
                    self._persist(session_id, "assistant", limit_text)
                    plan_ids = self.agent_store.promote_drafts(session_id, turn_seq)
                    finished_done = True
                    yield (
                        "done",
                        _dump(
                            {
                                "session_id": session_id,
                                "plan_ids": plan_ids,
                                "workflow": self.agent_store.get_workflow(session_id),
                                **_done_metrics(started, tool_batches, last_usage),
                            }
                        ),
                    )
                    return

                content_parts: list[str] = []
                buckets: dict[int, dict[str, str]] = {}
                finish: str | None = None
                try:
                    for event in self._stream_llm(
                        llm_client,
                        self._messages_for_llm(
                            session_id,
                            lang,
                            extra_system=page_block,
                            attachments=prepared,
                        ),
                    ):
                        if self._is_stopped(session_id):
                            yield ("stopped", _dump({"session_id": session_id}))
                            return
                        if timed_out():
                            yield emit_error("timeout", where="agent.timeout")
                            return
                        if event.get("usage"):
                            last_usage = event["usage"]
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
                    yield emit_error(exc.code, detail=exc.detail, where=exc.where)
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
                            yield emit_error("timeout", where="agent.timeout")
                            return
                        name = call["name"]
                        yield (
                            "tool_start",
                            _dump(
                                {
                                    "id": call["id"],
                                    "name": name,
                                    "arguments": call["arguments"],
                                }
                            ),
                        )
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
                        if name == "offer_choices" and result.get("ok"):
                            yield (
                                "choices",
                                _dump(self.agent_store.get_workflow(session_id)),
                            )
                    tool_batches += 1
                    continue

                if text:
                    self._persist(session_id, "assistant", text)
                plan_ids = self.agent_store.promote_drafts(session_id, turn_seq)
                finished_done = True
                yield (
                    "done",
                    _dump(
                        {
                            "session_id": session_id,
                            "plan_ids": plan_ids,
                            "workflow": self.agent_store.get_workflow(session_id),
                            **_done_metrics(started, tool_batches, last_usage),
                        }
                    ),
                )
                return
        except GeneratorExit:
            raise
        finally:
            if not finished_done and session_id and turn_seq is not None:
                self.agent_store.abandon_drafts(session_id, turn_seq)
