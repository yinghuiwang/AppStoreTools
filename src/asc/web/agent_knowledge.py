"""Read-only App Store Connect notes shipped inside this package."""
from __future__ import annotations

import re
from importlib import resources
from typing import Any

from asc.web.agent_redact import redact_text

_PACKAGE = "asc.web.knowledge"
_INDEX_NAME = "INDEX.md"
_MAX_QUERY = 200
_DEFAULT_SEARCH_CHARS = 8000
_MAX_SEARCH_CHARS = 12000
_DEFAULT_TOPIC_CHARS = 10000
_MAX_TOPIC_CHARS = 14000
_SNIPPET_RADIUS = 2
_MAX_SNIPPETS = 4
_NOTE_CACHE: dict[str, str] = {}
_SNIPPET_LINE_MAX = 240

TOPIC_FILES: dict[str, str] = {
    "locales": "locales.md",
    "listing": "listing.md",
    "screenshots": "screenshots.md",
    "iap": "iap.md",
    "version": "version.md",
    "pitfalls": "pitfalls.md",
}

_TOPIC_ALIASES: dict[str, str] = {
    "locale": "locales",
    "language": "locales",
    "languages": "locales",
    "region": "locales",
    "regions": "locales",
    "metadata": "listing",
    "keywords": "listing",
    "subtitle": "listing",
    "description": "listing",
    "appstore-listing": "listing",
    "separator": "listing",
    "legal": "listing",
    "screenshot": "screenshots",
    "screenshots": "screenshots",
    "preview": "screenshots",
    "iap": "iap",
    "subscription": "iap",
    "subscriptions": "iap",
    "in-app": "iap",
    "iap-packages": "iap",
    "grouplevel": "iap",
    "whatsnew": "version",
    "what's new": "version",
    "whats new": "version",
    "whats-new": "version",
    "version": "version",
    "review": "version",
    "rejection": "pitfalls",
    "pitfall": "pitfalls",
    "limit": "pitfalls",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.I)
_PHRASE_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("what's new", ("whatsnew", "whatsnew", "version")),
    ("whats new", ("whatsnew", "version")),
    ("whats-new", ("whatsnew", "version")),
    ("iap 类型", ("iap", "consumable", "subscription")),
    ("keywords 字数", ("keywords", "100", "listing")),
    ("grouplevel", ("grouplevel", "iap", "crossgrade")),
    ("10选项", ("iap", "localization", "grouplevel")),
    ("appstore-listing", ("listing", "separator", "en-us")),
)


def knowledge_root():
    return resources.files(_PACKAGE)


def list_topics() -> list[str]:
    return list(TOPIC_FILES)


def normalize_topic(value: str | None) -> str | None:
    if not value:
        return None
    key = str(value).strip().lower().replace("_", "-")
    if key in TOPIC_FILES:
        return key
    return _TOPIC_ALIASES.get(key)


def _read_packaged(name: str) -> str:
    cached = _NOTE_CACHE.get(name)
    if cached is not None:
        return cached
    path = knowledge_root().joinpath(name)
    text = path.read_text(encoding="utf-8")
    _NOTE_CACHE[name] = text
    return text


def _clip(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[: max(0, max_chars - 1)].rstrip() + "…", True


def _normalize_query(text: str) -> str:
    return (text or "").replace("’", "'").replace("‘", "'")


def _tokens(text: str) -> list[str]:
    lowered = _normalize_query(text).lower()
    parts = [part.lower() for part in _TOKEN_RE.findall(lowered) if part]
    extra: list[str] = []
    for phrase, mapped in _PHRASE_TOKENS:
        if phrase in lowered:
            extra.extend(mapped)
    if "whats" in parts and "new" in parts:
        extra.extend(("whatsnew", "version"))
    return parts + extra


def _score_text(text: str, tokens: list[str]) -> int:
    lowered = text.lower()
    score = 0
    for token in tokens:
        if not token:
            continue
        score += lowered.count(token)
        if token in lowered[:400]:
            score += 2
    return score


def _snippets(text: str, tokens: list[str], *, limit: int = _MAX_SNIPPETS) -> list[str]:
    lines = text.splitlines()
    lowered_tokens = [token for token in tokens if token]
    scored: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        blob = line.lower()
        score = sum(1 for token in lowered_tokens if token in blob)
        if score:
            scored.append((-score, index))
    scored.sort()
    hits = [index for _, index in scored]
    if not hits and lines:
        hits = [0]
    used: set[int] = set()
    snippets: list[str] = []
    for index in hits:
        start = max(0, index - _SNIPPET_RADIUS)
        end = min(len(lines), index + _SNIPPET_RADIUS + 1)
        key = (start, end)
        if key in used:
            continue
        used.add(key)
        chunk = []
        for raw in lines[start:end]:
            line = raw.rstrip()
            if len(line) > _SNIPPET_LINE_MAX:
                line = line[: _SNIPPET_LINE_MAX - 1] + "…"
            chunk.append(line)
        snippets.append("\n".join(chunk).strip())
        if len(snippets) >= limit:
            break
    return snippets


def get_topic(topic: str, *, max_chars: int = _DEFAULT_TOPIC_CHARS) -> dict[str, Any]:
    name = normalize_topic(topic)
    if name is None:
        return {
            "ok": False,
            "error": f"unknown topic: {topic!r}. Use: {', '.join(TOPIC_FILES)}",
        }
    cap = max(200, min(int(max_chars or _DEFAULT_TOPIC_CHARS), _MAX_TOPIC_CHARS))
    body, truncated = _clip(_read_packaged(TOPIC_FILES[name]), cap)
    return {
        "ok": True,
        "topic": name,
        "path": f"package:{_PACKAGE}/{TOPIC_FILES[name]}",
        "content": redact_text(body),
        "truncated": truncated,
    }


def search_notes(
    query: str,
    *,
    topic: str | None = None,
    max_chars: int = _DEFAULT_SEARCH_CHARS,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query is required"}
    if len(q) > _MAX_QUERY:
        q = q[:_MAX_QUERY]
    cap = max(200, min(int(max_chars or _DEFAULT_SEARCH_CHARS), _MAX_SEARCH_CHARS))
    tokens = _tokens(q)
    if not tokens:
        tokens = [q.lower()]

    selected = normalize_topic(topic)
    if topic and selected is None:
        return {
            "ok": False,
            "error": f"unknown topic: {topic!r}. Use: {', '.join(TOPIC_FILES)}",
        }

    names = [selected] if selected else list(TOPIC_FILES)
    ranked: list[tuple[int, str, str]] = []
    for name in names:
        text = _read_packaged(TOPIC_FILES[name])
        score = _score_text(text, tokens)
        if name in tokens or any(alias == name for alias in tokens):
            score += 5
        if selected == name:
            score += 3
        ranked.append((score, name, text))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    hits: list[dict[str, Any]] = []
    used = 0
    for score, name, text in ranked:
        if score <= 0 and selected is None:
            continue
        snippets = _snippets(text, tokens)
        payload = {
            "topic": name,
            "path": f"package:{_PACKAGE}/{TOPIC_FILES[name]}",
            "score": score,
            "snippets": [],
        }
        for snippet in snippets:
            piece, _ = _clip(snippet, max(120, cap - used))
            piece = redact_text(piece)
            payload["snippets"].append(piece)
            used += len(piece)
            if used >= cap:
                break
        if payload["snippets"]:
            hits.append(payload)
        if used >= cap:
            break

    if not hits:
        index = _read_packaged(_INDEX_NAME)
        snippet, _ = _clip(index, min(800, cap))
        hits.append(
            {
                "topic": "index",
                "path": f"package:{_PACKAGE}/{_INDEX_NAME}",
                "score": 0,
                "snippets": [redact_text(snippet)],
            }
        )

    return {
        "ok": True,
        "query": q,
        "topic": selected,
        "hits": hits,
        "truncated": used >= cap,
    }
