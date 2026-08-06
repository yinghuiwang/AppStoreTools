"""本地 CSV 与 ListingSnapshot 的互转（读入 + 写回）。

截图相关的本地文件系统辅助函数将在后续任务中补充到本文件。
"""
from __future__ import annotations

import csv
import os

from asc.constants import canonicalize_csv_header
from asc.listing.models import FIELD_NAMES, ListingSnapshot, LocaleListing
from asc.utils import extract_locale, parse_csv


class FileChangedError(Exception):
    """写回 CSV 时，磁盘文件的 mtime 与调用方持有的 `expected_mtime` 不一致。"""


def load_local_text_snapshot(csv_path: str) -> ListingSnapshot:
    """读取本地 CSV，构建纯文本字段的 `ListingSnapshot`（不含截图）。"""
    rows = parse_csv(csv_path)
    locales: list[LocaleListing] = []
    for row in rows:
        fields = {name: row.get(name, "") for name in FIELD_NAMES}
        locales.append(LocaleListing(locale=row["locale"], fields=fields, screenshots={}))
    return ListingSnapshot(source="local", locales=locales)


def save_local_csv(
    csv_path: str,
    locales: list[LocaleListing],
    *,
    expected_mtime: float | None = None,
) -> float:
    """将 `locales` 写回 `csv_path`，返回写入后的新 mtime。

    - 保留原表头顺序与未识别列
    - 按原行序更新匹配 locale 的行；新 locale 追加到末尾
    - locale 列尽量保留原始展示串（如 `简体中文(zh-Hans)`），找不到对应行时写入纯 locale code
    """
    if expected_mtime is not None and os.path.exists(csv_path):
        actual_mtime = os.path.getmtime(csv_path)
        if actual_mtime != expected_mtime:
            raise FileChangedError(
                f"{csv_path} was modified on disk (expected mtime {expected_mtime}, "
                f"found {actual_mtime})"
            )

    by_locale = {loc.locale: loc for loc in locales}

    fieldnames: list[str] = []
    raw_rows: list[dict[str, str]] = []
    locale_col = "locale"
    # canonical field name ("locale" / one of FIELD_NAMES) -> actual raw column
    # name in the file (which may be a Chinese alias like "语言" or "应用名称").
    column_for_canonical: dict[str, str] = {}

    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            raw_rows = [dict(row) for row in reader]

        for fname in fieldnames:
            stripped = (fname or "").strip().strip('"').strip("'").strip()
            canonical = canonicalize_csv_header(stripped)
            if canonical is None:
                continue
            # Prefer the exact English canonical column if there are duplicates.
            if canonical not in column_for_canonical or stripped == canonical:
                column_for_canonical[canonical] = fname

        if "locale" in column_for_canonical:
            locale_col = column_for_canonical["locale"]

    if not fieldnames:
        fieldnames = ["locale", *FIELD_NAMES]
        locale_col = "locale"
        column_for_canonical = {"locale": "locale", **{name: name for name in FIELD_NAMES}}
    else:
        for name in FIELD_NAMES:
            if name not in column_for_canonical:
                fieldnames.append(name)
                column_for_canonical[name] = name

    matched_locales: set[str] = set()
    out_rows: list[dict[str, str]] = []
    for raw_row in raw_rows:
        raw_locale_display = raw_row.get(locale_col, "") or ""
        locale_code = extract_locale(raw_locale_display)
        listing = by_locale.get(locale_code)
        row = dict(raw_row)
        if listing is not None:
            matched_locales.add(locale_code)
            for name in FIELD_NAMES:
                col = column_for_canonical.get(name, name)
                row[col] = listing.fields.get(name, "")
        out_rows.append(row)

    for loc in locales:
        if loc.locale in matched_locales:
            continue
        row = {fname: "" for fname in fieldnames}
        row[locale_col] = loc.locale
        for name in FIELD_NAMES:
            col = column_for_canonical.get(name, name)
            row[col] = loc.fields.get(name, "")
        out_rows.append(row)

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in out_rows:
            writer.writerow(row)

    return os.path.getmtime(csv_path)
