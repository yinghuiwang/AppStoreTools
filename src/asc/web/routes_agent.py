"""Agent HTTP routes: SSE stream, stop, apply/reject, failed-tasks, sessions."""
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from asc.web.agent import AGENT_TURN_TIMEOUT_SEC, WebAgent
from asc.web.agent_store import agent_store
from asc.web.agent_tools import AgentToolContext, apply_fix
from asc.web.i18n import t
from asc.web.sse import format_sse_event
from asc.web.tasks import TASK_KIND_LABELS

router = APIRouter()

AGENT_SSE_HEARTBEAT_SEC = 3.0
_ALLOWED_SSE = frozenset(
    {"session", "token", "tool_start", "tool_result", "error", "stopped", "done"}
)
_SENTINEL = object()


def _current_task_store():
    from asc.web import tasks as tasks_mod

    return tasks_mod.task_store


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _lang(request: Request) -> str:
    return getattr(request.state, "lang", None) or "en"


def _error_data(code: str, lang: str) -> str:
    return json.dumps(
        {"code": code, "message": t(f"agent.error.{code}", lang=lang)},
        ensure_ascii=False,
    )


def _llm_client_or_none():
    from asc.config import Config

    cfg = Config().get_active_llm_config()
    if not cfg:
        return None
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        return None
    from asc.llm import LLMClient

    return LLMClient(
        api_key=api_key,
        base_url=cfg.get("base_url") or "https://api.openai.com/v1",
        model=cfg.get("model") or "gpt-4o",
    )


def _web_agent() -> WebAgent:
    return WebAgent(agent_store=agent_store, task_store=_current_task_store())


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _failed_matches(row: dict[str, Any], needle: str) -> bool:
    task_id = str(row.get("id") or "").lower()
    kind = str(row.get("kind") or "").lower()
    title = str(row.get("title") or "").lower()
    label = str(TASK_KIND_LABELS.get(row.get("kind") or "", "")).lower()
    return (
        task_id.startswith(needle)
        or needle in kind
        or needle in title
        or needle in label
    )


def _form_paths_from_body(body: dict[str, Any]) -> list[str]:
    raw = body.get("form_paths")
    if not isinstance(raw, list):
        return []
    paths: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text:
            paths.append(text)
    return paths


def _sse_frames(
    agent: WebAgent,
    *,
    session_id: str | None,
    task_id: str | None,
    message: str,
    auto_analyze: bool,
    lang: str,
    llm_client: Any,
    form_paths: list[str] | None = None,
    profile: str = "",
):
    frames: queue.Queue = queue.Queue()
    session_holder: list[str | None] = [session_id]

    def produce() -> None:
        try:
            for event, data in agent.run_turn(
                session_id=session_id,
                task_id=task_id,
                message=message,
                auto_analyze=auto_analyze,
                lang=lang,
                llm_client=llm_client,
                form_paths=form_paths,
                profile=profile,
            ):
                if event == "session":
                    try:
                        parsed = json.loads(data) if data else {}
                    except json.JSONDecodeError:
                        parsed = {}
                    if isinstance(parsed, dict) and parsed.get("session_id"):
                        session_holder[0] = str(parsed["session_id"])
                if event in _ALLOWED_SSE:
                    frames.put(format_sse_event(event, data))
        except Exception:
            frames.put(format_sse_event("error", _error_data("llm_unavailable", lang)))
        finally:
            frames.put(_SENTINEL)

    threading.Thread(target=produce, name="agent-sse", daemon=True).start()
    deadline = time.monotonic() + AGENT_TURN_TIMEOUT_SEC

    def generate():
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                sid = session_holder[0]
                if sid:
                    WebAgent().request_stop(sid)
                    for plan in agent_store.list_plans(sid, statuses=("draft",)):
                        agent_store.abandon_drafts(sid, plan["turn_seq"])
                yield format_sse_event("error", _error_data("timeout", lang))
                return
            wait = min(AGENT_SSE_HEARTBEAT_SEC, remaining)
            try:
                item = frames.get(timeout=wait)
            except queue.Empty:
                yield ": heartbeat\n\n"
                continue
            if item is _SENTINEL:
                return
            yield item

    return generate()


@router.post("/stream")
async def agent_stream(request: Request):
    body = await _json_body(request)
    session_id = _opt_str(body.get("session_id"))
    task_id = _opt_str(body.get("task_id"))
    lang = _lang(request)
    llm_client = _llm_client_or_none()
    agent = _web_agent()
    cookie = (request.cookies.get("asc_profile") or "").strip()
    return StreamingResponse(
        _sse_frames(
            agent,
            session_id=session_id,
            task_id=task_id,
            message=str(body.get("message") or ""),
            auto_analyze=_as_bool(body.get("auto_analyze")),
            lang=lang,
            llm_client=llm_client,
            form_paths=_form_paths_from_body(body),
            profile=cookie,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/stop")
async def agent_stop(request: Request):
    body = await _json_body(request)
    session_id = _opt_str(body.get("session_id"))
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    WebAgent().request_stop(session_id)
    return {"ok": True}


@router.get("/failed-tasks")
def failed_tasks(
    request: Request,
    q: str | None = Query(None),
    kind: str | None = Query(None),
):
    cookie = (request.cookies.get("asc_profile") or "").strip() or None
    rows = _current_task_store().list_failed(
        limit=50,
        kind=_opt_str(kind),
        prefer_profile=cookie,
    )
    needle = (q or "").strip().lower()
    if needle:
        rows = [row for row in rows if _failed_matches(row, needle)]
    return {"tasks": rows}


@router.get("/sessions")
def agent_sessions(
    task_id: str | None = Query(None),
    session_id: str | None = Query(None),
):
    sid = _opt_str(session_id)
    bound = _opt_str(task_id)
    if sid:
        session = agent_store.get_session(sid)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
    elif bound:
        state = _current_task_store().get_state(bound)
        profile = str((state or {}).get("profile") or "")
        session = agent_store.get_or_create_session(bound, profile)
    else:
        raise HTTPException(status_code=400, detail="session_id or task_id is required")
    return {
        "session": session,
        "messages": agent_store.list_messages(session["id"]),
        "plans": agent_store.list_plans(session["id"], statuses=("pending",)),
    }


@router.get("/plans/{plan_id}")
def agent_plan(plan_id: str):
    plan = agent_store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return plan


@router.post("/apply")
async def agent_apply(request: Request):
    body = await _json_body(request)
    plan_id = _opt_str(body.get("plan_id"))
    if not plan_id:
        raise HTTPException(status_code=400, detail="plan_id is required")
    plan = agent_store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    mutations = plan.get("mutations") or []
    if not mutations:
        raise HTTPException(status_code=400, detail="empty mutations")
    if plan.get("status") != "pending":
        raise HTTPException(status_code=409, detail="conflict")

    session = agent_store.get_session(plan["session_id"])
    bound_task_id = (session or {}).get("task_id")
    cookie = (request.cookies.get("asc_profile") or "").strip()
    ctx = AgentToolContext(
        _current_task_store(),
        agent_store,
        bound_task_id,
        Path.cwd(),
        turn_seq=int(plan.get("turn_seq") or 1),
        session_id=plan.get("session_id") or "",
        form_paths=_form_paths_from_body(body),
        profile=cookie or str((session or {}).get("profile") or ""),
    )
    result = apply_fix(ctx, plan_id)
    if not result.get("ok"):
        if result.get("code") == "conflict":
            raise HTTPException(status_code=409, detail="conflict")
        return result

    rerun_info = plan.get("rerun")
    want_rerun = _as_bool(body.get("rerun")) and isinstance(rerun_info, dict)
    payload: dict[str, Any] = {"ok": True, "status": result.get("status") or "applied"}
    if want_rerun:
        from asc.web.agent_rerun import RerunError, rerun_task

        original_id = _opt_str(rerun_info.get("task_id"))
        try:
            if not original_id:
                raise RerunError("no_replay")
            new_task_id = rerun_task(original_id, task_store=_current_task_store())
            agent_store.set_plan_status(plan_id, "applied", new_task_id=new_task_id)
            payload["new_task_id"] = new_task_id
        except Exception as exc:
            payload["rerun_error"] = str(exc)
    return payload


@router.post("/reject")
async def agent_reject(request: Request):
    body = await _json_body(request)
    plan_id = _opt_str(body.get("plan_id"))
    if not plan_id:
        raise HTTPException(status_code=400, detail="plan_id is required")
    plan = agent_store.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    if not agent_store.reject_pending(plan_id):
        raise HTTPException(status_code=409, detail="conflict")
    return {"ok": True, "status": "rejected"}
