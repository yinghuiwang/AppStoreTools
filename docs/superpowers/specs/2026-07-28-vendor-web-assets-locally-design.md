# Design: Vendor Web UI assets locally (no CDN)

**Date:** 2026-07-28  
**Status:** Approved for implementation (pending user review of this doc)  
**Scope:** ASC Web UI (`asc web`) frontend assets only

## Problem

`src/asc/web/templates/base.html` loads critical UI assets from the public internet:

- Google Fonts (`fonts.googleapis.com` / `fonts.gstatic.com`)
- Tailwind Play CDN (`cdn.tailwindcss.com`)
- htmx (`unpkg.com/htmx.org@1.9.12`)
- Alpine.js (`unpkg.com/alpinejs@3.x.x` — floating major)

Offline, restricted networks, or CDN outages break layout and interactivity. This is unacceptable for a local CLI/desktop tool.

## Goals

1. Web UI works with **no outbound network** after `asc web` starts.
2. Styles (fonts + Tailwind utility CSS) and frontend scripts (htmx + Alpine) are served from `/static/...` via existing FastAPI `StaticFiles`.
3. Built/vendored assets ship inside the Python package so `pip install` users need no Node rebuild.
4. Preserve current visual theme (obsidian / amber / DM Sans / Fira Code / Instrument Serif).

## Non-goals

- No Vite/Webpack/full SPA toolchain.
- No redesign of pages or replacement of Alpine/htmx with another stack.
- No changes to dashboard.css / task-log-drawer.css ownership.
- No runtime fetch of fonts or CSS from CDNs as fallback.

## Approach (chosen)

**Formal Tailwind build + static vendor tree** (not copying the Play CDN script).

| Asset | Strategy |
|-------|----------|
| Tailwind | CLI scans Jinja templates + existing CSS; emit `static/tailwind.css` |
| Theme tokens | Move current `tailwind.config` extend (fontFamily, obsidian, amber) into build config |
| Fonts | Download required woff2 weights; local `@font-face` in `static/fonts.css` |
| htmx | Pin **1.9.12** minified file under `static/vendor/` |
| Alpine | Pin a concrete **3.x** release (e.g. 3.14.x) — never `3.x.x` floating URL |

## Layout

```
src/asc/web/static/
  vendor/
    htmx-1.9.12.min.js
    alpine-3.14.8.min.js          # exact pin recorded in NOTES/README under vendor or script header
  fonts/
    dm-sans-*.woff2
    fira-code-*.woff2
    instrument-serif-*.woff2
  fonts.css                       # @font-face → url(/static/fonts/...)
  tailwind.css                    # generated; committed to git
  dashboard.css / dashboard.js    # unchanged ownership
  task-log-drawer.css / .js       # unchanged ownership
```

Optional: `src/asc/web/tailwind.config.js` + `src/asc/web/input.css` (`@tailwind base/components/utilities`) live next to templates as build inputs (not served unless needed).

## base.html changes

Replace CDN tags with local links (cache-busted):

```html
<link rel="stylesheet" href="/static/fonts.css?v={{ asset_version }}">
<link rel="stylesheet" href="/static/tailwind.css?v={{ asset_version }}">
<script src="/static/vendor/htmx-1.9.12.min.js?v={{ asset_version }}"></script>
<script defer src="/static/vendor/alpine-….min.js?v={{ asset_version }}"></script>
```

Remove:

- `preconnect` to Google Fonts
- `cdn.tailwindcss.com` script and inline `tailwind.config = {…}` block
- unpkg script tags

Keep existing inline `:root` / component CSS in `base.html` (or leave as-is); it does not depend on CDN.

Load order: fonts.css → tailwind.css → page CSS (dashboard / task-log-drawer) → scripts.

## Build & packaging

1. Add `scripts/build_web_assets.sh` (or equivalent) that:
   - Invokes Tailwind CLI against `src/asc/web/templates/**/*.html` (and static CSS if needed for `@apply`)
   - Writes `src/asc/web/static/tailwind.css`
2. Document in README/dev section: after changing Tailwind class names in templates, run the script.
3. Commit generated `tailwind.css` and font/vendor binaries so end users need Node only when regenerating.
4. Confirm wheel/sdist includes new static files via existing package data discovery (`src/asc` layout).

Dev dependency: Tailwind CLI available via `npx @tailwindcss/cli` or a pinned standalone binary — prefer documenting `npx` so we avoid committing a huge binary unless reproducibility requires it.

Font acquisition: one-time download of OFL-licensed Google Fonts files used today; keep a short `static/fonts/SOURCES.md` with license + upstream URL for compliance.

## Testing

Add/extend `tests/test_web_server.py`:

- Homepage (and optionally another page) HTML must **not** contain: `cdn.tailwindcss.com`, `fonts.googleapis.com`, `fonts.gstatic.com`, `unpkg.com`.
- `GET /static/fonts.css`, `/static/tailwind.css`, `/static/vendor/htmx-1.9.12.min.js`, Alpine vendor path → **200**.
- Existing dashboard / task-log-drawer asset tests remain green.

Optional smoke: assert `tailwind.css` body includes a known utility or theme token used on the homepage (e.g. `obsidian` color class residue or `DM Sans` font-family in fonts.css).

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Missing Tailwind class after template edit | Rebuild script + doc; CI optional later |
| Font subset incomplete (missing weight) | Mirror weights currently requested in Google Fonts URL |
| Alpine floating 3.x.x behavior drift | Pin exact version file name |
| Package size growth | Acceptable for local tool; woff2 + min JS only |

## Success criteria

- Disconnect network → open `asc web` UI → layout and Alpine/htmx interactions still work.
- No CDN URLs remain in served HTML for UI assets.
- `pip install -e .` / packaged install serves all assets from `/static`.
