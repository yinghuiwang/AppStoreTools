"""Model-visible Agent tools (read + propose_fix). Writes stay gated."""
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
from asc.listing.local import PathTraversalError, _assert_under_root
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
    return {"ok": False, "error": "not implemented"}


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
