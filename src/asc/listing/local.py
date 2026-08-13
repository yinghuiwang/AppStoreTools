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
_DIGIT_RUN_RE = re.compile(r"\d+")


class FileChangedError(Exception):
    """写回 CSV 时，磁盘文件的 mtime 与调用方持有的 `expected_mtime` 不一致。"""


class PathTraversalError(ValueError):
    """路径逃逸 screenshots root，或 locale/filename 含绝对路径 / `..`。"""


def _assert_under_root(root: Path | str, path: Path | str) -> Path:
    """Resolve `path` and assert it lies under resolved `root` via `os.path.commonpath`."""
    root_r = Path(root).resolve()
    path_r = Path(path).resolve()
    try:
        common = os.path.commonpath([str(root_r), str(path_r)])
    except ValueError as e:
        raise PathTraversalError("path is outside root") from e
    if common != str(root_r):
        raise PathTraversalError("path is outside root")
    return path_r


def _safe_locale_name(locale: str) -> str:
    """Reject absolute paths, `..`, and multi-segment locale names."""
    locale = (locale or "").strip()
    if not locale:
        raise PathTraversalError("locale is required")
    p = Path(locale)
    if p.is_absolute() or ".." in p.parts or len(p.parts) != 1:
        raise PathTraversalError("locale must not be absolute or contain '..'")
    return locale


def _safe_basename(filename: str) -> str:
    """Return a bare basename; reject absolute paths and `..` components."""
    filename = (filename or "").strip()
    if not filename:
        raise PathTraversalError("filename is required")
    p = Path(filename)
    if p.is_absolute() or ".." in p.parts:
        raise PathTraversalError("filename must not be absolute or contain '..'")
    base = p.name
    if not base or base in (".", ".."):
        raise PathTraversalError("invalid filename")
    return base


def _semantic_stem(stem: str) -> str:
    """Strip a leading `NN_` order prefix and all digit runs from the semantic base.

    `_get_sorted_screenshots` sorts by the *last* number in the stem, so the
    order prefix must be the only digits left (e.g. `01_shot.png`, not `01_2.png`).
    """
    match = _NUMERIC_PREFIX_RE.match(stem)
    base = match.group(1) if match else stem
    cleaned = _DIGIT_RUN_RE.sub("", base).strip("._- ")
    return cleaned or "shot"



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


def apply_screenshot_order(
    locale_dir: Path,
    display_type: str,
    ordered_file_names: list[str],
    *,
    root: Path | str | None = None,
) -> None:
    """Reorder `ordered_file_names` and renumber the entire locale folder consistently.

    Files named in `ordered_file_names` fill the slots previously occupied by
    that set (in the new order). Other files (e.g. a different displayType)
    keep their relative positions and are renumbered together so `NN_` prefixes
    never collide across types. Digit runs are stripped from semantic stems so
    `_get_sorted_screenshots` (which uses the last number in the stem) sees the
    order prefix as the sort key. `display_type` is accepted for
    interface/documentation purposes; callers should only pass names from that
    displayType group.

    Every entry in `ordered_file_names` must pass `_safe_basename` (no `..` /
    absolute paths). Resolved paths are asserted under `root` (or `locale_dir`
    when `root` is omitted) via `_assert_under_root`.
    """
    # Imported lazily — same rationale as `scan_local_screenshots`.
    from asc.commands.screenshots import _get_sorted_screenshots

    locale_dir = Path(locale_dir)
    root_r = Path(root).resolve() if root is not None else locale_dir.resolve()
    _assert_under_root(root_r, locale_dir)

    safe_names = [_safe_basename(n) for n in ordered_file_names]
    ordered_existing: list[str] = []
    for name in safe_names:
        candidate = locale_dir / name
        _assert_under_root(root_r, candidate)
        if candidate.exists():
            ordered_existing.append(name)

    all_files = _get_sorted_screenshots(locale_dir)
    ordered_set = set(ordered_existing)

    # Preserve other types' slots: walk current sorted order and replace only
    # members of the reorder set with the new sequence.
    final_names: list[str] = []
    qi = 0
    for f in all_files:
        if f.name in ordered_set:
            if qi < len(ordered_existing):
                final_names.append(ordered_existing[qi])
                qi += 1
        else:
            final_names.append(f.name)
    while qi < len(ordered_existing):
        name = ordered_existing[qi]
        if name not in final_names:
            final_names.append(name)
        qi += 1

    entries: list[tuple[Path, str, str]] = []
    for name in final_names:
        src = locale_dir / name
        if not src.exists():
            continue
        entries.append((src, _semantic_stem(src.stem), src.suffix))

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


def replace_screenshot(
    path: Path,
    upload_bytes: bytes,
    new_name: str | None,
    *,
    root: Path | str | None = None,
) -> Path:
    """Overwrite the screenshot at `path` with `upload_bytes`, optionally renaming it.

    When `new_name` is set it must be a bare basename (no absolute path / `..`);
    the target is always written under `path.parent`. When `root` is provided,
    both `path` / `path.parent` and the final target must resolve under it.
    """
    path = Path(path)
    if root is not None:
        root_r = Path(root).resolve()
        _assert_under_root(root_r, path)
        _assert_under_root(root_r, path.parent)

    if new_name:
        target = path.parent / _safe_basename(new_name)
    else:
        target = path

    if root is not None:
        _assert_under_root(Path(root).resolve(), target)

    target.write_bytes(upload_bytes)
    if target != path and path.exists():
        path.unlink()
    return target


def rename_screenshot(path: Path, new_name: str, *, root: Path | str) -> Path:
    """Rename a screenshot, keeping the result under `root`.

    `new_name` must be a bare basename (no absolute path / `..`). Both the
    source and the resolved target are asserted under `root`.
    """
    path = Path(path)
    root_r = Path(root).resolve()
    _assert_under_root(root_r, path)
    _assert_under_root(root_r, path.parent)
    target = path.parent / _safe_basename(new_name)
    _assert_under_root(root_r, target)
    return path.rename(target)


def delete_screenshot(path: Path) -> None:
    """Delete the screenshot at `path`; a no-op if the file no longer exists."""
    path = Path(path)
    if path.exists():
        path.unlink()


def add_screenshot(
    locale_dir: Path,
    display_type: str,
    filename: str,
    data: bytes,
    *,
    root: Path | str | None = None,
) -> Path:
    """Write a new screenshot into `locale_dir`, creating it if needed.

    `filename` is reduced to a bare basename; absolute paths and `..` are
    rejected. When `root` is provided, both `locale_dir` and the final target
    must resolve under it. `display_type` is accepted for interface/documentation
    purposes (actual type is re-detected from image dimensions on the next scan).
    """
    safe_name = _safe_basename(filename)
    locale_dir = Path(locale_dir)

    if root is not None:
        root_r = Path(root).resolve()
        _assert_under_root(root_r, locale_dir)

    locale_dir.mkdir(parents=True, exist_ok=True)
    target = locale_dir / safe_name

    if root is not None:
        _assert_under_root(Path(root).resolve(), target)

    target.write_bytes(data)
    return target
