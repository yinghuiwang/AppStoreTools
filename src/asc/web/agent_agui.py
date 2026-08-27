"""Translate WebAgent legacy SSE tuples into TDesign Chat AG-UI events."""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

OPEN_TAGS = ("<think>", "<thinking>", "<reasoning>")
CLOSE_TAGS = ("</think>", "</thinking>", "</reasoning>")


def _parse_obj(data: str) -> dict[str, Any]:
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _find_tag(buf: str, tags: tuple[str, ...]) -> tuple[int, int] | None:
    lower = buf.lower()
    best: tuple[int, int] | None = None
    for tag in tags:
        index = lower.find(tag)
        if index >= 0 and (best is None or index < best[0]):
            best = (index, len(tag))
    return best


def _suffix_prefix_len(buf: str, tags: tuple[str, ...]) -> int:
    lower = buf.lower()
    max_keep = 0
    for tag in tags:
        n = min(len(tag) - 1, len(lower))
        for k in range(n, 0, -1):
            if lower.endswith(tag[:k]):
                max_keep = max(max_keep, k)
                break
    return max_keep


def split_think_delta(mode: str, hold: str, chunk: str) -> dict[str, str]:
    """Split a token delta into thinking / visible text around think tags."""
    buf = hold + chunk
    thinking = ""
    visible = ""
    current = mode
    while buf:
        tags = OPEN_TAGS if current == "text" else CLOSE_TAGS
        hit = _find_tag(buf, tags)
        if hit is None:
            keep = _suffix_prefix_len(buf, tags)
            ready = buf[: len(buf) - keep] if keep else buf
            if current == "think":
                thinking += ready
            else:
                visible += ready
            buf = buf[len(buf) - keep :] if keep else ""
            break
        index, length = hit
        before = buf[:index]
        if current == "think":
            thinking += before
        else:
            visible += before
        buf = buf[index + length :]
        current = "think" if current == "text" else "text"
    return {"thinking": thinking, "visible": visible, "mode": current, "hold": buf}


def split_stored_text(text: str) -> tuple[str, str]:
    split = split_think_delta("text", "", text)
    thinking = split["thinking"] + (split["hold"] if split["mode"] == "think" else "")
    visible = split["visible"] + (split["hold"] if split["mode"] == "text" else "")
    return thinking, visible


class AguiTurnTranslator:
    """Stateful mapper: one WebAgent turn → AG-UI event dicts."""

    def __init__(
        self,
        *,
        run_id: str,
        think_title: str = "Thinking...",
        think_done_title: str = "Thought complete",
        agent_store: Any | None = None,
    ) -> None:
        self.run_id = run_id
        self.thread_id = ""
        self.think_title = think_title
        self.think_done_title = think_done_title
        self.agent_store = agent_store
        self.mode = "text"
        self.hold = ""
        self.thinking_open = False
        self.text_open = False
        self.text_id = ""
        self.seq = 0

    def _next_id(self, prefix: str) -> str:
        self.seq += 1
        return f"{prefix}_{self.run_id}_{self.seq}"

    def _ensure_text_id(self) -> str:
        if not self.text_id:
            self.text_id = self._next_id("msg")
        return self.text_id

    def _open_thinking(self) -> Iterator[dict[str, Any]]:
        if self.thinking_open:
            return
        self.thinking_open = True
        yield {
            "type": "THINKING_TEXT_MESSAGE_START",
            "title": self.think_title,
        }

    def _close_thinking(self) -> Iterator[dict[str, Any]]:
        if not self.thinking_open:
            return
        self.thinking_open = False
        yield {
            "type": "THINKING_TEXT_MESSAGE_END",
            "title": self.think_done_title,
        }

    def _open_text(self) -> Iterator[dict[str, Any]]:
        if self.text_open:
            return
        self.text_open = True
        yield {
            "type": "TEXT_MESSAGE_START",
            "messageId": self._ensure_text_id(),
            "role": "assistant",
        }

    def _close_text(self) -> Iterator[dict[str, Any]]:
        if not self.text_open:
            return
        message_id = self._ensure_text_id()
        self.text_open = False
        self.text_id = ""
        yield {"type": "TEXT_MESSAGE_END", "messageId": message_id}

    def _close_streams(self) -> Iterator[dict[str, Any]]:
        if self.hold:
            if self.mode == "think":
                yield from self._emit_thinking(self.hold)
            else:
                yield from self._emit_visible(self.hold)
            self.hold = ""
        self.mode = "text"
        yield from self._close_thinking()
        yield from self._close_text()

    def _emit_thinking(self, text: str) -> Iterator[dict[str, Any]]:
        if not text:
            return
        yield from self._close_text()
        yield from self._open_thinking()
        yield {"type": "THINKING_TEXT_MESSAGE_CONTENT", "delta": text}

    def _emit_visible(self, text: str) -> Iterator[dict[str, Any]]:
        if not text:
            return
        yield from self._close_thinking()
        yield from self._open_text()
        yield {
            "type": "TEXT_MESSAGE_CONTENT",
            "messageId": self._ensure_text_id(),
            "delta": text,
        }

    def translate(self, event: str, data: str) -> Iterator[dict[str, Any]]:
        if event == "session":
            payload = _parse_obj(data)
            self.thread_id = str(payload.get("session_id") or self.thread_id or self.run_id)
            yield {
                "type": "RUN_STARTED",
                "threadId": self.thread_id,
                "runId": self.run_id,
            }
            yield {"type": "CUSTOM", "name": "session", "value": payload}
            return

        if event == "token":
            split = split_think_delta(self.mode, self.hold, data)
            self.mode = split["mode"]
            self.hold = split["hold"]
            yield from self._emit_thinking(split["thinking"])
            yield from self._emit_visible(split["visible"])
            return

        if event == "thinking":
            if data.strip():
                yield from self._emit_thinking(data)
            return

        if event == "tool_start":
            yield from self._close_streams()
            payload = _parse_obj(data)
            tool_id = str(payload.get("id") or self._next_id("tool"))
            name = str(payload.get("name") or "tool")
            args = payload.get("arguments")
            if not isinstance(args, str):
                args = json.dumps(args or {}, ensure_ascii=False)
            yield {
                "type": "TOOL_CALL_START",
                "toolCallId": tool_id,
                "toolCallName": name,
                "parentMessageId": self.run_id,
            }
            yield {"type": "TOOL_CALL_ARGS", "toolCallId": tool_id, "delta": args}
            return

        if event == "tool_result":
            payload = _parse_obj(data)
            tool_id = str(payload.get("id") or self._next_id("tool"))
            name = str(payload.get("name") or "tool")
            yield {"type": "TOOL_CALL_END", "toolCallId": tool_id}
            yield {
                "type": "TOOL_CALL_RESULT",
                "messageId": f"toolmsg_{tool_id}",
                "toolCallId": tool_id,
                "toolCallName": name,
                "content": json.dumps(payload, ensure_ascii=False),
                "role": "tool",
            }
            return

        if event == "error":
            yield from self._close_streams()
            payload = _parse_obj(data)
            message = str(payload.get("message") or data or "error")
            code = str(payload.get("code") or "")
            where = str(payload.get("where") or "")
            yield from self._close_text()
            err: dict[str, Any] = {"type": "RUN_ERROR", "message": message}
            if code:
                err["code"] = code
            if where:
                err["where"] = where
            yield err
            return

        if event == "stopped":
            yield from self._close_streams()
            payload = _parse_obj(data)
            if payload.get("session_id"):
                self.thread_id = str(payload["session_id"])
            yield {
                "type": "RUN_FINISHED",
                "threadId": self.thread_id or self.run_id,
                "runId": self.run_id,
                "result": {"stopped": True, **payload},
            }
            return

        if event == "choices":
            payload = _parse_obj(data)
            yield {
                "type": "ACTIVITY_SNAPSHOT",
                "messageId": self._next_id("choice"),
                "activityType": "offer_choices",
                "content": payload,
                "replace": True,
            }
            return

        if event == "done":
            yield from self._close_streams()
            payload = _parse_obj(data)
            if payload.get("session_id"):
                self.thread_id = str(payload["session_id"])
            for plan_id in payload.get("plan_ids") or []:
                plan = None
                if self.agent_store is not None:
                    plan = self.agent_store.get_plan(str(plan_id))
                content = plan if isinstance(plan, dict) else {"id": str(plan_id)}
                yield {
                    "type": "ACTIVITY_SNAPSHOT",
                    "messageId": self._next_id("plan"),
                    "activityType": "propose_fix",
                    "content": content,
                    "replace": True,
                }
            yield {"type": "CUSTOM", "name": "done", "value": payload}
            yield {
                "type": "RUN_FINISHED",
                "threadId": self.thread_id or self.run_id,
                "runId": self.run_id,
                "result": payload,
            }


def translate_legacy_events(
    events: Iterator[tuple[str, str]] | list[tuple[str, str]],
    *,
    run_id: str,
    think_title: str = "Thinking...",
    think_done_title: str = "Thought complete",
    agent_store: Any | None = None,
) -> Iterator[dict[str, Any]]:
    translator = AguiTurnTranslator(
        run_id=run_id,
        think_title=think_title,
        think_done_title=think_done_title,
        agent_store=agent_store,
    )
    for event, data in events:
        yield from translator.translate(event, data)
