# Vendor Web UI Assets Locally Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve fonts, Tailwind CSS, htmx, and Alpine from `/static` so ASC Web UI works offline with no CDN requests.

**Architecture:** Build a committed `tailwind.css` via Tailwind CLI from template class scans; vendor pinned htmx/Alpine JS and woff2 fonts under `src/asc/web/static/`; point `base.html` at local URLs with `asset_version` cache-busting.

**Tech Stack:** FastAPI StaticFiles, Tailwind CSS v3 CLI (compatible with current utility classes), Jinja templates, pytest TestClient

## Global Constraints

- No CDN URLs remain in served HTML for UI assets (`cdn.tailwindcss.com`, `fonts.googleapis.com`, `fonts.gstatic.com`, `unpkg.com`)
- Pin htmx **1.9.12** and a concrete Alpine **3.x** release (not floating `3.x.x`)
- Commit generated/vendored binaries so `pip install` users need no Node rebuild
- Do not redesign pages; do not change dashboard.css / task-log-drawer.css ownership
- Preserve obsidian/amber theme and DM Sans / Fira Code / Instrument Serif fonts
- Keep `?v={{ asset_version }}` on static asset URLs

---

## File map

| Path | Responsibility |
|------|----------------|
| `src/asc/web/input.css` | Tailwind `@tailwind` entry |
| `src/asc/web/tailwind.config.js` | content globs + theme extend (from current base.html) |
| `scripts/build_web_assets.sh` | Download/vendor helpers + run Tailwind build |
| `src/asc/web/static/tailwind.css` | Built CSS (committed) |
| `src/asc/web/static/fonts.css` | `@font-face` rules |
| `src/asc/web/static/fonts/*.woff2` | Font binaries |
| `src/asc/web/static/fonts/SOURCES.md` | License + upstream notes |
| `src/asc/web/static/vendor/htmx-1.9.12.min.js` | Vendored htmx |
| `src/asc/web/static/vendor/alpine-*.min.js` | Vendored Alpine (exact pin in filename) |
| `src/asc/web/templates/base.html` | Local `<link>` / `<script>` only |
| `tests/test_web_server.py` | No-CDN + static 200 assertions |
| `README.md` / `README.zh-CN.md` | One-line rebuild note for contributors |

---

### Task 1: Failing contract tests for no-CDN assets

**Files:**
- Modify: `tests/test_web_server.py`
- Test: same

**Interfaces:**
- Produces: `test_base_layout_has_no_cdn_asset_urls`, `test_vendored_web_assets_are_served`

- [ ] **Step 1: Write failing tests**

```python
def test_base_layout_has_no_cdn_asset_urls(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    for needle in (
        "cdn.tailwindcss.com",
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "unpkg.com",
    ):
        assert needle not in body
    assert "/static/fonts.css?v=" in body
    assert "/static/tailwind.css?v=" in body
    assert "/static/vendor/htmx-1.9.12.min.js" in body
    assert "/static/vendor/alpine-" in body and ".min.js" in body


def test_vendored_web_assets_are_served(client):
    for path in (
        "/static/fonts.css",
        "/static/tailwind.css",
        "/static/vendor/htmx-1.9.12.min.js",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
    # Alpine filename discovered from homepage or glob; assert 200 for the linked file
    home = client.get("/").text
    import re
    m = re.search(r'/static/vendor/(alpine-[^"\']+\.min\.js)', home)
    assert m, "alpine vendor script not linked"
    assert client.get(f"/static/vendor/{m.group(1)}").status_code == 200
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_web_server.py::test_base_layout_has_no_cdn_asset_urls tests/test_web_server.py::test_vendored_web_assets_are_served -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_web_server.py
git commit -m "test(web): require local fonts, tailwind, and vendor scripts"
```

---

### Task 2: Vendor htmx + Alpine + fonts

**Files:**
- Create: `src/asc/web/static/vendor/htmx-1.9.12.min.js`
- Create: `src/asc/web/static/vendor/alpine-3.14.8.min.js` (or latest 3.14.x available at implement time; use that exact version everywhere)
- Create: `src/asc/web/static/fonts/*.woff2`
- Create: `src/asc/web/static/fonts.css`
- Create: `src/asc/web/static/fonts/SOURCES.md`
- Create/Modify: `scripts/build_web_assets.sh` (download + font CSS section)

**Interfaces:**
- Produces: stable `/static/vendor/...` and `/static/fonts.css` URLs

- [ ] **Step 1: Download pinned JS**

```bash
mkdir -p src/asc/web/static/vendor
curl -fsSL -o src/asc/web/static/vendor/htmx-1.9.12.min.js \
  https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js
# Pin Alpine — verify version exists, e.g. 3.14.8
curl -fsSL -o src/asc/web/static/vendor/alpine-3.14.8.min.js \
  https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js
```

- [ ] **Step 2: Acquire font files**

Download woff2 files covering weights used by current Google Fonts URL:
- DM Sans: 300,400,500,600,700 + italic 400
- Fira Code: 400,500,600
- Instrument Serif: regular + italic

Prefer google-webfonts-helper / official OFL zip; place under `src/asc/web/static/fonts/`. Write `SOURCES.md` with license (OFL) and upstream.

- [ ] **Step 3: Write `fonts.css`**

`@font-face` for each file with `font-display: swap` and `url(/static/fonts/....woff2)`.

- [ ] **Step 4: Smoke**

```bash
# files exist and are non-empty
test -s src/asc/web/static/vendor/htmx-1.9.12.min.js
test -s src/asc/web/static/vendor/alpine-3.14.8.min.js
test -s src/asc/web/static/fonts.css
```

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/static/vendor src/asc/web/static/fonts src/asc/web/static/fonts.css scripts/build_web_assets.sh
git commit -m "feat(web): vendor htmx, alpine, and local webfonts"
```

---

### Task 3: Tailwind config + built CSS

**Files:**
- Create: `src/asc/web/input.css`
- Create: `src/asc/web/tailwind.config.js`
- Create: `src/asc/web/static/tailwind.css`
- Modify: `scripts/build_web_assets.sh` (tailwind build step)

**Interfaces:**
- Consumes: theme extend from current `base.html` (fontFamily + obsidian + amber)
- Produces: `/static/tailwind.css`

- [ ] **Step 1: Add `input.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 2: Add `tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/asc/web/templates/**/*.html"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["DM Sans", "system-ui", "sans-serif"],
        mono: ["Fira Code", "monospace"],
        display: ["Instrument Serif", "serif"],
      },
      colors: {
        obsidian: { /* copy from base.html */ },
        amber: { 650: "#d4880a", 600: "#e09413", 550: "#e8a125", 500: "#f0b03a" },
      },
    },
  },
  plugins: [],
};
```

Use Tailwind **v3** config shape (`module.exports`, `@tailwind` directives) for compatibility with existing class usage.

- [ ] **Step 3: Build**

```bash
# from repo root — script should wrap this
npx --yes tailwindcss@3.4.17 -c src/asc/web/tailwind.config.js \
  -i src/asc/web/input.css -o src/asc/web/static/tailwind.css --minify
```

Verify output contains utilities used on homepage (e.g. `obsidian-` or common spacing classes).

- [ ] **Step 4: Commit**

```bash
git add src/asc/web/input.css src/asc/web/tailwind.config.js src/asc/web/static/tailwind.css scripts/build_web_assets.sh
git commit -m "feat(web): add built local tailwind.css"
```

---

### Task 4: Wire `base.html` + docs + make tests green

**Files:**
- Modify: `src/asc/web/templates/base.html`
- Modify: `README.md`, `README.zh-CN.md` (short rebuild note)
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: assets from Tasks 2–3

- [ ] **Step 1: Replace CDN tags in `base.html`**

Head order:

1. `fonts.css?v={{ asset_version }}`
2. `tailwind.css?v={{ asset_version }}`
3. Remove Google preconnect + CDN tailwind script + inline `tailwind.config`
4. Keep existing inline `<style>` block
5. `htmx-1.9.12.min.js?v=...`
6. `alpine-….min.js?v=...` with `defer`

- [ ] **Step 2: Run contract tests — expect PASS**

```bash
pytest tests/test_web_server.py::test_base_layout_has_no_cdn_asset_urls \
  tests/test_web_server.py::test_vendored_web_assets_are_served -v
pytest tests/test_web_server.py -q
```

- [ ] **Step 3: Docs**

Add one sentence under Web/dev: rebuild with `scripts/build_web_assets.sh` after changing Tailwind classes.

- [ ] **Step 4: Commit**

```bash
git add src/asc/web/templates/base.html README.md README.zh-CN.md tests/test_web_server.py
git commit -m "feat(web): serve UI assets from local /static (no CDN)"
```

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| No CDN in HTML | 1, 4 |
| Local fonts + fonts.css | 2 |
| Built tailwind.css + theme | 3 |
| Pinned htmx/Alpine | 2 |
| Commit assets for pip users | 2–3 |
| Tests | 1, 4 |
| Rebuild script/docs | 2–4 |
