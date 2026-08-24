"""Workspace file tools for the web Agent. Writes stay gated as plan drafts."""
from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from asc.listing.local import PathTraversalError, _assert_under_root
from asc.web.agent_redact import redact_text

_CREDENTIALS_SECTION_RE = re.compile(r"(?is)^\[credentials\][^\[]*")

_GREP_TIMEOUT_SEC = 8.0
_GREP_MAX_FILES = 400
_GREP_MAX_HITS = 80
_GREP_MAX_FILE_BYTES = 1_000_000
_GREP_LINE_MAX = 240
_READ_DEFAULT_LIMIT = 200
_READ_MAX_LIMIT = 400
_READ_MAX_BYTES = 256 * 1024
_WRITE_MAX_CHARS = 200_000
_RESULT_HITS_MAX = 80

_IGNORE_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".git",
        "dist",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".eggs",
        "egg-info",
        ".idea",
        ".cursor",
    }
)
_SECRET_NAMES = frozenset(
    {
        ".env",
        "guard.json",
        "llm.toml",
        "credentials",
        "credentials.json",
        "credentials.toml",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
    }
)
_SECRET_SUFFIXES = frozenset({".p8", ".pem", ".key"})
_SECRET_DIR_NAMES = frozenset(
    {"keys", ".git", ".ssh", ".gnupg", ".aws", ".kube"}
)
_HOME_BROAD_CHILDREN = frozenset(
    {"library", "applications", ".ssh", ".gnupg", ".aws", ".kube"}
)
_BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".heic",
        ".tif",
        ".tiff",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".whl",
        ".pyc",
        ".so",
        ".dylib",
        ".woff",
        ".woff2",
        ".ttf",
    }
)
FILE_MUTATION_OPS = frozenset({"file_create", "file_replace", "file_delete"})
_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_FORM_PATH_PARAM_KEYS = (
    "csv_path",
    "screenshots_dir",
    "iap_file",
    "source_file",
    "project",
    "ipa_path",
)


class WorkspacePathError(ValueError):
    """Path is outside the workspace or blocked."""


def _home_asc() -> Path:
    return (Path.home() / ".config" / "asc").resolve()


def is_blocked_workspace_path(path: Path, project_root: Path | None = None) -> bool:
    """True for secrets, keys, credentials, and VCS objects."""
    name = path.name.lower()
    if name in _SECRET_NAMES or name.startswith(".env."):
        return True
    if path.suffix.lower() in _SECRET_SUFFIXES:
        return True
    if name in {"llm.toml", "guard.json"}:
        return True
    if path.suffix.lower() == ".toml" and path.parent.name.lower() == "profiles":
        return True
    rel_parts = path.parts
    if project_root is not None:
        try:
            rel_parts = path.resolve().relative_to(Path(project_root).resolve()).parts
        except ValueError:
            rel_parts = path.parts
    parts = {part.lower() for part in rel_parts}
    if parts & _SECRET_DIR_NAMES:
        return True
    if "credential" in name:
        return True
    home_asc = _home_asc()
    for root in (home_asc / "keys", home_asc / "profiles"):
        try:
            _assert_under_root(root, path)
            return True
        except (PathTraversalError, OSError, ValueError):
            continue
    return False


def _has_dotdot(raw: str) -> bool:
    try:
        parts = Path(raw).parts
    except Exception:
        return True
    return ".." in parts


def _looks_like_url(value: str) -> bool:
    return bool(_URL_RE.match(value.strip()))


def _too_broad_root(path: Path) -> bool:
    resolved = path.resolve()
    if resolved == resolved.anchor or str(resolved) in {"/", "\\"}:
        return True
    try:
        home = Path.home().resolve()
        if resolved == home:
            return True
        if (
            resolved.parent == home
            and resolved.name.lower() in _HOME_BROAD_CHILDREN
        ):
            return True
    except OSError:
        pass
    try:
        if resolved == Path(tempfile.gettempdir()).resolve():
            return True
    except OSError:
        pass
    return False


def _form_path_scope_roots(project_root: Path) -> list[Path]:
    roots = [Path(project_root).resolve()]
    for extra in (Path.home(), Path(tempfile.gettempdir())):
        try:
            roots.append(Path(extra).resolve())
        except OSError:
            continue
    return roots


def _under_any_root(path: Path, roots: list[Path]) -> bool:
    try:
        target = Path(path).resolve()
    except (OSError, ValueError):
        return False
    for root in roots:
        try:
            _assert_under_root(root, target)
            return True
        except (PathTraversalError, OSError, ValueError):
            continue
    return False


def normalize_allowed_roots(
    project_root: Path,
    extra: list[Path] | None = None,
) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(value: Path) -> None:
        try:
            resolved = Path(value).resolve()
        except (OSError, ValueError):
            return
        if _too_broad_root(resolved):
            return
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        roots.append(resolved)

    add(Path(project_root))
    for item in extra or []:
        add(item)
    return roots


def matching_allowed_root(resolved: Path, roots: list[Path]) -> Path | None:
    target = Path(resolved).resolve()
    for root in roots:
        try:
            _assert_under_root(root, target)
            return root
        except (PathTraversalError, OSError, ValueError):
            continue
    return None


def collect_form_allowed_roots(project_root: Path, form_paths: list[Any] | None) -> list[Path]:
    """Turn user-entered form paths into extra sandbox roots (existing dirs)."""
    roots: list[Path] = []
    seen: set[str] = set()
    base = Path(project_root).resolve()
    scopes = _form_path_scope_roots(base)

    def add(value: Path) -> None:
        if not _under_any_root(value, scopes):
            return
        if _too_broad_root(value) or is_blocked_workspace_path(value, base):
            return
        key = str(value)
        if key in seen:
            return
        seen.add(key)
        roots.append(value)

    for raw in form_paths or []:
        text = str(raw or "").strip()
        if not text or _looks_like_url(text) or _has_dotdot(text):
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = base / path
        try:
            resolved = path.resolve()
        except (OSError, ValueError):
            continue
        if not _under_any_root(resolved, scopes):
            continue
        if is_blocked_workspace_path(resolved, base):
            continue
        if resolved.is_dir():
            add(resolved)
            continue
        parent = resolved.parent if resolved.is_file() or resolved.parent.is_dir() else None
        if parent is not None and parent.is_dir():
            parent = parent.resolve()
            if not _too_broad_root(parent) and _under_any_root(parent, scopes):
                add(parent)
                continue
        if resolved.is_file():
            add(resolved)
    return roots


def sanitize_form_paths(project_root: Path, form_paths: list[Any] | None) -> list[str]:
    """Keep only client paths that can become extra sandbox roots."""
    kept: list[str] = []
    seen: set[str] = set()
    for raw in form_paths or []:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        if collect_form_allowed_roots(project_root, [text]):
            seen.add(text)
            kept.append(text)
    return kept


def resolve_workspace_path(
    project_root: Path,
    raw: str | Path,
    *,
    allow_root: bool = False,
    allowed_roots: list[Path] | None = None,
) -> Path:
    """Resolve a user path under project_root or extra form roots."""
    text = str(raw or "").strip()
    if not text:
        raise WorkspacePathError("path is required")
    if _has_dotdot(text):
        raise WorkspacePathError("path escapes the workspace")
    roots = normalize_allowed_roots(project_root, allowed_roots)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = Path(project_root).resolve() / path
    try:
        resolved = path.resolve()
    except (OSError, ValueError) as exc:
        raise WorkspacePathError("path escapes the workspace") from exc
    matching = matching_allowed_root(resolved, roots)
    if matching is None:
        raise WorkspacePathError("path escapes the workspace")
    if not allow_root and resolved in {root.resolve() for root in roots}:
        if not resolved.is_file():
            raise WorkspacePathError("cannot target the project root")
    if is_blocked_workspace_path(resolved, matching):
        raise WorkspacePathError("path is forbidden")
    return resolved


def rel_workspace_path(
    project_root: Path,
    resolved: Path,
    allowed_roots: list[Path] | None = None,
) -> str:
    target = Path(resolved).resolve()
    base = Path(project_root).resolve()
    try:
        return target.relative_to(base).as_posix()
    except ValueError:
        return str(target)


def _should_skip_dir(root: Path, directory: Path) -> bool:
    if directory.name in _IGNORE_DIR_NAMES or directory.name.endswith(".egg-info"):
        return True
    try:
        rel_parts = directory.resolve().relative_to(root).parts
    except ValueError:
        return True
    for index, part in enumerate(rel_parts):
        if part in _IGNORE_DIR_NAMES:
            return True
        if part == "spa" and index > 0 and rel_parts[index - 1] == "static":
            return True
    return False


def _is_binary_sample(data: bytes) -> bool:
    return b"\0" in data


def _compile_pattern(pattern: str, *, literal: bool) -> re.Pattern[str] | str:
    if not pattern:
        raise ValueError("pattern is required")
    if literal:
        return re.compile(re.escape(pattern))
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regex: {exc}") from exc


def tool_grep(
    project_root: Path,
    arguments: dict[str, Any],
    *,
    allowed_roots: list[Path] | None = None,
) -> dict[str, Any]:
    pattern = arguments.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return {"ok": False, "error": "pattern is required"}
    literal = bool(arguments.get("literal"))
    try:
        compiled = _compile_pattern(pattern, literal=literal)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    raw_path = arguments.get("path") or "."
    try:
        start = resolve_workspace_path(
            project_root, raw_path, allow_root=True, allowed_roots=allowed_roots
        )
    except WorkspacePathError as exc:
        return {"ok": False, "error": str(exc)}
    if is_blocked_workspace_path(start, matching_allowed_root(start, normalize_allowed_roots(project_root, allowed_roots))):
        return {"ok": False, "error": "path is forbidden"}
    if start.is_file() and start.suffix.lower() in _BINARY_SUFFIXES:
        return {"ok": True, "hits": [], "truncated": False, "summary": "0 hits"}

    deadline = time.monotonic() + _GREP_TIMEOUT_SEC
    hits: list[dict[str, Any]] = []
    files_scanned = 0
    truncated = False
    roots = normalize_allowed_roots(project_root, allowed_roots)
    root = Path(project_root).resolve()

    def add_hit(path: Path, line_no: int, text: str) -> None:
        hits.append(
            {
                "path": rel_workspace_path(root, path, allowed_roots=roots),
                "line": line_no,
                "text": redact_text(text[:_GREP_LINE_MAX]),
            }
        )

    def search_file(path: Path) -> bool:
        nonlocal files_scanned, truncated
        if time.monotonic() > deadline:
            truncated = True
            return True
        matching = matching_allowed_root(path, roots) or root
        if is_blocked_workspace_path(path, matching):
            return False
        if path.suffix.lower() in _BINARY_SUFFIXES:
            return False
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size > _GREP_MAX_FILE_BYTES:
            return False
        files_scanned += 1
        if files_scanned > _GREP_MAX_FILES:
            truncated = True
            return True
        try:
            data = path.read_bytes()
        except OSError:
            return False
        if _is_binary_sample(data[:8192]):
            return False
        text = data.decode("utf-8", errors="replace")
        for index, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line):
                add_hit(path, index, line)
                if len(hits) >= _GREP_MAX_HITS:
                    truncated = True
                    return True
        return False

    if start.is_file():
        search_file(start)
    elif start.is_dir():
        for dirpath, dirnames, filenames in os.walk(start):
            if time.monotonic() > deadline or len(hits) >= _GREP_MAX_HITS:
                truncated = True
                break
            current = Path(dirpath)
            skip_root = matching_allowed_root(current, roots) or root
            dirnames[:] = sorted(
                name
                for name in dirnames
                if not _should_skip_dir(skip_root, current / name)
            )
            for name in sorted(filenames):
                if search_file(current / name):
                    break
            if truncated:
                break
    else:
        return {"ok": False, "error": "path not found"}

    hits = hits[:_RESULT_HITS_MAX]
    files = {item["path"] for item in hits}
    summary = f"{len(hits)} hits in {len(files)} file" + ("" if len(files) == 1 else "s")
    return {
        "ok": True,
        "hits": hits,
        "truncated": truncated,
        "files_scanned": files_scanned,
        "summary": summary,
    }


def tool_read_file(
    project_root: Path,
    arguments: dict[str, Any],
    *,
    allowed_roots: list[Path] | None = None,
) -> dict[str, Any]:
    raw_path = arguments.get("path")
    if not raw_path:
        return {"ok": False, "error": "path is required"}
    try:
        resolved = resolve_workspace_path(
            project_root, raw_path, allow_root=False, allowed_roots=allowed_roots
        )
    except WorkspacePathError as exc:
        return {"ok": False, "error": str(exc)}
    if not resolved.exists():
        return {"ok": False, "error": "path not found"}
    if resolved.is_dir():
        return {"ok": False, "error": "path is a directory"}
    if resolved.suffix.lower() in _BINARY_SUFFIXES:
        return {"ok": False, "error": "binary file"}
    offset = _int_arg(arguments.get("offset"), default=1, lo=1, hi=1_000_000)
    limit = _int_arg(
        arguments.get("limit"),
        default=_READ_DEFAULT_LIMIT,
        lo=1,
        hi=_READ_MAX_LIMIT,
    )
    try:
        size = resolved.stat().st_size
        data = resolved.read_bytes()[:_READ_MAX_BYTES]
    except OSError as exc:
        return {"ok": False, "error": redact_text(str(exc))}
    if _is_binary_sample(data):
        return {"ok": False, "error": "binary file"}
    text = data.decode("utf-8", errors="replace")
    if resolved.name.lower() == "config.toml":
        text = _CREDENTIALS_SECTION_RE.sub("", text)
    lines = text.splitlines()
    start = max(offset - 1, 0)
    window = lines[start : start + limit]
    more_lines = start + limit < len(lines)
    truncated = more_lines or size > _READ_MAX_BYTES
    content = redact_text("\n".join(window))
    rel = rel_workspace_path(project_root, resolved, allowed_roots=allowed_roots)
    summary = f"{rel} lines {offset}-{offset + len(window) - 1}" if window else f"{rel} empty"
    return {
        "ok": True,
        "path": rel,
        "content": content,
        "offset": offset,
        "limit": limit,
        "truncated": truncated,
        "summary": summary,
    }


def build_file_mutation(
    op: str,
    project_root: Path,
    arguments: dict[str, Any],
    *,
    allowed_roots: list[Path] | None = None,
) -> tuple[dict | None, str | None]:
    raw_path = arguments.get("path")
    try:
        resolved = resolve_workspace_path(
            project_root, raw_path, allow_root=False, allowed_roots=allowed_roots
        )
    except WorkspacePathError as exc:
        return None, str(exc)
    rel = rel_workspace_path(project_root, resolved, allowed_roots=allowed_roots)
    roots = normalize_allowed_roots(project_root, allowed_roots)
    if op == "file_delete":
        if resolved in roots and resolved.is_dir():
            return None, "cannot delete the project root"
        if resolved.exists() and resolved.is_dir():
            return None, "cannot delete a directory"
        return {"op": op, "path": rel}, None
    content = arguments.get("content")
    if not isinstance(content, str):
        return None, "content is required"
    if len(content) > _WRITE_MAX_CHARS:
        return None, "content is too large"
    if op == "file_create" and resolved.exists():
        return None, "file already exists"
    return {"op": op, "path": rel, "content": content}, None


def file_mutation_summary(op: str, path: str) -> str:
    if op == "file_create":
        return f"将创建 {path}"
    if op == "file_delete":
        return f"将删除 {path}"
    return f"将写入 {path}"


def validate_file_mutation(
    project_root: Path,
    mutation: dict[str, Any],
    *,
    allowed_roots: list[Path] | None = None,
) -> str | None:
    op = mutation.get("op")
    if op not in FILE_MUTATION_OPS:
        return f"unsupported op: {op!r}"
    built, error = build_file_mutation(
        op, project_root, mutation, allowed_roots=allowed_roots
    )
    if error:
        return error
    if built is None:
        return "invalid mutation"
    return None


def apply_file_mutation(
    project_root: Path,
    mutation: dict[str, Any],
    *,
    allowed_roots: list[Path] | None = None,
) -> None:
    error = validate_file_mutation(
        project_root, mutation, allowed_roots=allowed_roots
    )
    if error:
        raise ValueError(error)
    resolved = resolve_workspace_path(
        project_root, mutation.get("path"), allow_root=False, allowed_roots=allowed_roots
    )
    op = mutation.get("op")
    if op == "file_delete":
        if not resolved.is_file():
            raise ValueError("file not found")
        resolved.unlink()
        return
    content = mutation.get("content")
    if not isinstance(content, str):
        raise ValueError("content is required")
    if op == "file_create" and resolved.exists():
        raise ValueError("file already exists")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    roots = normalize_allowed_roots(project_root, allowed_roots)
    matching = matching_allowed_root(resolved, roots)
    if matching is None:
        raise ValueError("path escapes the workspace")
    try:
        _assert_under_root(matching, resolved.parent)
        _assert_under_root(matching, resolved)
    except PathTraversalError as exc:
        raise ValueError("path escapes the workspace") from exc
    resolved.write_text(content, encoding="utf-8")


def _int_arg(value: Any, *, default: int, lo: int, hi: int) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(number, hi))
