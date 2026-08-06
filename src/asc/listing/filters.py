"""上传前按 locale / 字段过滤 metadata 行。"""
from __future__ import annotations


def filter_metadata_rows(
    rows: list[dict],
    locales: list[str] | None,
    fields_by_locale: dict[str, list[str]] | None,
) -> list[dict]:
    """按 `locales` 和 `fields_by_locale` 过滤 `rows`。

    - `locales` 非空：丢弃不在列表中的行（匹配 `row["locale"]`）；空/None 表示不按语言过滤。
    - `fields_by_locale` 为 `None`：不按字段过滤，保留整行。
    - `fields_by_locale` 提供时：`fields_by_locale[locale]` 缺失或为空列表 ⇒ 该语言跳过（丢弃整行）；
      非空 ⇒ 只保留 `locale` 键 + 列出的字段。
    """
    out: list[dict] = []
    for row in rows:
        loc = row.get("locale")
        if not loc:
            continue
        if locales and loc not in locales:
            continue
        if fields_by_locale is None:
            out.append(dict(row))
            continue
        allowed = fields_by_locale.get(loc)
        if not allowed:
            continue
        filtered = {"locale": loc}
        for key in allowed:
            if key in row and key != "locale":
                filtered[key] = row[key]
        if len(filtered) == 1:
            continue
        out.append(filtered)
    return out
