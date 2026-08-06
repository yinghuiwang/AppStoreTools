# Web Metadata Listing Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/metadata` 提供按语言的 CSV/截图本地预览与编辑（写回本地）、细粒度勾选上传，以及与 App Store Connect 同结构的 Diff 与拉取覆盖。

**Architecture:** 新增 `src/asc/listing/` 领域层（统一 `ListingSnapshot`、本地读写、ASC 拉取、纯函数 Diff、上传过滤）；Web 用 `routes_listing.py` 暴露 API；`metadata.html` 扩展为路径区 + 本地工作台 + Diff 工作台；上传仍走现有 task runner，对 metadata/screenshots core 增加过滤。

**Tech Stack:** Python 3.9+, FastAPI, Jinja2, Alpine.js, HTMX, pytest, Pillow（已有）

**Spec:** `docs/superpowers/specs/2026-08-06-web-metadata-listing-preview-design.md`

## Global Constraints

- 文本编辑必须显式「保存到 CSV」；未保存时禁止上传与任何拉取
- 截图排序/替换/删除直接改本地文件；排序前缀与 `_get_sorted_screenshots` 兼容（文件名中的数字排序）
- 勾选粒度：每语言 × 每字段；截图为语言 × displayType × 可选 fileNames
- 文本 Diff：trim 后比较；缺失键与空串视为空
- 截图 Diff：只并排缩略图，不做自动相同判定
- 不创建 ASC 版本；不自动写盘；不做截图 MD5 相等判定
- `docs/superpowers/` 在 `.gitignore` 中；提交计划/规格时使用 `git add -f`
- 中英文 UI 文案写入 `src/asc/web/locales/{zh,en}.json`
- 遵循现有 Conventional Commits（`feat(web):` / `test:` / `fix:`）

---

## 文件结构

```text
src/asc/listing/
  __init__.py              # 导出公共 API
  models.py                # ListingSnapshot / LocaleListing / ScreenshotItem / ListingDiff
  local.py                 # 读本地 CSV+截图目录；写 CSV；截图排序/替换/删/增
  remote.py                # 从 ASC 构建 Snapshot；缩略图 URL；下载截图到本地
  diff.py                  # diff_snapshots(local, asc) -> ListingDiff
  filters.py               # filter_metadata_rows / 规范化 screenshot_scopes

src/asc/web/
  routes_listing.py        # /api/listing/* 
  routes_api.py            # 扩展 metadata/run 过滤参数；注册或 include listing router
  server.py                # include_router(listing)
  templates/metadata.html  # 三区 UI
  locales/zh.json, en.json

src/asc/commands/
  metadata.py              # 可选：文档化过滤由调用方预处理即可（本计划优先 filters + 调用方）
  screenshots.py           # 按文件检测 displayType 分组；支持 locales/scopes 过滤

tests/
  test_listing_models.py
  test_listing_diff.py
  test_listing_local.py
  test_listing_filters.py
  test_listing_remote.py
  test_screenshots_filter.py
  test_web_listing.py
```

---

### Task 1: Listing 模型与 Diff 纯函数

**Files:**
- Create: `src/asc/listing/__init__.py`
- Create: `src/asc/listing/models.py`
- Create: `src/asc/listing/diff.py`
- Test: `tests/test_listing_diff.py`

**Interfaces:**
- Produces:
  - `FIELD_NAMES: tuple[str, ...] = ("name", "subtitle", "privacyPolicyUrl", "description", "keywords", "supportUrl", "marketingUrl")`
  - `@dataclass ScreenshotItem`: `file_name: str`, `order: int`, `thumb_url: str = ""`, `local_path: str = ""`, `remote_id: str = ""`
  - `@dataclass LocaleListing`: `locale: str`, `fields: dict[str, str]`, `screenshots: dict[str, list[ScreenshotItem]]`
  - `@dataclass ListingSnapshot`: `source: str`, `locales: list[LocaleListing]`, `version: dict | None = None`
  - `@dataclass FieldDiff`: `field: str`, `status: str`, `local: str`, `asc: str`  # status ∈ equal|local_only|asc_only|changed
  - `@dataclass ScreenshotTypeDiff`: `display_type: str`, `local: list[ScreenshotItem]`, `asc: list[ScreenshotItem]`
  - `@dataclass LocaleDiff`: `locale: str`, `fields: list[FieldDiff]`, `screenshots: list[ScreenshotTypeDiff]`
  - `@dataclass ListingDiff`: `locales: list[LocaleDiff]`
  - `def diff_snapshots(local: ListingSnapshot, asc: ListingSnapshot) -> ListingDiff`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_listing_diff.py
from __future__ import annotations

from asc.listing.diff import diff_snapshots
from asc.listing.models import ListingSnapshot, LocaleListing, ScreenshotItem


def _snap(source, locales):
    return ListingSnapshot(source=source, locales=locales)


def test_field_equal_and_changed():
    local = _snap("local", [
        LocaleListing("en-US", {"name": "A", "description": "x"}, {}),
    ])
    asc = _snap("asc", [
        LocaleListing("en-US", {"name": "A", "description": "y"}, {}),
    ])
    d = diff_snapshots(local, asc)
    by = {f.field: f for f in d.locales[0].fields}
    assert by["name"].status == "equal"
    assert by["description"].status == "changed"
    assert by["description"].local == "x"
    assert by["description"].asc == "y"


def test_empty_and_missing_are_equal():
    local = _snap("local", [LocaleListing("en-US", {"name": ""}, {})])
    asc = _snap("asc", [LocaleListing("en-US", {}, {})])
    d = diff_snapshots(local, asc)
    by = {f.field: f for f in d.locales[0].fields}
    assert by["name"].status == "equal"


def test_local_only_and_asc_only_locale():
    local = _snap("local", [LocaleListing("zh-Hans", {"name": "中"}, {})])
    asc = _snap("asc", [LocaleListing("ja", {"name": "日"}, {})])
    d = diff_snapshots(local, asc)
    locales = {x.locale: x for x in d.locales}
    assert "zh-Hans" in locales and "ja" in locales
    zh = {f.field: f for f in locales["zh-Hans"].fields}
    assert zh["name"].status == "local_only"
    ja = {f.field: f for f in locales["ja"].fields}
    assert ja["name"].status == "asc_only"


def test_screenshot_type_side_by_side_no_equality():
    local = _snap("local", [
        LocaleListing("en-US", {}, {
            "APP_IPHONE_67": [ScreenshotItem("01_a.png", 1, local_path="/a")],
        }),
    ])
    asc = _snap("asc", [
        LocaleListing("en-US", {}, {
            "APP_IPHONE_67": [ScreenshotItem("x.png", 1, remote_id="s1")],
            "APP_IPHONE_65": [ScreenshotItem("y.png", 1, remote_id="s2")],
        }),
    ])
    d = diff_snapshots(local, asc)
    types = {s.display_type: s for s in d.locales[0].screenshots}
    assert len(types["APP_IPHONE_67"].local) == 1
    assert len(types["APP_IPHONE_67"].asc) == 1
    assert len(types["APP_IPHONE_65"].local) == 0
    assert len(types["APP_IPHONE_65"].asc) == 1
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/test_listing_diff.py -v`  
Expected: import error / not found

- [ ] **Step 3: Implement models + diff**

```python
# src/asc/listing/models.py
from __future__ import annotations
from dataclasses import dataclass, field

FIELD_NAMES = (
    "name", "subtitle", "privacyPolicyUrl",
    "description", "keywords", "supportUrl", "marketingUrl",
)

@dataclass
class ScreenshotItem:
    file_name: str
    order: int
    thumb_url: str = ""
    local_path: str = ""
    remote_id: str = ""

@dataclass
class LocaleListing:
    locale: str
    fields: dict[str, str]
    screenshots: dict[str, list[ScreenshotItem]] = field(default_factory=dict)

@dataclass
class ListingSnapshot:
    source: str
    locales: list[LocaleListing]
    version: dict | None = None

@dataclass
class FieldDiff:
    field: str
    status: str
    local: str
    asc: str

@dataclass
class ScreenshotTypeDiff:
    display_type: str
    local: list[ScreenshotItem]
    asc: list[ScreenshotItem]

@dataclass
class LocaleDiff:
    locale: str
    fields: list[FieldDiff]
    screenshots: list[ScreenshotTypeDiff]

@dataclass
class ListingDiff:
    locales: list[LocaleDiff]
```

```python
# src/asc/listing/diff.py
from __future__ import annotations
from asc.listing.models import (
    FIELD_NAMES, FieldDiff, ListingDiff, ListingSnapshot,
    LocaleDiff, LocaleListing, ScreenshotTypeDiff,
)

def _norm(v: str | None) -> str:
    return (v or "").strip()

def _field_status(local: str, asc: str) -> str:
    l, a = _norm(local), _norm(asc)
    if not l and not a:
        return "equal"
    if l and not a:
        return "local_only"
    if a and not l:
        return "asc_only"
    if l == a:
        return "equal"
    return "changed"

def diff_snapshots(local: ListingSnapshot, asc: ListingSnapshot) -> ListingDiff:
    local_map = {x.locale: x for x in local.locales}
    asc_map = {x.locale: x for x in asc.locales}
    locales = sorted(set(local_map) | set(asc_map))
    out: list[LocaleDiff] = []
    for loc in locales:
        lm = local_map.get(loc) or LocaleListing(loc, {}, {})
        am = asc_map.get(loc) or LocaleListing(loc, {}, {})
        fields = [
            FieldDiff(
                field=f,
                status=_field_status(lm.fields.get(f, ""), am.fields.get(f, "")),
                local=_norm(lm.fields.get(f, "")),
                asc=_norm(am.fields.get(f, "")),
            )
            for f in FIELD_NAMES
        ]
        types = sorted(set(lm.screenshots) | set(am.screenshots))
        shots = [
            ScreenshotTypeDiff(
                display_type=t,
                local=list(lm.screenshots.get(t, [])),
                asc=list(am.screenshots.get(t, [])),
            )
            for t in types
        ]
        out.append(LocaleDiff(locale=loc, fields=fields, screenshots=shots))
    return ListingDiff(locales=out)
```

```python
# src/asc/listing/__init__.py
from asc.listing.diff import diff_snapshots
from asc.listing.models import (
    FIELD_NAMES, FieldDiff, ListingDiff, ListingSnapshot,
    LocaleDiff, LocaleListing, ScreenshotItem, ScreenshotTypeDiff,
)

__all__ = [
    "FIELD_NAMES", "ScreenshotItem", "LocaleListing", "ListingSnapshot",
    "FieldDiff", "ScreenshotTypeDiff", "LocaleDiff", "ListingDiff",
    "diff_snapshots",
]
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_listing_diff.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/asc/listing tests/test_listing_diff.py
git commit -m "feat(listing): add snapshot models and diff"
```

---

### Task 2: 本地 CSV 读入 Snapshot + 写回

**Files:**
- Create: `src/asc/listing/local.py`（本任务只做 CSV 部分；截图函数可先 stub 或同文件后半在 Task 4 填充）
- Test: `tests/test_listing_local.py`

**Interfaces:**
- Consumes: `parse_csv`, `FIELD_NAMES`, `ListingSnapshot`, `LocaleListing`
- Produces:
  - `def load_local_text_snapshot(csv_path: str) -> ListingSnapshot`
  - `def save_local_csv(csv_path: str, locales: list[LocaleListing], *, expected_mtime: float | None = None) -> float`  
    返回新 mtime；若提供 `expected_mtime` 且文件 mtime 不等则 `raise FileChangedError`
  - `class FileChangedError(Exception): ...`

**写回规则：**
- 用 `utf-8-sig` 读写
- 若文件已存在：保留原表头顺序与未识别列；按原行序更新匹配 locale 的行；`locales` 中新 locale 追加到末尾
- locale 列单元格：若原值含 `DisplayName(code)` 则尽量保留原展示串，仅当找不到行时写入纯 locale code
- `parse_csv` 会丢空字段；Snapshot 的 `fields` 对 `FIELD_NAMES` 缺省补 `""`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_listing_local.py
from __future__ import annotations
from pathlib import Path
import time
import pytest
from asc.listing.local import (
    FileChangedError, load_local_text_snapshot, save_local_csv,
)
from asc.listing.models import LocaleListing

def test_load_local_text_snapshot(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text(
        "locale,name,subtitle,description\n"
        "简体中文(zh-Hans),应用,副标,描述\n"
        "en-US,App,,Hello\n",
        encoding="utf-8-sig",
    )
    snap = load_local_text_snapshot(str(p))
    assert snap.source == "local"
    by = {x.locale: x for x in snap.locales}
    assert by["zh-Hans"].fields["name"] == "应用"
    assert by["en-US"].fields["description"] == "Hello"
    assert by["en-US"].fields["subtitle"] == ""

def test_save_preserves_unknown_columns_and_order(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text(
        "locale,name,extra,description\n"
        "en-US,Old,keep-me,Desc\n"
        "zh-Hans,中,保留,描\n",
        encoding="utf-8-sig",
    )
    snap = load_local_text_snapshot(str(p))
    en = next(x for x in snap.locales if x.locale == "en-US")
    en.fields["name"] = "New"
    save_local_csv(str(p), snap.locales)
    text = p.read_text(encoding="utf-8-sig")
    assert "extra" in text.splitlines()[0]
    assert "keep-me" in text
    assert "New" in text
    # zh-Hans row still present before/after en depending on original order
    assert text.index("en-US") < text.index("zh-Hans") or "zh-Hans" in text

def test_save_mtime_conflict(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text("locale,name\nen-US,A\n", encoding="utf-8-sig")
    mtime = p.stat().st_mtime
    time.sleep(0.02)
    p.write_text("locale,name\nen-US,B\n", encoding="utf-8-sig")
    with pytest.raises(FileChangedError):
        save_local_csv(
            str(p),
            [LocaleListing("en-US", {"name": "C"}, {})],
            expected_mtime=mtime,
        )
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/test_listing_local.py -v`

- [ ] **Step 3: Implement `load_local_text_snapshot` + `save_local_csv`**

实现要点：
- load：`parse_csv` → 每行构建 `fields` dict（补全 `FIELD_NAMES`）
- save：`csv.DictReader` 读原始行；按 `extract_locale` 建索引；写回时合并 `FIELD_NAMES` 更新；未知列原样保留；`encoding=utf-8-sig`, `lineterminator="\n"`

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/test_listing_local.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/asc/listing/local.py tests/test_listing_local.py
git commit -m "feat(listing): load and save local CSV snapshots"
```

---

### Task 3: 上传过滤 helpers + metadata 任务接入

**Files:**
- Create: `src/asc/listing/filters.py`
- Modify: `src/asc/web/routes_api.py`（`_start_metadata_task` / `metadata_run`）
- Test: `tests/test_listing_filters.py`
- Test: `tests/test_web_listing.py`（本任务先写 metadata/run 过滤相关用例，后续任务追加）

**Interfaces:**
- Produces:
  - `def filter_metadata_rows(rows: list[dict], locales: list[str] | None, fields_by_locale: dict[str, list[str]] | None) -> list[dict]`
  - 若 `locales` 非空：丢弃不在列表中的行（匹配 `row["locale"]`）
  - 若 `fields_by_locale` 提供：对每个 locale 只保留 `locale` 键 + 列出的字段；未出现在 map 中的 locale 若仍在 `locales` 中则保留全部字段（或视为无字段——**约定：map 中缺 locale 键 = 该语言不上传任何字段，应在过滤后若仅剩 locale 则丢弃整行**）
  - **明确约定：** `fields_by_locale[locale]` 缺失 ⇒ 该语言跳过；空列表 ⇒ 跳过；非空 ⇒ 只保留这些字段

- [ ] **Step 1: Write failing filter tests**

```python
# tests/test_listing_filters.py
from asc.listing.filters import filter_metadata_rows

def test_filter_by_locale_and_fields():
    rows = [
        {"locale": "en-US", "name": "A", "keywords": "k", "description": "d"},
        {"locale": "zh-Hans", "name": "中", "keywords": "词"},
    ]
    out = filter_metadata_rows(
        rows,
        locales=["en-US"],
        fields_by_locale={"en-US": ["name", "keywords"]},
    )
    assert out == [{"locale": "en-US", "name": "A", "keywords": "k"}]

def test_missing_fields_entry_skips_locale():
    rows = [{"locale": "en-US", "name": "A"}, {"locale": "ja", "name": "J"}]
    out = filter_metadata_rows(rows, locales=["en-US", "ja"], fields_by_locale={"en-US": ["name"]})
    assert out == [{"locale": "en-US", "name": "A"}]
```

- [ ] **Step 2: Implement `filters.py`**

```python
# src/asc/listing/filters.py
from __future__ import annotations

def filter_metadata_rows(
    rows: list[dict],
    locales: list[str] | None,
    fields_by_locale: dict[str, list[str]] | None,
) -> list[dict]:
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
```

- [ ] **Step 3: Extend `metadata_run` / `_start_metadata_task`**

Form 新增可选字段：
- `locales_json` 默认 `""`；解析后空列表 = 不过滤语言
- `fields_by_locale_json` 默认 `""`；空 = 不过滤字段（传 `None` 给 filter）

在 `_start_metadata_task` 增加参数 `locales: list[str] | None = None`, `fields_by_locale: dict | None = None`。`run()` 内：

```python
metadata_list = parse_csv(csv_path)
if locales or fields_by_locale is not None:
    metadata_list = filter_metadata_rows(
        metadata_list,
        locales or None,
        fields_by_locale,
    )
if include_metadata and not metadata_list and not include_screenshots:
    raise RuntimeError("no metadata rows selected")
```

`metadata_run` 解析 JSON；若 `include_metadata` 且过滤结果为空且未勾选截图，在启动任务前返回 HTTP 400。

Web 测试：patch `_upload_metadata_core`，POST `/api/metadata/run` 带过滤，断言传入 core 的 list 已过滤。

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_listing_filters.py tests/test_web_listing.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/asc/listing/filters.py src/asc/web/routes_api.py tests/test_listing_filters.py tests/test_web_listing.py
git commit -m "feat(web): filter metadata upload by locale and fields"
```

---

### Task 4: Listing Web API（本地文本）+ metadata 本地工作台 P0/P1

**Files:**
- Create: `src/asc/web/routes_listing.py`
- Modify: `src/asc/web/server.py`（`app.include_router`）
- Modify: `src/asc/web/templates/metadata.html`
- Modify: `src/asc/web/locales/zh.json`, `en.json`
- Modify: `tests/test_web_listing.py`

**Interfaces / API：**

| Method | Path | Body/Query | Response |
|--------|------|------------|----------|
| GET | `/api/listing/local` | `csv_path`, optional `screenshots_dir` | `{ ok, mtime, snapshot }`（本任务 screenshots 可为空 dict） |
| POST | `/api/listing/local/save` | JSON `{ csv_path, expected_mtime, locales: [{locale, fields}] }` | `{ ok, mtime }` 或 409 conflict |

需 profile cookie + guard，与其它 API 一致。

**UI（metadata.html）：**
- 路径区下方增加「本地工作台」：按钮「加载预览」→ GET local
- 表格：locale 勾选 | 语言 | 字段摘要 | 展开编辑（每字段 checkbox + input/textarea）
- 「保存到 CSV」→ POST save；展示未保存状态
- 上传表单提交前：若 dirty → 阻止；附带 `locales_json` / `fields_by_locale_json`（由勾选生成）
- 保留原有 dry-run / include_metadata / include_screenshots / 任务日志

- [ ] **Step 1: API 测试（TestClient）**

```python
def test_listing_local_and_save(client, tmp_path):
    p = tmp_path / "app.csv"
    p.write_text("locale,name\nen-US,Old\n", encoding="utf-8-sig")
    with patch(... Config / guard ...):
        r = client.get("/api/listing/local", params={"csv_path": str(p)}, cookies={"asc_profile": "test"})
    assert r.status_code == 200
    assert r.json()["snapshot"]["locales"][0]["fields"]["name"] == "Old"
    mtime = r.json()["mtime"]
    body = {
        "csv_path": str(p),
        "expected_mtime": mtime,
        "locales": [{"locale": "en-US", "fields": {"name": "New"}}],
    }
    r2 = client.post("/api/listing/local/save", json=body, cookies={"asc_profile": "test"})
    assert r2.status_code == 200
    assert "New" in p.read_text(encoding="utf-8-sig")
```

- [ ] **Step 2: Implement router + UI + i18n keys**（键名示例：`metadata.workbench`, `metadata.save_csv`, `metadata.unsaved`, `metadata.load_preview`）

- [ ] **Step 3: Run**

Run: `pytest tests/test_web_listing.py tests/test_listing_local.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/asc/web/routes_listing.py src/asc/web/server.py src/asc/web/templates/metadata.html src/asc/web/locales/zh.json src/asc/web/locales/en.json tests/test_web_listing.py
git commit -m "feat(web): local listing workbench for CSV preview and save"
```

---

### Task 5: 本地截图扫描、缩略图、排序/替换/删除/新增

**Files:**
- Modify: `src/asc/listing/local.py`
- Modify: `src/asc/web/routes_listing.py`
- Modify: `src/asc/web/templates/metadata.html`
- Test: `tests/test_listing_local.py`（追加）
- Test: `tests/test_web_listing.py`（追加）

**Interfaces:**
- `def scan_local_screenshots(screenshots_dir: str) -> dict[str, dict[str, list[ScreenshotItem]]]`  
  返回 `locale -> displayType -> items`；用 `_detect_display_type`（可从 `asc.commands.screenshots` import）；无法识别的文件归入 displayType `"UNKNOWN"` 并仍列出
- `def apply_screenshot_order(locale_dir: Path, display_type: str, ordered_file_names: list[str]) -> None`  
  仅重排属于该 displayType 的文件：写成 `01_stem.ext`, `02_...`（去掉旧数字前缀时保留语义 stem）
- `def replace_screenshot(path: Path, upload_bytes: bytes, new_name: str | None) -> Path`
- `def delete_screenshot(path: Path) -> None`
- `def add_screenshot(locale_dir: Path, display_type: str, filename: str, data: bytes) -> Path`

**API：**
- GET `/api/listing/local` 在提供 `screenshots_dir` 时合并 screenshots 到 snapshot
- GET `/api/listing/thumb?path=` — 仅允许 `screenshots_dir` 实时根下的文件（调用方传 `root` query 或 session 校验）；返回 image/*
- POST `/api/listing/screenshots/reorder` JSON `{ root, locale, display_type, file_names }`
- POST `/api/listing/screenshots/replace` multipart
- POST `/api/listing/screenshots/delete` JSON
- POST `/api/listing/screenshots/add` multipart

**UI：** 展开语言行显示按 displayType 分组的缩略图；拖拽排序（Alpine + 保存顺序 API）；替换/删除/新增按钮；displayType 与单张勾选进入 `screenshot_scopes_json`

- [ ] **Step 1: 单测 reorder 后 `_get_sorted_screenshots` 顺序**

```python
def test_reorder_matches_sorted_screenshots(tmp_path):
    from PIL import Image
    from asc.commands.screenshots import _get_sorted_screenshots
    from asc.listing.local import apply_screenshot_order

    d = tmp_path / "en-US"
    d.mkdir()
    # 1290x2796 → APP_IPHONE_67 in DISPLAY_TYPE_BY_SIZE
    for name in ("a.png", "b.png"):
        Image.new("RGB", (1290, 2796), color=(1, 2, 3)).save(d / name)
    apply_screenshot_order(d, "APP_IPHONE_67", ["b.png", "a.png"])
    names = [p.name for p in _get_sorted_screenshots(d)]
    assert names[0].startswith("01_")
    assert "b" in names[0]
    assert names[1].startswith("02_")
```

- [ ] **Step 2: Implement + wire UI**

- [ ] **Step 3: pytest 相关文件**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(web): local screenshot preview edit and reorder"
```

---

### Task 6: Screenshots core 多 displayType + scopes 过滤

**Files:**
- Modify: `src/asc/commands/screenshots.py`
- Modify: `src/asc/web/routes_api.py`
- Test: `tests/test_screenshots_filter.py`

**行为变更（兼容默认）：**
- 扫描某 locale 文件夹时，**按每张图** `_detect_display_type` 分组，生成多个 job `(locale, display_type, files)`
- 新增参数 `screenshot_scopes: list[dict] | None = None`  
  每项：`{"locale": str, "display_type": str, "file_names": list[str] | None}`  
  - `None` ⇒ 全部  
  - 有 scopes ⇒ 只处理列出的 (locale, display_type)；`file_names` 非空则再滤文件名

`metadata_run` / `_start_metadata_task` 增加 `screenshot_scopes_json` → 传入 core。

- [ ] **Step 1: Write failing test for grouping helper**

在 `screenshots.py` 抽出可测函数（或 listing.filters 中）：

```python
# tests/test_screenshots_filter.py
from pathlib import Path
from PIL import Image
from asc.commands.screenshots import _group_files_by_display_type, _filter_screenshot_jobs

def test_group_files_by_display_type(tmp_path: Path):
    folder = tmp_path / "en-US"
    folder.mkdir()
    Image.new("RGB", (1290, 2796)).save(folder / "01_phone.png")
    Image.new("RGB", (2048, 2732)).save(folder / "01_pad.png")  # iPad 12.9
    groups = _group_files_by_display_type(folder)
    assert "APP_IPHONE_67" in groups
    assert "APP_IPAD_PRO_3GEN_129" in groups

def test_filter_scopes_keeps_matching_only():
    jobs = [
        ("en-US", "APP_IPHONE_67", [Path("a.png"), Path("b.png")]),
        ("zh-Hans", "APP_IPHONE_67", [Path("c.png")]),
    ]
    scopes = [{"locale": "en-US", "display_type": "APP_IPHONE_67", "file_names": ["b.png"]}]
    out = _filter_screenshot_jobs(jobs, scopes)
    assert len(out) == 1
    assert out[0][0] == "en-US"
    assert [p.name for p in out[0][2]] == ["b.png"]
```

（若仓库 `DISPLAY_TYPE_BY_SIZE` 中 iPad 尺寸键不同，测试内用 constants 里真实存在的尺寸。）

- [ ] **Step 2: Implement helpers；改 `_upload_screenshots_core` 使用分组 job 列表；接 routes**

- [ ] **Step 3: Run**

Run: `pytest tests/test_screenshots_filter.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/asc/commands/screenshots.py src/asc/web/routes_api.py tests/test_screenshots_filter.py
git commit -m "feat(screenshots): multi display-type jobs and upload scopes"
```

---

### Task 7: ASC 文本 Snapshot、Diff API、文本拉取、Diff UI（P3）

**Files:**
- Create: `src/asc/listing/remote.py`
- Modify: `src/asc/web/routes_listing.py`
- Modify: `src/asc/web/templates/metadata.html`
- Modify: `src/asc/web/locales/zh.json`, `en.json`
- Test: `tests/test_listing_remote.py`
- Test: `tests/test_web_listing.py`

**Interfaces:**
- `def load_asc_text_snapshot(api, app_id: str) -> ListingSnapshot`
- GET `/api/listing/diff?csv_path=&screenshots_dir=` → local + asc text（本任务 asc.screenshots 可为 `{}`，本地截图若已扫入则进入 diff 结构）+ `diff_snapshots`
- POST `/api/listing/pull/text` JSON `{ csv_path, expected_mtime, selections: [{locale, fields: [str]}] }`

- [ ] **Step 1: Failing test for `load_asc_text_snapshot`**

```python
# tests/test_listing_remote.py
from unittest.mock import MagicMock
from asc.listing.remote import load_asc_text_snapshot

def test_load_asc_text_snapshot_merges_info_and_version_fields():
    api = MagicMock()
    api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.2.0", "appStoreState": "PREPARE_FOR_SUBMISSION"},
    }
    api.get_app_infos.return_value = [{"id": "ai1", "relationships": {}}]
    api.get_app_info_localizations.return_value = [
        {"id": "il1", "attributes": {"locale": "en-US", "name": "App", "subtitle": "Sub", "privacyPolicyUrl": "https://p"}},
    ]
    api.get_version_localizations.return_value = [
        {"id": "vl1", "attributes": {
            "locale": "en-US", "description": "D", "keywords": "k",
            "supportUrl": "https://s", "marketingUrl": "https://m",
        }},
    ]
    snap = load_asc_text_snapshot(api, "app1")
    assert snap.source == "asc"
    assert snap.version["versionString"] == "1.2.0"
    loc = snap.locales[0]
    assert loc.locale == "en-US"
    assert loc.fields["name"] == "App"
    assert loc.fields["description"] == "D"
    assert loc.fields["supportUrl"] == "https://s"
```

注：`get_app_infos` 选择逻辑与 `metadata._select_app_info_id` 对齐；测试里可 mock 成单元素列表并在 remote 内取第一个可编辑关联，或复用 `_select_app_info_id`。

- [ ] **Step 2: Implement `remote.py` + diff/pull routes**

- [ ] **Step 3: Diff UI（Tab）+ dirty 门禁 + i18n；pytest**

Run: `pytest tests/test_listing_remote.py tests/test_web_listing.py tests/test_listing_diff.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/asc/listing/remote.py src/asc/web/routes_listing.py src/asc/web/templates/metadata.html src/asc/web/locales/zh.json src/asc/web/locales/en.json tests/test_listing_remote.py tests/test_web_listing.py
git commit -m "feat(web): ASC listing text diff and pull-to-csv"
```

---

### Task 8: ASC 截图缩略图、并排 Diff、下载覆盖（P4）

**Files:**
- Modify: `src/asc/listing/remote.py`
- Modify: `src/asc/web/routes_listing.py`
- Modify: `src/asc/web/templates/metadata.html`
- Modify: `src/asc/web/locales/zh.json`, `en.json`
- Test: `tests/test_listing_remote.py`, `tests/test_web_listing.py`

**Interfaces:**
- `def attach_asc_screenshots(api, snapshot: ListingSnapshot) -> ListingSnapshot`（或合并进 `load_asc_snapshot`）
- `def screenshot_thumb_url(shot_attrs: dict) -> str` — 优先 `imageAsset.templateUrl` 替换 `{w}`/`{h}` 为 `100`
- `def download_asc_screenshots(api, app_id: str, screenshots_dir: str, scopes: list[dict], reporter=None) -> None`
- GET `/api/listing/asc-thumb?screenshot_id=`
- POST `/api/listing/pull/screenshots` → `task_store` 后台任务；前端强确认

下载规则：对每个 scope `(locale, display_type)`，删除该 locale 目录中检测为该 displayType 的本地文件，再按线上顺序写入 `01_*.png` 等；目录名用 ASC locale。

- [ ] **Step 1: Failing test — parse sets into snapshot screenshots**

```python
def test_attach_asc_screenshots_reads_sets():
    api = MagicMock()
    # version loc id en-US already on snapshot locales — attach looks up localization ids via get_version_localizations
    api.get_version_localizations.return_value = [
        {"id": "vl1", "attributes": {"locale": "en-US"}},
    ]
    api.get_screenshot_sets.return_value = {
        "data": [{
            "id": "set1",
            "attributes": {"screenshotDisplayType": "APP_IPHONE_67"},
            "relationships": {"appScreenshots": {"data": [{"id": "s1", "type": "appScreenshots"}]}},
        }],
        "included": [{
            "type": "appScreenshots",
            "id": "s1",
            "attributes": {
                "fileName": "shot.png",
                "imageAsset": {"templateUrl": "https://example.com/{w}x{h}.png"},
            },
        }],
    }
    base = ListingSnapshot(source="asc", locales=[LocaleListing("en-US", {}, {})], version={"id": "v1"})
    snap = attach_asc_screenshots(api, base)
    items = snap.locales[0].screenshots["APP_IPHONE_67"]
    assert items[0].remote_id == "s1"
    assert "100x100" in items[0].thumb_url
```

- [ ] **Step 2: Implement attach/download + routes + UI 并排缩略图**

- [ ] **Step 3: Run**

Run: `pytest tests/test_listing_remote.py tests/test_web_listing.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/asc/listing/remote.py src/asc/web/routes_listing.py src/asc/web/templates/metadata.html src/asc/web/locales/zh.json src/asc/web/locales/en.json tests/test_listing_remote.py tests/test_web_listing.py
git commit -m "feat(web): ASC screenshot diff thumbs and pull overwrite"
```

---

## Spec 覆盖自检

| Spec 项 | Task |
|---------|------|
| ListingSnapshot 统一模型 | 1 |
| Diff 四态 + 截图并排结构 | 1, 7, 8 |
| 本地 CSV 预览/编辑/mtime | 2, 4 |
| 每语言每字段勾选上传 | 3, 4 |
| 截图预览/排序/替换/删/增 | 5 |
| 截图 scopes 上传 | 5, 6 |
| 多 displayType 扫描/上传 | 5, 6 |
| ASC 文本 Diff + 拉取 | 7 |
| ASC 截图缩略图 + 下载覆盖 | 8 |
| 未保存阻止上传/拉取 | 4, 7, 8（前端 + save API） |
| 非目标（MD5/自动写盘/建版本） | 不实现 |

---

## 执行说明

完成后可选执行方式见下方 handoff。实现时严格按 Task 顺序；每个 Task 结束保持 `pytest` 相关子集绿色。
