# CSV English Headers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make metadata CSV default headers English (ASC API style), normalize all parsed rows to canonical keys, and keep Chinese headers working as read-only aliases — including templates, tests, Web UI, and stable docs.

**Architecture:** Add a single alias map + `canonicalize_csv_header()` in `constants.py`. `parse_csv()` is the only normalization point: strip headers, map to canonical keys with English-overwrite conflict rules, then `extract_locale` on `locale`. All consumers (`metadata.py`, tests, templates, docs) use English keys only.

**Tech Stack:** Python 3.9+, `csv.DictReader`, pytest, existing Typer CLI / FastAPI Web UI, Markdown docs.

## Global Constraints

- Canonical headers (exact, case-sensitive): `locale`, `name`, `subtitle`, `description`, `keywords`, `supportUrl`, `marketingUrl`, `privacyPolicyUrl`
- Chinese aliases remain readable forever; no migration CLI; `init` always emits English headers
- Unknown columns are dropped (not passed through)
- Conflict rule: scan columns left-to-right; set if unset; overwrite only when the current header is the exact English canonical name
- Locale cell formats unchanged (`简体中文(zh-Hans)`, bare `en-US`, etc.)
- Spec: `docs/specs/2026-07-29-csv-english-headers-design.md`

## File map

| Path | Responsibility |
|------|----------------|
| Modify `src/asc/constants.py` | `CSV_HEADER_ALIASES`, `canonicalize_csv_header()` |
| Modify `src/asc/utils.py` | `parse_csv()` normalization to canonical keys |
| Modify `src/asc/commands/metadata.py` | Read English keys only; update docstrings |
| Modify `src/asc/commands/app_config.py` | English `_CSV_TEMPLATE` |
| Modify `data/appstore_info.csv` | English header row (example download source) |
| Modify Web templates | `metadata.html`, `profiles.html` column docs |
| Modify docs | tutorials 02 (en/zh), ARCHITECTURE, CLAUDE, README if needed |
| Modify tests | `test_constants`, `test_utils`, `test_metadata`, `test_init_cmd`, `test_web_server` |

---

### Task 1: Header alias map + canonicalize helper

**Files:**
- Modify: `src/asc/constants.py`
- Modify: `tests/test_constants.py`

**Interfaces:**
- Produces:
  - `CSV_HEADER_ALIASES: dict[str, str]` — maps every accepted header (including English canonical names) → canonical name
  - `canonicalize_csv_header(raw: str) -> str | None` — strip / strip quotes, lookup in map; unknown → `None`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_constants.py`:

```python
from asc.constants import CSV_HEADER_ALIASES, canonicalize_csv_header


def test_canonicalize_english_headers():
    assert canonicalize_csv_header("locale") == "locale"
    assert canonicalize_csv_header("name") == "name"
    assert canonicalize_csv_header("supportUrl") == "supportUrl"
    assert canonicalize_csv_header("privacyPolicyUrl") == "privacyPolicyUrl"


def test_canonicalize_chinese_aliases():
    assert canonicalize_csv_header("语言") == "locale"
    assert canonicalize_csv_header("应用名称") == "name"
    assert canonicalize_csv_header("副标题") == "subtitle"
    assert canonicalize_csv_header("长描述") == "description"
    assert canonicalize_csv_header("描述") == "description"
    assert canonicalize_csv_header("关键词") == "keywords"
    assert canonicalize_csv_header("关键字") == "keywords"
    assert canonicalize_csv_header("技术支持链接") == "supportUrl"
    assert canonicalize_csv_header("技术支持网址") == "supportUrl"
    assert canonicalize_csv_header("营销网站") == "marketingUrl"
    assert canonicalize_csv_header("营销网址") == "marketingUrl"
    assert canonicalize_csv_header("隐私政策网址") == "privacyPolicyUrl"
    assert canonicalize_csv_header("隐私政策链接") == "privacyPolicyUrl"
    assert canonicalize_csv_header("隐私政策URL") == "privacyPolicyUrl"


def test_canonicalize_strips_whitespace_and_quotes():
    assert canonicalize_csv_header('  "语言"  ') == "locale"
    assert canonicalize_csv_header(" name ") == "name"


def test_canonicalize_unknown_and_wrong_case_return_none():
    assert canonicalize_csv_header("unknown") is None
    assert canonicalize_csv_header("SupportUrl") is None  # case-sensitive
    assert canonicalize_csv_header("") is None


def test_csv_header_aliases_cover_all_canonicals():
    canonicals = {
        "locale", "name", "subtitle", "description", "keywords",
        "supportUrl", "marketingUrl", "privacyPolicyUrl",
    }
    assert canonicals <= set(CSV_HEADER_ALIASES.values())
    for c in canonicals:
        assert CSV_HEADER_ALIASES[c] == c
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_constants.py::test_canonicalize_english_headers tests/test_constants.py::test_canonicalize_chinese_aliases -v`

Expected: FAIL (ImportError or attribute missing)

- [ ] **Step 3: Implement mapping + helper**

Append to `src/asc/constants.py`:

```python
# Metadata CSV headers: English canonical (ASC API style) + Chinese aliases.
# Every key maps to its canonical name; unknown headers are rejected by canonicalize.
CSV_HEADER_ALIASES: dict[str, str] = {
    # canonical → self
    "locale": "locale",
    "name": "name",
    "subtitle": "subtitle",
    "description": "description",
    "keywords": "keywords",
    "supportUrl": "supportUrl",
    "marketingUrl": "marketingUrl",
    "privacyPolicyUrl": "privacyPolicyUrl",
    # Chinese aliases
    "语言": "locale",
    "应用名称": "name",
    "副标题": "subtitle",
    "长描述": "description",
    "描述": "description",
    "关键词": "keywords",
    "关键字": "keywords",
    "技术支持链接": "supportUrl",
    "技术支持网址": "supportUrl",
    "营销网站": "marketingUrl",
    "营销网址": "marketingUrl",
    "隐私政策网址": "privacyPolicyUrl",
    "隐私政策链接": "privacyPolicyUrl",
    "隐私政策URL": "privacyPolicyUrl",
}


def canonicalize_csv_header(raw: str) -> str | None:
    """Map a CSV header to its canonical English key, or None if unknown."""
    if raw is None:
        return None
    cleaned = raw.strip().strip('"').strip("'").strip()
    if not cleaned:
        return None
    return CSV_HEADER_ALIASES.get(cleaned)
```

Note: for Python 3.9 compatibility, if the file does not already use `from __future__ import annotations`, use `Optional[str]` instead of `str | None`. Check the top of `constants.py` and match existing style (`Optional[str]` from `typing` if needed).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_constants.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/constants.py tests/test_constants.py
git commit -m "$(cat <<'EOF'
feat(csv): add English header aliases and canonicalize helper

Centralize ASC-style canonical CSV columns and Chinese aliases
so parse_csv can normalize headers in one place.

EOF
)"
```

---

### Task 2: Normalize `parse_csv` + sample data + utils tests

**Files:**
- Modify: `src/asc/utils.py` (`parse_csv`)
- Modify: `tests/test_utils.py`
- Modify: `data/appstore_info.csv`

**Interfaces:**
- Consumes: `canonicalize_csv_header` from `asc.constants`
- Produces: `parse_csv(csv_path: str) -> list[dict]` where each dict uses only canonical keys; `locale` required

- [ ] **Step 1: Rewrite / extend failing utils tests**

Replace Chinese-key assertions in `tests/test_utils.py` and add new cases. Update imports if needed.

```python
def test_parse_real_csv_locale_codes():
    rows = parse_csv(str(DATA_CSV))
    locales = [r["locale"] for r in rows]
    assert "zh-Hans" in locales
    assert "en-US" in locales


def test_parse_real_csv_app_name_present():
    rows = parse_csv(str(DATA_CSV))
    for row in rows:
        assert "name" in row
        assert row["name"]


def test_parse_csv_with_bom(tmp_path):
    csv_file = tmp_path / "test.csv"
    content = "语言,应用名称\n简体中文(zh-Hans),测试应用\n"
    csv_file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
    rows = parse_csv(str(csv_file))
    assert len(rows) == 1
    assert rows[0]["locale"] == "zh-Hans"
    assert rows[0]["name"] == "测试应用"


def test_parse_csv_skips_rows_without_locale(tmp_path):
    csv_file = tmp_path / "test.csv"
    content = "语言,应用名称\n,无语言行\n英文(en-US),有语言行\n"
    csv_file.write_text(content, encoding="utf-8")
    rows = parse_csv(str(csv_file))
    assert len(rows) == 1
    assert rows[0]["locale"] == "en-US"


def test_parse_csv_english_headers(tmp_path):
    csv_file = tmp_path / "en.csv"
    csv_file.write_text(
        "locale,name,subtitle,description,keywords,supportUrl,marketingUrl,privacyPolicyUrl\n"
        "en-US,App,Sub,Desc,kw,https://s.example,https://m.example,https://p.example\n",
        encoding="utf-8",
    )
    rows = parse_csv(str(csv_file))
    assert rows[0] == {
        "locale": "en-US",
        "name": "App",
        "subtitle": "Sub",
        "description": "Desc",
        "keywords": "kw",
        "supportUrl": "https://s.example",
        "marketingUrl": "https://m.example",
        "privacyPolicyUrl": "https://p.example",
    }


def test_parse_csv_mixed_headers(tmp_path):
    csv_file = tmp_path / "mixed.csv"
    csv_file.write_text(
        "locale,应用名称,keywords\nzh-Hans,测试,kw1\n",
        encoding="utf-8",
    )
    rows = parse_csv(str(csv_file))
    assert rows[0]["locale"] == "zh-Hans"
    assert rows[0]["name"] == "测试"
    assert rows[0]["keywords"] == "kw1"


def test_parse_csv_english_overrides_chinese_alias(tmp_path):
    csv_file = tmp_path / "conflict.csv"
    # Chinese first, English later → English wins
    csv_file.write_text(
        "关键字,keywords,语言\nchinese-kw,english-kw,en-US\n",
        encoding="utf-8",
    )
    rows = parse_csv(str(csv_file))
    assert rows[0]["keywords"] == "english-kw"


def test_parse_csv_first_chinese_alias_wins_when_no_english(tmp_path):
    csv_file = tmp_path / "alias_conflict.csv"
    csv_file.write_text(
        "关键词,关键字,语言\nfirst,second,en-US\n",
        encoding="utf-8",
    )
    rows = parse_csv(str(csv_file))
    assert rows[0]["keywords"] == "first"


def test_parse_csv_drops_unknown_columns(tmp_path):
    csv_file = tmp_path / "extra.csv"
    csv_file.write_text(
        "locale,name,extra_col\nen-US,App,ignored\n",
        encoding="utf-8",
    )
    rows = parse_csv(str(csv_file))
    assert rows[0] == {"locale": "en-US", "name": "App"}
```

Also keep `test_parse_real_csv_row_count` unchanged (still expects 2 rows).

- [ ] **Step 2: Run new tests to verify failure on current code**

Run: `pytest tests/test_utils.py::test_parse_csv_english_headers tests/test_utils.py::test_parse_real_csv_locale_codes -v`

Expected: FAIL (`KeyError: 'locale'` or missing fields)

- [ ] **Step 3: Implement `parse_csv` normalization**

Replace `parse_csv` in `src/asc/utils.py` with:

```python
from asc.constants import CSV_LOCALE_TO_ASC, canonicalize_csv_header, normalize_locale_code


def parse_csv(csv_path: str) -> list[dict]:
    """Parse metadata CSV; return rows keyed by English canonical headers."""
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        raw_headers = reader.fieldnames or []

        # (original DictReader key, canonical key or None)
        header_plan: list[tuple[str, str | None]] = []
        for h in raw_headers:
            stripped = (h or "").strip().strip('"')
            if not stripped:
                header_plan.append((h, None))
                continue
            header_plan.append((h, canonicalize_csv_header(stripped)))

        results = []
        for row in reader:
            mapped: dict[str, str] = {}
            for orig_key, canonical in header_plan:
                if canonical is None:
                    continue
                val = row.get(orig_key)
                if not val or not str(val).strip():
                    continue
                value = str(val).strip()
                # Set if unset; overwrite only when this column is the English canonical name
                if canonical not in mapped or orig_key.strip().strip('"') == canonical:
                    mapped[canonical] = value

            if "locale" not in mapped or not mapped["locale"]:
                continue
            mapped["locale"] = extract_locale(mapped["locale"])
            results.append(mapped)

    return results
```

Fix type hints for 3.9 if the module lacks `from __future__ import annotations` (it already has it).

Overwrite conflict check: `orig_key` from DictReader may include whitespace/quotes — use the same cleaned form as canonicalize input:

```python
clean_orig = (orig_key or "").strip().strip('"').strip("'").strip()
if canonical not in mapped or clean_orig == canonical:
    mapped[canonical] = value
```

- [ ] **Step 4: Update sample CSV to English headers**

Replace `data/appstore_info.csv` header (keep row data; adjust cells as needed):

```csv
locale,name,subtitle,description,keywords,supportUrl,marketingUrl
简体中文(zh-Hans),应用名称（1212219）,副标题,长描述长描述长描述长描述长描述长描述长描述,关键字,,
英文(en-US),app name 8393939,subtitle,subtitlesubtitlesubtitlesubtitlesubtitlesubtitlesubtitle,keyword,,
```

(Match existing cell content; trailing empty optional columns OK.)

- [ ] **Step 5: Run utils tests**

Run: `pytest tests/test_utils.py -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/asc/utils.py tests/test_utils.py data/appstore_info.csv
git commit -m "$(cat <<'EOF'
feat(csv): normalize parse_csv to English canonical keys

Map Chinese and English headers at parse time, drop unknown
columns, and switch the sample CSV to English defaults.

EOF
)"
```

---

### Task 3: Metadata consumers use canonical keys

**Files:**
- Modify: `src/asc/commands/metadata.py` (field reads ~102–153 and docstrings ~421–637)
- Modify: `tests/test_metadata.py`
- Modify: `tests/test_web_server.py` (metadata fixture dicts that call `_upload_metadata_core`)

**Interfaces:**
- Consumes: rows from `parse_csv` with keys `locale`, `name`, `subtitle`, `description`, `keywords`, `supportUrl`, `marketingUrl`, `privacyPolicyUrl`
- Produces: unchanged ASC API update behavior

- [ ] **Step 1: Update metadata tests to English keys first**

In `tests/test_metadata.py`, change every metadata dict, e.g.:

```python
metadata = [{"locale": "zh-Hans", "name": "测试", "description": "描述"}]
# ...
metadata = [{"locale": "zh-Hans", "name": "新名称", "subtitle": "新副标题"}]
# ...
metadata = [{"locale": "en-US", "name": "New Name"}]
# ...
metadata = [{"locale": "zh-Hans", "description": "新描述", "keywords": "关键词1,关键词2"}]
# ...
metadata = [{"locale": "zh-Hans", "description": "描述", "keywords": "kw1"}]
# ...
metadata = [{
    "locale": "zh-Hans",
    "name": "新名称",
    "subtitle": "新副标题",
    "description": "新描述",
    "keywords": "kw1,kw2",
}]
```

In `tests/test_web_server.py`, update the progress-related metadata fixture (~1596):

```python
{"locale": "en-US", "name": "Test", "description": "desc"},
{"locale": "zh-CN", "name": "测试", "description": "描述"},
```

(Do **not** change progress message strings like `元数据 5/11 语言` — those are UI copy, not CSV headers.)

- [ ] **Step 2: Run metadata tests — expect fail**

Run: `pytest tests/test_metadata.py -v`

Expected: FAIL / empty updates (still reading Chinese keys)

- [ ] **Step 3: Update `_upload_metadata_core` field access**

In `src/asc/commands/metadata.py`, replace Chinese reads:

```python
csv_locale = meta["locale"]
name = meta.get("name", "")
subtitle = meta.get("subtitle", "")
privacy_policy_url = meta.get("privacyPolicyUrl", "")
description = meta.get("description", "")
keywords = meta.get("keywords", "")
support_url = meta.get("supportUrl", "")
marketing_url = meta.get("marketingUrl", "")
```

Remove the Chinese `or meta.get(...)` alias chains — aliases are handled in `parse_csv` only. Console print labels may stay Chinese (user-facing log language); only dict keys change.

Update docstrings / help text that list column names, e.g.:

```text
The CSV should have columns like: locale, name, subtitle, description, keywords.
Chinese headers (语言, 应用名称, …) are still accepted.
```

Similarly for keywords / support / marketing / privacy command docstrings: mention English canonical names and that Chinese aliases still work.

- [ ] **Step 4: Run consumer tests**

Run: `pytest tests/test_metadata.py tests/test_web_server.py::test_metadata_progress_output -v`  
(Use the actual progress test name if different; also run any test that builds metadata dicts.)

Broader: `pytest tests/test_metadata.py tests/test_utils.py tests/test_web_server.py -k "metadata or csv or examples_csv" -v`

Expected: PASS for metadata/utils; `test_examples_csv_download` may still fail until Task 2 sample CSV is English (should already be) — if it asserts `"语言"`, fix in Task 5.

- [ ] **Step 5: Commit**

```bash
git add src/asc/commands/metadata.py tests/test_metadata.py tests/test_web_server.py
git commit -m "$(cat <<'EOF'
feat(metadata): read canonical English CSV keys only

Rely on parse_csv normalization; drop Chinese key lookups
from the upload path and update unit fixtures.

EOF
)"
```

---

### Task 4: `asc init` English CSV template

**Files:**
- Modify: `src/asc/commands/app_config.py` (`_CSV_TEMPLATE` ~631–635)
- Modify: `tests/test_init_cmd.py` (`test_init_csv_has_header_row`)

**Interfaces:**
- Produces: new AppStore scaffolds with English header CSV

- [ ] **Step 1: Update failing init assertion**

In `tests/test_init_cmd.py`:

```python
def test_init_csv_has_header_row(xcode_project):
    """Generated appstore_info.csv has the required English header columns."""
    runner.invoke(app, ["init", "--path", str(xcode_project)])
    content = (xcode_project / "AppStore" / "data" / "appstore_info.csv").read_text()
    assert "locale" in content
    assert "name" in content
    assert "keywords" in content
    assert "语言" not in content.splitlines()[0]
```

- [ ] **Step 2: Run test — expect fail**

Run: `pytest tests/test_init_cmd.py::test_init_csv_has_header_row -v`

Expected: FAIL

- [ ] **Step 3: Replace `_CSV_TEMPLATE`**

In `src/asc/commands/app_config.py`:

```python
_CSV_TEMPLATE = (
    "locale,name,subtitle,description,keywords,supportUrl,marketingUrl\n"
    'zh-Hans,应用名称,副标题,"在这里填写应用的完整描述","关键词1,关键词2",,\n'
    'en-US,App Name,Subtitle,"Write your full app description here","keyword1,keyword2",,\n'
)
```

- [ ] **Step 4: Run init tests**

Run: `pytest tests/test_init_cmd.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/commands/app_config.py tests/test_init_cmd.py
git commit -m "$(cat <<'EOF'
feat(init): scaffold metadata CSV with English headers

New AppStore templates default to ASC-style column names.

EOF
)"
```

---

### Task 5: Web UI copy + example CSV contract

**Files:**
- Modify: `src/asc/web/templates/metadata.html` (~46–48)
- Modify: `src/asc/web/templates/profiles.html` (~167)
- Modify: `tests/test_web_server.py` (`test_examples_csv_download`, any page text asserting `语言` as CSV column)

**Interfaces:**
- Example download still serves `data/appstore_info.csv` (already English after Task 2)

- [ ] **Step 1: Update web tests**

```python
def test_examples_csv_download(client):
    resp = client.get("/api/examples/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "appstore_info_example.csv" in resp.headers.get("content-disposition", "")
    assert "locale" in resp.text
    assert "name" in resp.text
```

If a template smoke test asserts `"语言" in resp.text` for metadata/profiles pages and that string only referred to CSV columns, change to assert `"locale"` (and optionally keep a compatibility note string like `语言` if the page documents Chinese aliases).

- [ ] **Step 2: Run — expect fail on page copy if still Chinese-only**

Run: `pytest tests/test_web_server.py::test_examples_csv_download -v`

- [ ] **Step 3: Update templates**

In `metadata.html`, change required/optional column docs to English, add one line for Chinese compatibility, e.g.:

```html
<p class="text-obsidian-200"><span class="font-medium text-obsidian-100">Required columns:</span>
<code ...>locale</code> <code ...>name</code> <code ...>subtitle</code>
<code ...>description</code> <code ...>keywords</code></p>
<p class="text-obsidian-200"><span class="font-medium text-obsidian-100">Optional:</span>
<code ...>supportUrl</code> <code ...>marketingUrl</code> <code ...>privacyPolicyUrl</code></p>
<p class="text-obsidian-200"><span class="font-medium text-obsidian-100">locale format:</span>
<code ...>简体中文(zh-Hans)</code> or <code ...>en-US</code></p>
<p class="text-obsidian-200 text-xs">Chinese headers (语言, 应用名称, 副标题, 长描述, 关键字, …) are still accepted.</p>
```

Match existing Chinese UI voice if the page is otherwise Chinese — use Chinese labels for the sentence (“必填列” etc.) but English column codes inside `<code>`.

Same for `profiles.html` required-columns blurb.

- [ ] **Step 4: Run web tests**

Run: `pytest tests/test_web_server.py -k "csv or metadata or profiles" -v`

Expected: PASS for updated contracts

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/templates/metadata.html src/asc/web/templates/profiles.html tests/test_web_server.py
git commit -m "$(cat <<'EOF'
docs(web): document English CSV headers with Chinese aliases

Align metadata/profiles help and example CSV assertions with
canonical column names.

EOF
)"
```

---

### Task 6: Stable documentation

**Files:**
- Modify: `docs/tutorials/02-metadata-and-screenshots.md`
- Modify: `docs/tutorials/02-metadata-and-screenshots.zh-CN.md`
- Modify: `ARCHITECTURE.md` (CSV example ~405)
- Modify: `CLAUDE.md` (Data Files CSV column list ~137)
- Modify: `README.md` / `README.zh-CN.md` only if they hardcode Chinese column names (today they mostly link to tutorials)

**Interfaces:** None (docs only)

- [ ] **Step 1: Update English tutorial**

In `docs/tutorials/02-metadata-and-screenshots.md`:

- Required column: `locale`
- Table of columns using English names; add a subsection **Compatible Chinese headers** listing the alias map from the spec
- Example CSV:

```csv
locale,name,subtitle,description,keywords
简体中文(zh-Hans),应用名称,副标题,完整描述,keyword1,keyword2
English(en-US),App Name,Subtitle,Full description,keyword1,keyword2
```

- FAQ: refer to `locale` column (mention `语言` still works)

- [ ] **Step 2: Update Chinese tutorial the same way**

In `.zh-CN.md`: default examples and table use English column names; include 兼容中文列名对照表. Do not teach Chinese-only as the primary format.

- [ ] **Step 3: Update ARCHITECTURE + CLAUDE**

`ARCHITECTURE.md` example line → English headers.

`CLAUDE.md` Data Files bullet → English required/optional columns + note that Chinese aliases are accepted via `CSV_HEADER_ALIASES`.

- [ ] **Step 4: Quick grep for leftover primary docs**

Run:

```bash
rg -n '语言,应用名称|`语言`|`应用名称`|`长描述`|`关键字`' \
  README.md README.zh-CN.md ARCHITECTURE.md CLAUDE.md \
  docs/tutorials/02-metadata-and-screenshots.md \
  docs/tutorials/02-metadata-and-screenshots.zh-CN.md \
  src/asc/commands/metadata.py \
  src/asc/web/templates/metadata.html \
  src/asc/web/templates/profiles.html
```

Expected: remaining Chinese only in explicit “compatibility / alias” sections, not as the sole default example.

- [ ] **Step 5: Full regression**

Run: `pytest tests/test_constants.py tests/test_utils.py tests/test_metadata.py tests/test_init_cmd.py tests/test_web_server.py -q`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add docs/tutorials/02-metadata-and-screenshots.md \
  docs/tutorials/02-metadata-and-screenshots.zh-CN.md \
  ARCHITECTURE.md CLAUDE.md README.md README.zh-CN.md
git commit -m "$(cat <<'EOF'
docs: document English CSV headers as default

Update tutorials, architecture notes, and CLAUDE data-file
docs; keep Chinese column names as documented aliases.

EOF
)"
```

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|---|---|
| ASC-style canonical names | Task 1 |
| Chinese read aliases | Task 1–2 |
| Normalize only in `parse_csv` | Task 2 |
| English wins / left-first alias conflict | Task 2 tests + impl |
| Drop unknown columns | Task 2 |
| `metadata.py` English-only keys | Task 3 |
| `init` / sample CSV English | Task 2 + 4 |
| Web UI + example download | Task 5 |
| README / tutorials / ARCHITECTURE / CLAUDE | Task 6 |
| No migration CLI / no ASC_LANG template switch | Global constraints (out of scope) |

No TBD placeholders. Interface names consistent: `canonicalize_csv_header`, `CSV_HEADER_ALIASES`, canonical key set matches spec.
