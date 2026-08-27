"""Sanitize, format, and apply Agent workflow choice state."""
from __future__ import annotations

from typing import Any

WORKFLOW_PHASES = (
    "idle",
    "collecting",
    "awaiting_choice",
    "confirmed",
    "expanding",
)
WORKFLOW_KINDS = ("listing", "iap", "generic")

_PHASES = frozenset(WORKFLOW_PHASES)
_KINDS = frozenset(WORKFLOW_KINDS)
_PROMPT_MAX = 300
_LABEL_MAX = 80
_DESCRIPTION_MAX = 80
_FORMAT_LABEL_MAX = 40
_CONFLICT = {"ok": False, "code": "conflict"}
_CHOICE_CONTINUE = (
    "Continue the workflow from this confirmed choice. Do not re-ask these options."
)


def default_workflow() -> dict[str, Any]:
    return {"phase": "idle"}


def sanitize_option(raw: Any, index: int) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    option_id = str(raw.get("id") or "").strip() or f"opt_{index}"
    label = str(raw.get("label") or "").strip()
    if not option_id or not label:
        return None
    option: dict[str, str] = {"id": option_id, "label": label[:_LABEL_MAX]}
    description = raw.get("description")
    if isinstance(description, str) and description.strip():
        option["description"] = description.strip()[:_DESCRIPTION_MAX]
    return option


def sanitize_options(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    options: list[dict[str, str]] = []
    for index, item in enumerate(raw, start=1):
        cleaned = sanitize_option(item, index)
        if cleaned is not None:
            options.append(cleaned)
    return options


def sanitize_workflow(data: Any, *, now: str | None = None) -> dict[str, Any]:
    if not isinstance(data, dict) or not data:
        return default_workflow()
    phase = data.get("phase")
    if phase not in _PHASES:
        phase = "idle"
    out: dict[str, Any] = {"phase": phase}
    kind = data.get("kind")
    if kind in _KINDS:
        out["kind"] = kind
    prompt = data.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        out["prompt"] = prompt.strip()[:_PROMPT_MAX]
    options = sanitize_options(data.get("options"))
    if options:
        out["options"] = options
    selected = data.get("selected_id")
    if selected is None or selected == "":
        if "selected_id" in data:
            out["selected_id"] = None
    else:
        out["selected_id"] = str(selected).strip() or None
    updated = now or data.get("updated_at")
    if isinstance(updated, str) and updated.strip():
        out["updated_at"] = updated.strip()
    return out


def format_workflow_line(data: dict[str, Any] | None) -> str:
    workflow = data if isinstance(data, dict) else default_workflow()
    phase = str(workflow.get("phase") or "idle")
    kind = str(workflow.get("kind") or "")
    selected = workflow.get("selected_id")
    selected_text = "" if selected is None else str(selected)
    parts = [f"[workflow] phase={phase} kind={kind} selected={selected_text}"]
    if phase == "awaiting_choice":
        bits: list[str] = []
        for option in workflow.get("options") or []:
            if not isinstance(option, dict):
                continue
            option_id = str(option.get("id") or "")
            label = str(option.get("label") or "")[:_FORMAT_LABEL_MAX]
            if option_id:
                bits.append(f"{option_id}:{label}")
        if bits:
            parts.append(" ".join(bits))
    return " ".join(parts)


def apply_choice(store: Any, session_id: str, option_id: str) -> dict[str, Any]:
    if not session_id or not option_id or store is None:
        return dict(_CONFLICT)
    if store.get_session(session_id) is None:
        return dict(_CONFLICT)
    workflow = store.get_workflow(session_id)
    if workflow.get("phase") != "awaiting_choice":
        return dict(_CONFLICT)
    match: dict[str, str] | None = None
    for option in workflow.get("options") or []:
        if isinstance(option, dict) and option.get("id") == option_id:
            match = option
            break
    if match is None:
        return dict(_CONFLICT)
    updated = dict(workflow)
    updated["phase"] = "confirmed"
    updated["selected_id"] = option_id
    store.set_workflow(session_id, updated)
    kind = str(workflow.get("kind") or "generic")
    label = str(match.get("label") or "")
    prompt = f"[choice] kind={kind} id={option_id} label={label}\n{_CHOICE_CONTINUE}"
    return {"ok": True, "prompt": prompt}
