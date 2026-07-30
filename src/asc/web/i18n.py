from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

SUPPORTED_LANGS = frozenset({"zh", "en"})
COOKIE_NAME = "asc_lang"
COOKIE_MAX_AGE = 31536000
_LOCALES_DIR = Path(__file__).parent / "locales"
_ACCEPT_RE = re.compile(r"([a-zA-Z]{2,3}(?:-[a-zA-Z0-9]+)*)")


def normalize_lang(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower().replace("_", "-")
    if s in ("zh", "zh-cn", "zh-hans", "zh-tw", "zh-hant", "chinese"):
        return "zh"
    if s.startswith("zh"):
        return "zh"
    if s in ("en", "en-us", "en-gb", "english") or s.startswith("en"):
        return "en"
    return None


def resolve_lang(
    *,
    cookie: str | None = None,
    accept_language: str | None = None,
    env_lang: str | None = None,
) -> str:
    for candidate in (cookie,):
        n = normalize_lang(candidate)
        if n in SUPPORTED_LANGS:
            return n
    if accept_language:
        for part in accept_language.split(","):
            token = part.split(";")[0].strip()
            m = _ACCEPT_RE.match(token)
            if not m:
                continue
            n = normalize_lang(m.group(1))
            if n in SUPPORTED_LANGS:
                return n
    env_raw = env_lang if env_lang is not None else os.environ.get("ASC_LANG")
    n = normalize_lang(env_raw)
    if n in SUPPORTED_LANGS:
        return n
    return "en"


@lru_cache(maxsize=8)
def load_catalog(lang: str) -> dict[str, str]:
    code = lang if lang in SUPPORTED_LANGS else "en"
    path = _LOCALES_DIR / f"{code}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    code = lang if lang in SUPPORTED_LANGS else "en"
    catalog = load_catalog(code)
    text = catalog.get(key)
    if text is None and code != "en":
        text = load_catalog("en").get(key)
    if text is None:
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def html_lang(lang: str) -> str:
    return "zh-CN" if lang == "zh" else "en"
