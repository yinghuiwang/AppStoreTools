"""Current-turn vision parts for Agent LLM payloads.

Image bytes stay in the in-memory OpenAI payload only. SQLite stores paths.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

# MiniMax Chat Completions (platform.minimaxi.com): image_url URL/base64
# is 10 MB per image and 64 MB per request body. Files API mm_file:// is
# documented for videos (purpose=video_understanding), not chat images.
MAX_VISION_IMAGES = 8
MAX_VISION_BYTES = 10 * 1024 * 1024
MAX_VISION_TOTAL_BYTES = 20 * 1024 * 1024
VISION_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def image_parts(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Build OpenAI image_url parts from this turn's normalized attachments."""
    parts: list[dict[str, Any]] = []
    if not items:
        return parts
    used = 0
    for item in items:
        if len(parts) >= MAX_VISION_IMAGES:
            break
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        suffix = path.suffix.lower()
        if suffix not in VISION_SUFFIXES:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= 0 or size > MAX_VISION_BYTES:
            continue
        if used + size > MAX_VISION_TOTAL_BYTES:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if not data or len(data) > MAX_VISION_BYTES:
            continue
        if used + len(data) > MAX_VISION_TOTAL_BYTES:
            continue
        mime = _MIME_BY_SUFFIX[suffix]
        encoded = base64.b64encode(data).decode("ascii")
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            }
        )
        used += len(data)
    return parts


def apply_current_turn_vision(
    messages: list[dict[str, Any]],
    items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Replace only the last user message content with text + image parts."""
    parts = image_parts(items)
    if not parts:
        return messages
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        text = message.get("content")
        if not isinstance(text, str):
            break
        message["content"] = [{"type": "text", "text": text}, *parts]
        break
    return messages
