"""Model-visible Agent tools plus server-only apply_fix. Writes stay gated."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import toml

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef, import-not-found]

from asc.config import Config
from asc.listing.local import (
    FileChangedError,
    PathTraversalError,
    _assert_under_root,
    apply_screenshot_order,
    delete_screenshot,
    load_local_text_snapshot,
    rename_screenshot,
    save_local_csv,
)
from asc.listing.models import FIELD_NAMES
from asc.web.agent_redact import redact_obj, redact_text
from asc.web.task_runner import FORBIDDEN_REPLAY_KEYS

MODEL_TOOL_NAMES = (
    "get_task",
    "list_failed_tasks",
    "get_task_log",
    "get_profile_context",
    "inspect_local",
    "propose_fix",
)

_GATED_ERROR = "writes are gated; use propose_fix"
_RESULT_PARAMS_MAX = 4096
_LOG_LINE_TOTAL = 400
_LOG_ERROR_CAP = 200
_LOG_PAYLOAD_MAX = 80 * 1024
_INSPECT_MAX_BYTES = 65536
_DIR_LIST_CAP = 500
_SECRET_KEYS = {key.lower() for key in FORBIDDEN_REPLAY_KEYS}
_BUILD_LOG_NAMES = ("build.log", "export.log", "upload.log")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".tif", ".tiff"}
_ERROR_LINE_RE = re.compile(
    r"\b(error|failed|failure|fatal|exception|traceback)\b|错误|失败|异常",
    re.I,
)
_CREDENTIALS_SECTION_RE = re.compile(r"(?is)^\[credentials\][^\[]*")
_CREDENTIALS_BLOCK_RE = re.compile(r"(?im)^\[credentials\][^\[]*")
_CONFLICT = {"ok": False, "code": "conflict"}
_ALLOWED_MUTATION_OPS = frozenset(
    {"csv_set_fields", "json_patch", "toml_set", "text_replace", "screenshot_fs"}
)
_TOML_ALLOWED_KEYS = frozenset(
    {
        "defaults.csv",
        "defaults.screenshots",
        "build.project",
        "build.scheme",
        "build.output",
        "build.signing",
    }
)
_TOML_SIGNING_VALUES = frozenset({"auto", "manual"})
_JSON_PATCH_OPS = frozenset({"replace", "add", "remove"})
_JSON_POINTER_TERMINALS = frozenset(
    {
        "name",
        "description",
        "reviewNote",
        "displayName",
        "baseAmount",
        "price",
        "reviewScreenshot",
        "reviewScreenshotPath",
        "screenshot",
        "screenshotPath",
    }
)
_SCREENSHOT_ACTIONS = frozenset({"rename", "delete", "reorder"})
_FIELD_NAME_SET = frozenset(FIELD_NAMES)


def _tool_schema(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


OPENAI_TOOLS: list[dict] = [
    _tool_schema(
        "get_task",
        "Get one task's kind, status, redacted result, and replay params. No logs.",
        {
            "task_id": {"type": "string", "description": "Task id to load"},
        },
        ["task_id"],
    ),
    _tool_schema(
        "list_failed_tasks",
        "List recent failed tasks (status=error). No log bodies.",
        {
            "kind": {"type": "string", "description": "Optional task kind filter"},
            "profile": {"type": "string", "description": "Optional profile filter"},
            "limit": {
                "type": "integer",
                "description": "Max rows (default 20, cap 50)",
            },
        },
    ),
    _tool_schema(
        "get_task_log",
        "Get redacted task logs: error/traceback lines plus tail context, max 400 lines.",
        {
            "task_id": {"type": "string", "description": "Task id"},
            "tail": {
                "type": "integer",
                "description": "Tail context lines (default 400)",
            },
        },
        ["task_id"],
    ),
    _tool_schema(
        "get_profile_context",
        "Profile name, csv/screenshots/iap paths, and local [defaults]/[build] only.",
        {
            "profile": {
                "type": "string",
                "description": "Profile name; defaults to the bound task profile",
            },
        },
    ),
    _tool_schema(
        "inspect_local",
        "Read an allow-listed local text file or list a screenshots directory.",
        {
            "path": {"type": "string", "description": "Absolute or project-relative path"},
            "max_bytes": {
                "type": "integer",
                "description": "Max bytes to read (default 65536, cap 65536)",
            },
        },
        ["path"],
    ),
    _tool_schema(
        "propose_fix",
        "Validate and store a draft local-fix plan. Does not write business files.",
        {
            "summary": {"type": "string"},
            "mutations": {"type": "array", "items": {"type": "object"}},
            "rerun": {"type": "object"},
            "manual_steps": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        ["summary"],
    ),
]


@dataclass
class AgentToolContext:
    task_store: Any
    agent_store: Any
    bound_task_id: str | None
    project_root: Path
    turn_seq: int
    session_id: str = ""

    def __post_init__(self) -> None:
        self.project_root = Path(self.project_root).resolve()


class _ApplyStepError(Exception):
    """A single mutation failed during apply_fix."""


def execute_model_tool(ctx: AgentToolContext, name: str, arguments: dict) -> dict:
    """Run one model-visible tool. Unknown or write tools never touch disk."""
    if name not in MODEL_TOOL_NAMES:
        return {"ok": False, "error": _GATED_ERROR}
    payload = arguments if isinstance(arguments, dict) else {}
    handler = _HANDLERS[name]
    try:
        return handler(ctx, payload)
    except Exception as exc:
        return {"ok": False, "error": redact_text(str(exc))}


def apply_fix(ctx: AgentToolContext, plan_id: str) -> dict:
    """Apply a pending plan's mutations. Not a model tool; no rerun."""
    if ctx.agent_store is None:
        return dict(_CONFLICT)
    plan = ctx.agent_store.get_plan(plan_id)
    if plan is None:
        return dict(_CONFLICT)
    if ctx.session_id and plan.get("session_id") != ctx.session_id:
        return dict(_CONFLICT)
    claimed = ctx.agent_store.claim_pending(plan_id)
    if claimed is None:
        return dict(_CONFLICT)
    mutations = claimed.get("mutations") or []
    for index, mutation in enumerate(mutations):
        try:
            _apply_one_mutation(ctx, mutation)
        except Exception as exc:
            message = redact_text(str(exc))
            ctx.agent_store.set_plan_status(plan_id, "apply_failed", error=message)
            op = mutation.get("op") if isinstance(mutation, dict) else None
            return {
                "ok": False,
                "status": "apply_failed",
                "error": message,
                "failed_step": {"index": index, "op": op},
            }
    ctx.agent_store.set_plan_status(plan_id, "applied")
    return {"ok": True, "status": "applied"}


def _tool_get_task(ctx: AgentToolContext, arguments: dict) -> dict:
    task_id = arguments.get("task_id") or ctx.bound_task_id
    if not task_id:
        return {"ok": False, "error": "task_id is required"}
    state = ctx.task_store.get_state(str(task_id))
    if state is None:
        return {"ok": False, "error": "task not found"}
    replay = ctx.task_store.get_replay(str(task_id))
    params = replay.get("params") if isinstance(replay, dict) else None
    result, params = _cap_result_params(state.get("result"), params)
    return {
        "ok": True,
        "id": state.get("id") or task_id,
        "kind": state.get("kind"),
        "title": state.get("title"),
        "profile": state.get("profile"),
        "status": _status_value(state.get("status")),
        "result": result,
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "completed_at": state.get("completed_at"),
        "retry_path": state.get("retry_path"),
        "has_replay": bool(replay),
        "params": params,
    }


def _tool_list_failed_tasks(ctx: AgentToolContext, arguments: dict) -> dict:
    kind = arguments.get("kind") or None
    profile = arguments.get("profile") or None
    limit = _int_arg(arguments.get("limit"), default=20, lo=1, hi=50)
    rows = ctx.task_store.list_failed(
        limit=limit,
        kind=kind,
        profile=profile,
    )
    tasks = []
    for row in rows:
        item = dict(row)
        item.pop("logs", None)
        item.pop("params", None)
        item.pop("replay", None)
        item["status"] = _status_value(item.get("status"))
        tasks.append(redact_obj(_drop_secret_keys(item)))
    return {"ok": True, "tasks": tasks}


def _tool_get_task_log(ctx: AgentToolContext, arguments: dict) -> dict:
    task_id = arguments.get("task_id") or ctx.bound_task_id
    if not task_id:
        return {"ok": False, "error": "task_id is required"}
    if ctx.task_store.get_state(str(task_id)) is None:
        return {"ok": False, "error": "task not found"}
    tail = _int_arg(arguments.get("tail"), default=_LOG_LINE_TOTAL, lo=1, hi=_LOG_LINE_TOTAL)
    entries = ctx.task_store.get_logs_after(str(task_id), 0)
    selected = _select_log_lines(entries, tail=tail)
    lines = [
        {"seq": entry.get("seq"), "message": redact_text(entry.get("message", ""))}
        for entry in selected
    ]
    return _cap_log_payload({"ok": True, "task_id": str(task_id), "lines": lines})


def _tool_get_profile_context(ctx: AgentToolContext, arguments: dict) -> dict:
    profile = arguments.get("profile") or None
    if not profile and ctx.bound_task_id:
        state = ctx.task_store.get_state(str(ctx.bound_task_id))
        if state:
            profile = state.get("profile")
    csv_path = None
    screenshots_path = None
    iap_path = None
    if profile:
        try:
            cfg = Config(app_name=str(profile))
            csv_path = cfg.csv_path
            screenshots_path = cfg.screenshots_path
            iap_path = cfg.iap_path or "data/iap_packages.json"
        except Exception:
            pass
    if ctx.bound_task_id:
        replay = ctx.task_store.get_replay(str(ctx.bound_task_id))
        if isinstance(replay, dict):
            params = replay.get("params") or {}
            csv_path = csv_path or params.get("csv_path")
            screenshots_path = screenshots_path or params.get("screenshots_dir")
            iap_path = iap_path or params.get("iap_file")
    defaults, build = _load_local_defaults_build(ctx.project_root)
    payload = {
        "ok": True,
        "name": profile or "",
        "csv_path": csv_path,
        "screenshots_path": screenshots_path,
        "iap_path": iap_path,
        "defaults": defaults,
        "build": build,
    }
    return redact_obj(_drop_secret_keys(payload))


def _tool_inspect_local(ctx: AgentToolContext, arguments: dict) -> dict:
    raw_path = arguments.get("path")
    if not raw_path:
        return {"ok": False, "error": "path is required"}
    max_bytes = _int_arg(
        arguments.get("max_bytes"),
        default=_INSPECT_MAX_BYTES,
        lo=1,
        hi=_INSPECT_MAX_BYTES,
    )
    try:
        resolved = _resolve_user_path(ctx.project_root, raw_path)
    except Exception:
        return {"ok": False, "error": "path is not on the allow-list"}
    if _is_forbidden_path(resolved) or not _is_allowed_path(ctx, resolved):
        return {"ok": False, "error": "path is not on the allow-list"}
    if not resolved.exists():
        return {"ok": False, "error": "path not found"}
    if resolved.is_dir():
        return _list_directory(resolved)
    if resolved.suffix.lower() in _IMAGE_SUFFIXES:
        return _binary_meta(resolved)
    try:
        size = resolved.stat().st_size
        data = resolved.read_bytes()[:max_bytes]
    except OSError as exc:
        return {"ok": False, "error": redact_text(str(exc))}
    if b"\0" in data:
        return _binary_meta(resolved)
    text = data.decode("utf-8", errors="replace")
    if resolved.name.lower() == "config.toml":
        text = _strip_credentials_toml(text)
    return {
        "ok": True,
        "path": str(resolved),
        "content": redact_text(text),
        "truncated": size > max_bytes,
    }


def _tool_propose_fix(ctx: AgentToolContext, arguments: dict) -> dict:
    if not ctx.session_id:
        return {"ok": False, "error": "session_id is required"}
    if ctx.agent_store is None:
        return {"ok": False, "error": "agent store is required"}
    summary = arguments.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return {"ok": False, "error": "summary is required"}
    mutations = arguments.get("mutations") if "mutations" in arguments else []
    if mutations is None:
        mutations = []
    if not isinstance(mutations, list):
        return {"ok": False, "error": "mutations must be a list"}
    manual_steps = arguments.get("manual_steps") if "manual_steps" in arguments else []
    if manual_steps is None:
        manual_steps = []
    if not isinstance(manual_steps, list):
        return {"ok": False, "error": "manual_steps must be a list"}
    rerun = arguments.get("rerun")
    if not mutations and not [step for step in manual_steps if str(step).strip()]:
        return {"ok": False, "error": "mutations or manual_steps required"}
    if rerun is not None:
        if not mutations:
            return {"ok": False, "error": "rerun is illegal when mutations is empty"}
        if not isinstance(rerun, dict) or not rerun.get("task_id") or not rerun.get("kind"):
            return {"ok": False, "error": "rerun must include task_id and kind"}
    for mutation in mutations:
        error = _validate_mutation(ctx, mutation)
        if error:
            return {"ok": False, "error": error}
    plan_id = ctx.agent_store.insert_plan_draft(
        ctx.session_id,
        ctx.turn_seq,
        summary.strip(),
        mutations,
        rerun if isinstance(rerun, dict) else None,
        [str(step) for step in manual_steps],
    )
    return {"ok": True, "plan_id": plan_id, "status": "draft"}


_HANDLERS: dict[str, Callable[[AgentToolContext, dict], dict]] = {
    "get_task": _tool_get_task,
    "list_failed_tasks": _tool_list_failed_tasks,
    "get_task_log": _tool_get_task_log,
    "get_profile_context": _tool_get_profile_context,
    "inspect_local": _tool_inspect_local,
    "propose_fix": _tool_propose_fix,
}


def _status_value(status: Any) -> str:
    if status is None:
        return ""
    value = getattr(status, "value", status)
    return str(value)


def _int_arg(value: Any, *, default: int, lo: int, hi: int) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(number, hi))


def _drop_secret_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_secret_keys(item)
            for key, item in value.items()
            if str(key).lower() not in _SECRET_KEYS
        }
    if isinstance(value, list):
        return [_drop_secret_keys(item) for item in value]
    return value


def _cap_result_params(result: Any, params: Any) -> tuple[Any, Any]:
    result = redact_obj(_drop_secret_keys(result))
    params = redact_obj(_drop_secret_keys(params))
    result_s = json.dumps(result, ensure_ascii=False, default=str)
    params_s = json.dumps(params, ensure_ascii=False, default=str)
    if len(result_s) + len(params_s) <= _RESULT_PARAMS_MAX:
        return result, params
    half = _RESULT_PARAMS_MAX // 2
    if len(result_s) > half:
        result = redact_obj(result, max_chars=half)
        result_s = json.dumps(result, ensure_ascii=False, default=str)
    rest = max(0, _RESULT_PARAMS_MAX - len(result_s))
    if len(params_s) > rest:
        params = redact_obj(params, max_chars=rest)
    return result, params


def _is_error_line(message: str) -> bool:
    text = message if isinstance(message, str) else str(message)
    return bool(_ERROR_LINE_RE.search(text) or "traceback" in text.lower())


def _select_log_lines(entries: list[dict], *, tail: int) -> list[dict]:
    errors = [entry for entry in entries if _is_error_line(str(entry.get("message", "")))]
    if len(errors) > _LOG_ERROR_CAP:
        errors = errors[-_LOG_ERROR_CAP:]
    tail_n = max(0, min(int(tail), _LOG_LINE_TOTAL))
    tail_entries = entries[-tail_n:] if tail_n else []
    selected: list[dict] = []
    seen: set[Any] = set()
    for entry in errors:
        key = entry.get("seq")
        if key in seen:
            continue
        seen.add(key)
        selected.append(entry)
        if len(selected) >= _LOG_LINE_TOTAL:
            break
    if len(selected) < _LOG_LINE_TOTAL:
        for entry in reversed(tail_entries):
            key = entry.get("seq")
            if key in seen:
                continue
            seen.add(key)
            selected.append(entry)
            if len(selected) >= _LOG_LINE_TOTAL:
                break
    selected.sort(key=lambda item: int(item.get("seq") or 0))
    return selected


def _cap_log_payload(payload: dict) -> dict:
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if len(encoded) <= _LOG_PAYLOAD_MAX:
        return payload
    lines = list(payload.get("lines") or [])
    while lines and len(json.dumps({**payload, "lines": lines}, ensure_ascii=False, default=str)) > _LOG_PAYLOAD_MAX:
        lines.pop(0)
    capped = dict(payload)
    capped["lines"] = lines
    capped["truncated"] = True
    return capped


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return data if isinstance(data, dict) else {}


def _load_local_defaults_build(project_root: Path) -> tuple[dict, dict]:
    path = Path(project_root) / ".asc" / "config.toml"
    if not path.is_file():
        return {}, {}
    try:
        data = _read_toml(path)
    except Exception:
        return {}, {}
    defaults = dict(data.get("defaults") or {})
    build = dict(data.get("build") or {})
    return _drop_secret_keys(defaults), _drop_secret_keys(build)


def _strip_credentials_toml(text: str) -> str:
    try:
        data = tomllib.loads(text)
    except Exception:
        return _CREDENTIALS_SECTION_RE.sub("", text)
    if not isinstance(data, dict):
        return text
    data.pop("credentials", None)
    return toml.dumps(_drop_secret_keys(data))


def _resolve_user_path(project_root: Path, value: str | Path) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = Path(project_root) / path
    return path.resolve()


def _home_asc() -> Path:
    return (Path.home() / ".config" / "asc").resolve()


def _is_forbidden_path(path: Path) -> bool:
    if path.suffix.lower() == ".p8":
        return True
    if path.name.lower() in {"llm.toml", "guard.json"}:
        return True
    if path.suffix.lower() == ".toml" and path.parent.name.lower() == "profiles":
        return True
    home_asc = _home_asc()
    for root in (home_asc / "keys", home_asc / "profiles"):
        try:
            _assert_under_root(root, path)
            return True
        except (PathTraversalError, OSError, ValueError):
            continue
    return False


def _allow_roots(ctx: AgentToolContext) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if not value:
            return
        try:
            resolved = _resolve_user_path(ctx.project_root, value)
        except Exception:
            return
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        roots.append(resolved)

    add(ctx.project_root / ".asc" / "config.toml")
    for name in _BUILD_LOG_NAMES:
        add(ctx.project_root / "build" / name)

    profile = None
    replay = None
    if ctx.bound_task_id:
        state = ctx.task_store.get_state(str(ctx.bound_task_id))
        if state:
            profile = state.get("profile")
        replay = ctx.task_store.get_replay(str(ctx.bound_task_id))

    if profile:
        try:
            cfg = Config(app_name=str(profile))
            add(cfg.csv_path)
            add(cfg.screenshots_path)
            add(cfg.iap_path or "data/iap_packages.json")
            output = cfg.get("output", default=None, section="build")
            if output:
                out_dir = _resolve_user_path(ctx.project_root, output)
                for name in _BUILD_LOG_NAMES:
                    add(out_dir / name)
        except Exception:
            pass

    _defaults, build = _load_local_defaults_build(ctx.project_root)
    local_output = build.get("output")
    if local_output:
        out_dir = _resolve_user_path(ctx.project_root, local_output)
        for name in _BUILD_LOG_NAMES:
            add(out_dir / name)

    if isinstance(replay, dict):
        params = replay.get("params") or {}
        add(params.get("csv_path"))
        add(params.get("screenshots_dir"))
        add(params.get("iap_file"))
        add(params.get("source_file"))

    return roots


def _is_allowed_path(ctx: AgentToolContext, resolved: Path) -> bool:
    for root in _allow_roots(ctx):
        try:
            _assert_under_root(root, resolved)
            return True
        except (PathTraversalError, OSError, ValueError):
            continue
    return False


def _list_directory(path: Path) -> dict:
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        return {"ok": False, "error": redact_text(str(exc))}
    entries = []
    for child in children[:_DIR_LIST_CAP]:
        item: dict[str, Any] = {"name": child.name}
        try:
            stat = child.stat()
            item["size"] = stat.st_size
            item["mtime"] = stat.st_mtime
            item["directory"] = child.is_dir()
        except OSError:
            pass
        entries.append(item)
    return {
        "ok": True,
        "directory": True,
        "path": str(path),
        "entries": entries,
    }


def _binary_meta(path: Path) -> dict:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        "ok": True,
        "binary": True,
        "size": size,
        "suffix": path.suffix.lower(),
    }


def _validate_mutation(ctx: AgentToolContext, mutation: Any) -> str | None:
    if not isinstance(mutation, dict):
        return "invalid mutation"
    op = mutation.get("op")
    if op not in _ALLOWED_MUTATION_OPS:
        return f"unsupported op: {op!r}"
    resolved, error = _resolve_mutation_path(ctx, mutation.get("path"))
    if error:
        return error
    assert resolved is not None
    if op == "csv_set_fields":
        return _validate_csv_set_fields(ctx, mutation, resolved)
    if op == "json_patch":
        return _validate_json_patch(ctx, mutation, resolved)
    if op == "toml_set":
        return _validate_toml_set(ctx, mutation, resolved)
    if op == "text_replace":
        return _validate_text_replace(ctx, mutation, resolved)
    return _validate_screenshot_fs(ctx, mutation, resolved)


def _resolve_mutation_path(ctx: AgentToolContext, raw_path: Any) -> tuple[Path | None, str | None]:
    if not raw_path:
        return None, "path is required"
    try:
        resolved = _resolve_user_path(ctx.project_root, raw_path)
    except Exception:
        return None, "path is not on the allow-list"
    if _is_forbidden_path(resolved) or not _is_allowed_path(ctx, resolved):
        return None, "path is not on the allow-list"
    return resolved, None


def _bound_replay_params(ctx: AgentToolContext) -> dict[str, Any]:
    if not ctx.bound_task_id:
        return {}
    replay = ctx.task_store.get_replay(str(ctx.bound_task_id))
    if not isinstance(replay, dict):
        return {}
    params = replay.get("params")
    return params if isinstance(params, dict) else {}


def _bound_profile_paths(ctx: AgentToolContext) -> tuple[Any, Any, Any]:
    csv_path = None
    screenshots_path = None
    iap_path = None
    profile = None
    if ctx.bound_task_id:
        state = ctx.task_store.get_state(str(ctx.bound_task_id))
        if state:
            profile = state.get("profile")
    if profile:
        try:
            cfg = Config(app_name=str(profile))
            csv_path = cfg.csv_path
            screenshots_path = cfg.screenshots_path
            iap_path = cfg.iap_path or "data/iap_packages.json"
        except Exception:
            pass
    return csv_path, screenshots_path, iap_path


def _candidate_paths(ctx: AgentToolContext, *values: Any) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        try:
            resolved = _resolve_user_path(ctx.project_root, value)
        except Exception:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _path_matches_any(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            _assert_under_root(root, path)
            return True
        except (PathTraversalError, OSError, ValueError):
            continue
    return False


def _validate_csv_set_fields(ctx: AgentToolContext, mutation: dict, resolved: Path) -> str | None:
    locale = mutation.get("locale")
    if not locale or not str(locale).strip():
        return "locale is required"
    fields = mutation.get("fields")
    if not isinstance(fields, dict) or not fields:
        return "fields is required"
    unknown = [name for name in fields if name not in _FIELD_NAME_SET]
    if unknown:
        return f"unknown csv field: {unknown[0]}"
    params = _bound_replay_params(ctx)
    cfg_csv, _shots, _iap = _bound_profile_paths(ctx)
    csv_roots = _candidate_paths(ctx, params.get("csv_path"), cfg_csv)
    if not csv_roots or not _path_matches_any(resolved, csv_roots):
        return "path must be the profile CSV"
    return None


def _validate_json_patch(ctx: AgentToolContext, mutation: dict, resolved: Path) -> str | None:
    params = _bound_replay_params(ctx)
    _csv, _shots, cfg_iap = _bound_profile_paths(ctx)
    iap_roots = _candidate_paths(ctx, params.get("iap_file"), cfg_iap)
    if not iap_roots or not _path_matches_any(resolved, iap_roots):
        return "path must be the profile IAP JSON"
    patch = mutation.get("patch")
    if not isinstance(patch, list) or not patch:
        return "json_patch requires a patch list"
    for operation in patch:
        if not isinstance(operation, dict):
            return "invalid json_patch operation"
        name = operation.get("op")
        if name not in _JSON_PATCH_OPS:
            return f"json_patch op {name!r} is not allowed"
        pointer = operation.get("path")
        terminal = _json_pointer_terminal(pointer) if isinstance(pointer, str) else None
        if terminal not in _JSON_POINTER_TERMINALS:
            return "json_patch pointer is not allowed"
    return None


def _json_pointer_terminal(pointer: str) -> str | None:
    if not pointer.startswith("/"):
        return None
    parts = pointer.split("/")[1:]
    if not parts:
        return None
    token = parts[-1].replace("~1", "/").replace("~0", "~")
    if token in {"", "-"} or token.isdigit():
        return None
    return token


def _validate_toml_set(ctx: AgentToolContext, mutation: dict, resolved: Path) -> str | None:
    expected = (ctx.project_root / ".asc" / "config.toml").resolve()
    if resolved != expected:
        return "path must be project .asc/config.toml"
    key = mutation.get("key")
    if not isinstance(key, str) or not key.strip():
        return "toml key is required"
    dotted = key.strip()
    if dotted == "credentials" or dotted.startswith("credentials."):
        return "credentials keys are forbidden"
    if dotted not in _TOML_ALLOWED_KEYS:
        return f"toml key {dotted!r} is not allowed"
    if dotted == "build.signing" and mutation.get("value") not in _TOML_SIGNING_VALUES:
        return "build.signing must be auto or manual"
    return None


def _validate_text_replace(ctx: AgentToolContext, mutation: dict, resolved: Path) -> str | None:
    if "before" not in mutation or "after" not in mutation:
        return "text_replace requires before, after, count"
    count = mutation.get("count")
    if type(count) is not int:
        return "text_replace requires before, after, count"
    params = _bound_replay_params(ctx)
    source_file = params.get("source_file")
    if not source_file:
        return "text_replace requires replay source_file"
    sources = _candidate_paths(ctx, source_file)
    if not sources or resolved != sources[0]:
        return "path must equal replay source_file"
    return None


def _validate_screenshot_fs(ctx: AgentToolContext, mutation: dict, resolved: Path) -> str | None:
    action = mutation.get("action")
    if action not in _SCREENSHOT_ACTIONS:
        return "screenshot_fs action must be rename, delete, or reorder"
    params = _bound_replay_params(ctx)
    _csv, cfg_shots, _iap = _bound_profile_paths(ctx)
    shot_roots = _candidate_paths(ctx, params.get("screenshots_dir"), cfg_shots)
    if not shot_roots or not _path_matches_any(resolved, shot_roots):
        return "path must be under screenshots_path"
    return None


def _apply_one_mutation(ctx: AgentToolContext, mutation: Any) -> None:
    error = _validate_mutation(ctx, mutation)
    if error:
        raise _ApplyStepError(error)
    resolved, path_error = _resolve_mutation_path(ctx, mutation.get("path"))
    if path_error or resolved is None:
        raise _ApplyStepError(path_error or "path is required")
    op = mutation.get("op")
    if op == "csv_set_fields":
        _apply_csv_set_fields(mutation, resolved)
    elif op == "json_patch":
        _apply_json_patch(mutation, resolved)
    elif op == "toml_set":
        _apply_toml_set(mutation, resolved)
    elif op == "text_replace":
        _apply_text_replace(mutation, resolved)
    elif op == "screenshot_fs":
        _apply_screenshot_fs(ctx, mutation, resolved)
    else:
        raise _ApplyStepError(f"unsupported op: {op!r}")


def _apply_csv_set_fields(mutation: dict, resolved: Path) -> None:
    mtime = resolved.stat().st_mtime if resolved.exists() else None
    snapshot = load_local_text_snapshot(str(resolved))
    locale = str(mutation.get("locale") or "").strip()
    listing = next((item for item in snapshot.locales if item.locale == locale), None)
    if listing is None:
        raise _ApplyStepError(f"locale {locale!r} not found")
    before = mutation.get("before")
    if isinstance(before, dict):
        for field, expected in before.items():
            current = listing.fields.get(field, "")
            if str(current) != str(expected):
                raise _ApplyStepError("before mismatch")
    fields = mutation.get("fields") or {}
    for field, value in fields.items():
        listing.fields[field] = "" if value is None else str(value)
    try:
        save_local_csv(str(resolved), snapshot.locales, expected_mtime=mtime)
    except FileChangedError as exc:
        raise _ApplyStepError(str(exc)) from exc


def _apply_json_patch(mutation: dict, resolved: Path) -> None:
    patch = mutation.get("patch")
    if not isinstance(patch, list):
        raise _ApplyStepError("json_patch requires a patch list")
    try:
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _ApplyStepError(str(exc)) from exc
    _apply_rfc6902(document, patch)
    resolved.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _json_pointer_tokens(pointer: str) -> list[str]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise _ApplyStepError("invalid json pointer")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]


def _json_is_index(token: str) -> bool:
    return token.isdigit() and (token == "0" or not token.startswith("0"))


def _json_child(node: Any, token: str) -> Any:
    if isinstance(node, list):
        if not _json_is_index(token):
            raise _ApplyStepError("invalid array index")
        index = int(token)
        if index < 0 or index >= len(node):
            raise _ApplyStepError("json pointer not found")
        return node[index]
    if isinstance(node, dict):
        if token not in node:
            raise _ApplyStepError("json pointer not found")
        return node[token]
    raise _ApplyStepError("json pointer not found")


def _json_parent_and_token(document: Any, tokens: list[str]) -> tuple[Any, str]:
    if not tokens:
        raise _ApplyStepError("json patch cannot target the document root")
    current = document
    for token in tokens[:-1]:
        current = _json_child(current, token)
    return current, tokens[-1]


def _json_add(parent: Any, token: str, value: Any) -> None:
    if isinstance(parent, list):
        if token == "-":
            parent.append(value)
            return
        if not _json_is_index(token):
            raise _ApplyStepError("invalid array index")
        index = int(token)
        if index < 0 or index > len(parent):
            raise _ApplyStepError("invalid array index")
        parent.insert(index, value)
        return
    if isinstance(parent, dict):
        parent[token] = value
        return
    raise _ApplyStepError("json patch add failed")


def _json_remove(parent: Any, token: str) -> None:
    if isinstance(parent, list):
        if not _json_is_index(token):
            raise _ApplyStepError("invalid array index")
        index = int(token)
        if index < 0 or index >= len(parent):
            raise _ApplyStepError("json pointer not found")
        parent.pop(index)
        return
    if isinstance(parent, dict):
        if token not in parent:
            raise _ApplyStepError("json pointer not found")
        del parent[token]
        return
    raise _ApplyStepError("json patch remove failed")


def _json_replace(parent: Any, token: str, value: Any) -> None:
    if isinstance(parent, list):
        if not _json_is_index(token):
            raise _ApplyStepError("invalid array index")
        index = int(token)
        if index < 0 or index >= len(parent):
            raise _ApplyStepError("json pointer not found")
        parent[index] = value
        return
    if isinstance(parent, dict):
        if token not in parent:
            raise _ApplyStepError("json pointer not found")
        parent[token] = value
        return
    raise _ApplyStepError("json patch replace failed")


def _apply_rfc6902(document: Any, operations: list) -> None:
    for operation in operations:
        if not isinstance(operation, dict):
            raise _ApplyStepError("invalid json_patch operation")
        name = operation.get("op")
        if name not in _JSON_PATCH_OPS:
            raise _ApplyStepError(f"json_patch op {name!r} is not allowed")
        pointer = operation.get("path")
        terminal = _json_pointer_terminal(pointer) if isinstance(pointer, str) else None
        if terminal not in _JSON_POINTER_TERMINALS:
            raise _ApplyStepError("json_patch pointer is not allowed")
        parent, token = _json_parent_and_token(document, _json_pointer_tokens(pointer))
        if name == "add":
            _json_add(parent, token, operation.get("value"))
        elif name == "remove":
            _json_remove(parent, token)
        else:
            _json_replace(parent, token, operation.get("value"))


def _extract_credentials_section(text: str) -> str:
    match = _CREDENTIALS_BLOCK_RE.search(text)
    return match.group(0) if match else ""


def _apply_toml_set(mutation: dict, resolved: Path) -> None:
    original = resolved.read_text(encoding="utf-8") if resolved.is_file() else ""
    try:
        data = tomllib.loads(original) if original else {}
    except Exception as exc:
        raise _ApplyStepError(str(exc)) from exc
    if not isinstance(data, dict):
        raise _ApplyStepError("invalid toml")
    credentials = _extract_credentials_section(original)
    data.pop("credentials", None)
    dotted = str(mutation.get("key") or "").strip()
    section, _, name = dotted.partition(".")
    nested = data.get(section)
    if not isinstance(nested, dict):
        nested = {}
        data[section] = nested
    nested[name] = mutation.get("value")
    data.pop("credentials", None)
    text = toml.dumps(data)
    if not text.endswith("\n"):
        text += "\n"
    if credentials:
        text = text.rstrip("\n") + "\n\n" + credentials.strip() + "\n"
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(text, encoding="utf-8")


def _apply_text_replace(mutation: dict, resolved: Path) -> None:
    before = mutation.get("before")
    after = mutation.get("after")
    count = mutation.get("count")
    if not isinstance(before, str) or not isinstance(after, str) or type(count) is not int:
        raise _ApplyStepError("text_replace requires before, after, count")
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise _ApplyStepError(str(exc)) from exc
    if text.count(before) != count:
        raise _ApplyStepError("text_replace count mismatch")
    resolved.write_text(text.replace(before, after, count), encoding="utf-8")


def _screenshots_root(ctx: AgentToolContext) -> Path | None:
    params = _bound_replay_params(ctx)
    _csv, cfg_shots, _iap = _bound_profile_paths(ctx)
    roots = _candidate_paths(ctx, params.get("screenshots_dir"), cfg_shots)
    return roots[0] if roots else None


def _apply_screenshot_fs(ctx: AgentToolContext, mutation: dict, resolved: Path) -> None:
    root = _screenshots_root(ctx)
    if root is None:
        raise _ApplyStepError("screenshots root is required")
    try:
        _assert_under_root(root, resolved)
    except PathTraversalError as exc:
        raise _ApplyStepError(str(exc)) from exc
    action = mutation.get("action")
    try:
        if action == "rename":
            new_name = mutation.get("new_name")
            if not isinstance(new_name, str) or not new_name.strip():
                raise _ApplyStepError("screenshot rename requires new_name")
            rename_screenshot(resolved, new_name, root=root)
            return
        if action == "delete":
            _assert_under_root(root, resolved)
            delete_screenshot(resolved)
            return
        if action == "reorder":
            file_names = mutation.get("file_names") or mutation.get("ordered_file_names")
            display_type = mutation.get("display_type") or ""
            if not isinstance(file_names, list) or not all(
                isinstance(name, str) for name in file_names
            ):
                raise _ApplyStepError("screenshot reorder requires file_names")
            locale_dir = resolved if resolved.is_dir() else resolved.parent
            _assert_under_root(root, locale_dir)
            apply_screenshot_order(locale_dir, str(display_type), file_names, root=root)
            return
    except PathTraversalError as exc:
        raise _ApplyStepError(str(exc)) from exc
    raise _ApplyStepError("screenshot_fs action must be rename, delete, or reorder")

