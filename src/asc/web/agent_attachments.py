"""Normalize Agent chat attachments and expose them to the model/tools."""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

from asc.web.agent_redact import redact_text
from asc.web.agent_workspace import (
    _has_dotdot,
    _looks_like_url,
    _too_broad_root,
    is_blocked_workspace_path,
)

MAX_ATTACHMENTS = 8
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_EXCERPT_CHARS = 8 * 1024
INBOX_DIRNAME = "agent-inbox"
ATTACH_MARKER = "[attachments]"

ALLOWED_SUFFIXES = frozenset(
    {
        ".txt",
        ".md",
        ".json",
        ".csv",
        ".xml",
        ".html",
        ".htm",
        ".yaml",
        ".yml",
        ".toml",
        ".log",
        ".plist",
        ".strings",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".py",
        ".swift",
        ".sh",
        ".rb",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".css",
        ".scss",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
    }
)
BINARY_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    base = Path(str(name or "").strip()).name or "file"
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._") or "file"
    return cleaned[:80]


def _suffix_ok(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    return suffix in ALLOWED_SUFFIXES


def attachment_form_paths(items: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for item in items:
        path = str(item.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _excerpt_text(text: str, *, truncated: bool = False) -> str:
    cleaned = redact_text(text)
    if len(cleaned) <= MAX_EXCERPT_CHARS and not truncated:
        return cleaned
    return f"{cleaned[:MAX_EXCERPT_CHARS]}\n…(truncated)"


def _resolve_existing_file(project_root: Path, raw: str) -> Path | None:
    text = str(raw or "").strip()
    if not text or _looks_like_url(text) or _has_dotdot(text):
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = Path(project_root).resolve() / path
    try:
        resolved = path.resolve()
    except (OSError, ValueError):
        return None
    if _too_broad_root(resolved) or is_blocked_workspace_path(resolved, Path(project_root)):
        return None
    if not resolved.is_file():
        return None
    if not _suffix_ok(resolved.name):
        return None
    try:
        if resolved.stat().st_size > MAX_FILE_BYTES:
            return None
    except OSError:
        return None
    return resolved


def _decode_inline_bytes(item: dict[str, Any]) -> bytes | None:
    raw_b64 = item.get("content_b64")
    if isinstance(raw_b64, str) and raw_b64.strip():
        try:
            data = base64.b64decode(raw_b64, validate=False)
        except (ValueError, TypeError):
            return None
        return data
    raw_text = item.get("content")
    if isinstance(raw_text, str):
        return raw_text.encode("utf-8")
    return None


def _unique_inbox_path(folder: Path, filename: str) -> Path:
    dest = folder / filename
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    for index in range(2, 20):
        candidate = folder / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return folder / f"{stem}-dup{suffix}"


def normalize_attachments(
    raw: Any,
    *,
    project_root: Path,
    session_id: str,
) -> list[dict[str, Any]]:
    """Keep only safe path/inline attachments and persist browser uploads."""
    if not isinstance(raw, list):
        return []
    root = Path(project_root).resolve()
    sid = _SAFE_NAME_RE.sub("", str(session_id or "").strip()) or "session"
    inbox = root / ".asc" / INBOX_DIRNAME / sid
    out: list[dict[str, Any]] = []
    total = 0
    for item in raw:
        if len(out) >= MAX_ATTACHMENTS:
            break
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or item.get("type") or "path").strip().lower()
        name = _safe_filename(str(item.get("name") or item.get("path") or "file"))
        if is_blocked_workspace_path(Path(name), root) or not _suffix_ok(name):
            continue
        if kind == "inline":
            data = _decode_inline_bytes(item)
            if data is None or len(data) == 0 or len(data) > MAX_FILE_BYTES:
                continue
            if total + len(data) > MAX_TOTAL_BYTES:
                continue
            try:
                inbox.mkdir(parents=True, exist_ok=True)
            except OSError:
                continue
            dest = _unique_inbox_path(inbox, name)
            if is_blocked_workspace_path(dest, root):
                continue
            try:
                dest.write_bytes(data)
            except OSError:
                continue
            row: dict[str, Any] = {
                "kind": "inline",
                "name": dest.name,
                "path": str(dest),
                "size": len(data),
                "binary": dest.suffix.lower() in BINARY_SUFFIXES or b"\0" in data[:2048],
            }
            if not row["binary"]:
                row["excerpt"] = _excerpt_text(
                    data[:MAX_EXCERPT_CHARS].decode("utf-8", errors="replace"),
                    truncated=len(data) > MAX_EXCERPT_CHARS,
                )
            total += len(data)
            out.append(row)
            continue
        resolved = _resolve_existing_file(root, str(item.get("path") or item.get("name") or ""))
        if resolved is None:
            continue
        try:
            size = resolved.stat().st_size
        except OSError:
            continue
        if total + size > MAX_TOTAL_BYTES:
            continue
        row = {
            "kind": "path",
            "name": resolved.name,
            "path": str(resolved),
            "size": size,
            "binary": resolved.suffix.lower() in BINARY_SUFFIXES,
        }
        if not row["binary"]:
            try:
                text = resolved.read_bytes()[:MAX_EXCERPT_CHARS].decode("utf-8", errors="replace")
            except OSError:
                text = ""
            if text and "\0" not in text:
                row["excerpt"] = _excerpt_text(text, truncated=size > MAX_EXCERPT_CHARS)
            else:
                row["binary"] = True
        total += size
        out.append(row)
    return out


def format_attachments_prompt(items: list[dict[str, Any]], lang: str) -> str:
    if not items:
        return ""
    header = (
        "用户附带了这些文件。图片可能已被直接查看；仍请用 read_file 或 inspect_local 读取下列路径。"
        if lang == "zh"
        else (
            "The user attached these files. Images may be seen directly; "
            "still use read_file or inspect_local on the paths below."
        )
    )
    lines = [ATTACH_MARKER, header]
    for index, item in enumerate(items, 1):
        name = str(item.get("name") or "file")
        path = str(item.get("path") or name)
        lines.append(f"{index}. {name}")
        lines.append(f"   path: {path}")
        excerpt = item.get("excerpt")
        if excerpt:
            lines.append("   excerpt:")
            lines.append(str(excerpt))
    return "\n".join(lines)


def _excerpt_block(items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in items:
        excerpt = item.get("excerpt")
        if not excerpt:
            continue
        name = str(item.get("name") or "file")
        parts.append(f"{name}:\n{excerpt}")
    if not parts:
        return ""
    return "[attachment contents]\n" + "\n\n".join(parts)


def merge_user_content_with_attachments(message: str, items: list[dict[str, Any]], lang: str) -> str:
    body = (message or "").strip()
    appendix = format_attachments_prompt(items, lang)
    if not appendix:
        return body
    if ATTACH_MARKER in body:
        extra = _excerpt_block(items)
        if extra:
            return f"{body}\n\n{extra}"
        return body
    if body:
        return f"{body}\n\n{appendix}"
    return appendix


def attachments_from_body(body: dict[str, Any]) -> list[Any]:
    raw = body.get("attachments")
    return raw if isinstance(raw, list) else []
