"""Shared utility functions used across command modules"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Optional

import typer

from asc.constants import CSV_LOCALE_TO_ASC, normalize_locale_code


def extract_locale(raw_lang: str) -> str:
    """从 '简体中文(zh-Hans)' 或 '英文(en-US)' 格式中提取 locale 代码"""
    m = re.search(r"\(([^)]+)\)", raw_lang)
    if m:
        return normalize_locale_code(m.group(1))
    return normalize_locale_code(raw_lang.strip())


def parse_csv(csv_path: str) -> list[dict]:
    """解析 CSV 元数据文件，返回每个语言的元数据字典列表"""
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        raw_headers = reader.fieldnames or []
        clean_headers = []
        for h in raw_headers:
            stripped = h.strip().strip('"')
            if stripped:
                clean_headers.append((h, stripped))

        results = []
        for row in reader:
            mapped = {}
            for orig_key, clean_key in clean_headers:
                val = row.get(orig_key)
                if val and val.strip():
                    mapped[clean_key] = val.strip()
            if "语言" not in mapped or not mapped["语言"]:
                continue
            mapped["语言"] = extract_locale(mapped["语言"])
            results.append(mapped)

    return results


def resolve_locale(csv_locale: str, existing_locales: list[str]) -> Optional[str]:
    """将 CSV 中的语言代码映射到 ASC 中实际存在的 locale"""
    csv_locale = normalize_locale_code(csv_locale)

    if csv_locale in existing_locales:
        return csv_locale

    asc_locale = CSV_LOCALE_TO_ASC.get(csv_locale)
    if asc_locale and asc_locale in existing_locales:
        return asc_locale

    for existing in existing_locales:
        if existing.startswith(csv_locale):
            return existing

    return asc_locale or csv_locale


def md5_of_file(file_path: Path) -> str:
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def make_api_from_config(config, app_id_override: Optional[str] = None):
    """Build an AppStoreConnectAPI instance from config, validating required fields"""
    from asc.api import AppStoreConnectAPI

    issuer_id = config.issuer_id
    key_id = config.key_id
    key_file = config.key_file
    app_id = app_id_override or config.app_id

    missing = []
    if not issuer_id:
        missing.append("ISSUER_ID / issuer_id")
    if not key_id:
        missing.append("KEY_ID / key_id")
    if not key_file:
        missing.append("KEY_FILE / key_file")
    if not app_id:
        missing.append("APP_ID / app_id")
    if missing:
        typer.echo(
            f"❌ Missing required config: {', '.join(missing)}\n"
            "Run 'asc app add <name>' to configure an app profile, or set environment variables.",
            err=True,
        )
        raise typer.Exit(1)

    return AppStoreConnectAPI(issuer_id, key_id, key_file), app_id
