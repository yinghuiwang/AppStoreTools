"""本地 CSV 与 ListingSnapshot 的互转（读入 + 写回），以及本地截图目录的扫描 / 编辑辅助函数。"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from urllib.parse import quote

from asc.constants import SCREENSHOT_FOLDER_TO_LOCALE, canonicalize_csv_header
from asc.listing.models import FIELD_NAMES, ListingSnapshot, LocaleListing, ScreenshotItem
from asc.utils import extract_locale, parse_csv

UNKNOWN_DISPLAY_TYPE = "UNKNOWN"

_NUMERIC_PREFIX_RE = re.compile(r"^\d+_(.+)$")


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


def _folder_locale(folder_name: str) -> str:
    """Map a screenshots subfolder name to a locale code via `SCREENSHOT_FOLDER_TO_LOCALE`."""
    return SCREENSHOT_FOLDER_TO_LOCALE.get(folder_name.lower(), folder_name)


def _thumb_url(root: str, path: Path) -> str:
    return f"/api/listing/thumb?path={quote(str(path), safe='')}&root={quote(str(root), safe='')}"


def scan_local_screenshots(screenshots_dir: str) -> dict[str, dict[str, list[ScreenshotItem]]]:
    """Scan `screenshots_dir` and return `locale -> displayType -> [ScreenshotItem]`.

    Display type is detected per-file via `_detect_display_type` (image dimensions);
    files whose dimensions don't match any known device type are grouped under
    `"UNKNOWN"` and still listed (not dropped).
    """
    # Imported lazily to avoid a hard dependency between `asc.listing` and the
    # `asc.commands` CLI layer at module import time.
    from asc.commands.screenshots import _detect_display_type, _get_sorted_screenshots

    result: dict[str, dict[str, list[ScreenshotItem]]] = {}
    base = Path(screenshots_dir)
    if not base.exists() or not base.is_dir():
        return result

    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        files = _get_sorted_screenshots(folder)
        if not files:
            continue
        locale = _folder_locale(folder.name)
        by_type: dict[str, list[ScreenshotItem]] = {}
        for file_path in files:
            display_type = _detect_display_type(file_path) or UNKNOWN_DISPLAY_TYPE
            items = by_type.setdefault(display_type, [])
            items.append(
                ScreenshotItem(
                    file_name=file_path.name,
                    order=len(items) + 1,
                    thumb_url=_thumb_url(str(base), file_path),
                    local_path=str(file_path),
                )
            )
        result[locale] = by_type
    return result


def find_locale_screenshot_dir(screenshots_dir: str, locale: str) -> Path | None:
    """Find the subfolder of `screenshots_dir` that maps to `locale`, if any."""
    base = Path(screenshots_dir)
    if not base.exists() or not base.is_dir():
        return None
    for folder in base.iterdir():
        if folder.is_dir() and _folder_locale(folder.name) == locale:
            return folder
    return None


def apply_screenshot_order(locale_dir: Path, display_type: str, ordered_file_names: list[str]) -> None:
    """Reorder the files in `ordered_file_names` within `locale_dir` to `01_stem.ext`, `02_...`.

    Only the files named in `ordered_file_names` are touched — other files in
    `locale_dir` (e.g. belonging to a different displayType) are left as-is.
    A previously-applied `NN_` numeric prefix is stripped so the semantic stem
    is preserved across repeated reorders. `display_type` is accepted for
    interface/documentation purposes; callers are expected to only pass file
    names that belong to that displayType group.
    """
    locale_dir = Path(locale_dir)

    entries: list[tuple[Path, str, str]] = []
    for name in ordered_file_names:
        src = locale_dir / name
        if not src.exists():
            continue
        match = _NUMERIC_PREFIX_RE.match(src.stem)
        semantic_stem = match.group(1) if match else src.stem
        entries.append((src, semantic_stem, src.suffix))

    # Two-phase rename (via temp names) so swapping/rotating positions never
    # collides with a file that hasn't been renamed yet.
    temp_entries: list[tuple[Path, str, str]] = []
    for idx, (src, semantic_stem, suffix) in enumerate(entries):
        tmp_path = locale_dir / f".__asc_reorder_tmp_{idx}{suffix}"
        src.rename(tmp_path)
        temp_entries.append((tmp_path, semantic_stem, suffix))

    for idx, (tmp_path, semantic_stem, suffix) in enumerate(temp_entries, start=1):
        new_name = f"{idx:02d}_{semantic_stem}{suffix}"
        tmp_path.rename(locale_dir / new_name)


def replace_screenshot(path: Path, upload_bytes: bytes, new_name: str | None) -> Path:
    """Overwrite the screenshot at `path` with `upload_bytes`, optionally renaming it."""
    path = Path(path)
    target = path.parent / new_name if new_name else path
    target.write_bytes(upload_bytes)
    if target != path and path.exists():
        path.unlink()
    return target


def delete_screenshot(path: Path) -> None:
    """Delete the screenshot at `path`; a no-op if the file no longer exists."""
    path = Path(path)
    if path.exists():
        path.unlink()


def add_screenshot(locale_dir: Path, display_type: str, filename: str, data: bytes) -> Path:
    """Write a new screenshot `filename` (bytes `data`) into `locale_dir`, creating it if needed.

    `display_type` is accepted for interface/documentation purposes (the new
    file's actual displayType is re-detected from its image dimensions on the
    next scan); it is not encoded into the file name here.
    """
    locale_dir = Path(locale_dir)
    locale_dir.mkdir(parents=True, exist_ok=True)
    target = locale_dir / filename
    target.write_bytes(data)
    return target
