# Web UI Multilingual (i18n) Design

**Date:** 2026-07-29  
**Status:** Approved for planning  
**Branch context:** ASC Web dashboard (`src/asc/web/`) language support

## Problem

ASC Web UI templates under `src/asc/web/templates/` are almost entirely hardcoded Chinese (`base.html` sets `<html lang="zh-CN">`). Settings already exposes a language `<select>` that `POST`s `/api/settings/lang` and sets `os.environ["ASC_LANG"]`, but that only affects the **CLI** `src/asc/i18n.py` catalog — **page chrome and user-facing API messages do not switch**.

Users need:

1. Default language that follows browser / system preference.
2. Manual override that persists across visits.
3. Extensible structure so more locales can be added later (first delivery: `zh` + `en` only).

## Goals

- Deliver bilingual Web UI (`zh` / `en`) with catalogs structured for future locales.
- Auto-detect language on first visit; allow manual switch anytime.
- Persist preference via **Cookie + localStorage** (Cookie drives SSR; localStorage mirrors for client).
- Localize **UI chrome** and **user-facing API** `message` / `detail` strings.
- Provide switchers in **global nav (sidebar/header)** and **Settings** (same source of truth).

## Non-goals

- Translating raw task log lines, `xcodebuild` / `altool` subprocess output, or third-party error text verbatim.
- Merging Web catalogs into CLI `i18n.py` message tables (keep Web catalogs separate; share only language-code convention `zh` / `en`).
- Shipping additional languages in v1 beyond `zh` and `en`.
- Client-only string swapping that causes first-paint flash of the wrong language.

## Decisions

| Topic | Choice |
|-------|--------|
| Locales (v1) | `zh`, `en`; JSON catalogs keyed for easy addition later |
| Persistence | Cookie `asc_lang` (SSR, `Max-Age` ≈ 1 year, `Path=/`, `SameSite=Lax`) + `localStorage['asc_lang']` (client mirror) |
| Resolve order | Cookie → `Accept-Language` → env `ASC_LANG` → default `en` |
| Conflict rule | Cookie wins; on load, overwrite localStorage from Cookie |
| Scope | UI templates + user-facing API messages; not task/subprocess logs |
| Switcher UI | Global nav **and** Settings (shared API) |
| Approach | Server-resolved language + Jinja `t()` + injected catalog for Alpine |
| CLI coupling | Keep setting `ASC_LANG` on switch (existing Settings behavior) so Web-spawned CLI context stays aligned |

## Architecture

```
Request
  → resolve_lang(cookie → Accept-Language → ASC_LANG → en)
  → request.state.lang + Jinja globals: t(), lang, i18n_catalog
  → Templates render in that language; APIs call t() for user messages

Language switch
  → POST /api/settings/lang (form: lang=zh|en)
  → Validate → Set-Cookie(asc_lang, long-lived) → os.environ["ASC_LANG"]=lang
  → Client writes localStorage → full page reload (or htmx boost reload)
```

### New / updated modules

| Path | Role |
|------|------|
| `src/asc/web/locales/zh.json` | Chinese message catalog (dot keys, e.g. `nav.settings`) |
| `src/asc/web/locales/en.json` | English message catalog (same key set) |
| `src/asc/web/i18n.py` | `SUPPORTED_LANGS`, `resolve_lang`, `load_catalog`, `t(key, lang=None, **kwargs)` |
| FastAPI middleware or dependency | Per-request `resolve_lang`; attach to `request.state` |
| Jinja environment | Register `t`, expose `lang`; `base.html` sets `<html lang="zh-CN"\|"en">` and injects `window.__I18N` |
| `POST /api/settings/lang` | Extend existing handler: Set-Cookie + `ASC_LANG` + `{ok, lang}` |
| `base.html` + Settings | Global language control + Settings select bound to same API |

Do **not** fold Web strings into `src/asc/i18n.py`. CLI and Web catalogs evolve independently; both use `zh` / `en` codes.

### Message catalog shape

```json
{
  "nav.dashboard": "Dashboard",
  "nav.settings": "Settings",
  "settings.lang": "Language",
  "api.invalid_lang": "Invalid language",
  "whats_new.version_locales": "Version {version} · {count} locales"
}
```

- Keys: stable, namespaced by area (`nav.*`, `settings.*`, `api.*`, page prefixes).
- Interpolation: simple `{name}` replacement in `t()`.
- Missing key: try `en` catalog → else return the key string (makes gaps visible in development).
- Adding a locale later: add `locales/<code>.json` + register in `SUPPORTED_LANGS`; no template rewrite.

### Language resolution (`resolve_lang`)

1. If Cookie `asc_lang` ∈ supported → use it.
2. Else parse `Accept-Language`: first matching prefix (`zh*` → `zh`, `en*` → `en`).
3. Else if `ASC_LANG` maps to supported (`zh` / `en` aliases same as CLI) → use it.
4. Else → `en`.

### Frontend sync

- On every page load: if Cookie present, `localStorage.asc_lang = cookie value`.
- If Cookie absent but localStorage has a supported value: one-shot `POST /api/settings/lang` to mint Cookie (avoids SSR/client drift), then reload once if language changed from resolved default.
- Switcher (nav + Settings): call API → write localStorage → reload.

Alpine / inline JS user-visible strings use `window.__I18N[key]` (or a tiny `window.t(key, vars)` helper) from the same catalog injected by the server — **one catalog, no parallel JS dictionary files**.

## Data flow

### First visit (no Cookie, no localStorage)

1. Server uses `Accept-Language` / `ASC_LANG` / `en`.
2. Renders page; optionally does **not** set Cookie until user switches or client sync runs (so changing browser language still works until an explicit preference exists).  
   **Decision:** Do not auto-persist detected language to Cookie on first paint. Cookie is written only on explicit switch or when client promotes localStorage. This keeps “follow browser” until the user chooses.

### Explicit switch

1. User picks `zh` or `en` in nav or Settings.
2. `POST /api/settings/lang` → Cookie + `ASC_LANG`.
3. Client sets localStorage → reload → all SSR + `__I18N` match.

### API responses

Handlers that return user-readable `message` / `detail` call `t(key, lang=request.state.lang, ...)` instead of hardcoded Chinese. Validation errors (e.g. invalid lang) use the catalog too.

## Error handling

| Case | Behavior |
|------|----------|
| Unsupported `lang` in POST | HTTP 400; Cookie unchanged |
| Missing translation key | Fallback `en` → then key string |
| Unparseable / empty Accept-Language | Skip to `ASC_LANG` / default |
| Cookie vs localStorage mismatch | Cookie wins; overwrite localStorage on load |
| Switch network failure | Show localized error toast/text; no reload; keep current language |

## UI placement

- **Global:** compact control in the **sidebar footer** (below nav, always visible), e.g. segmented `中文 | EN` or a small `<select>`.
- **Settings:** existing「语言」block remains; options and current value driven by `lang` from server; same POST endpoint.
- Both controls must not diverge: no second persistence path.
- `<html lang>` mapping: internal `zh` → `zh-CN`, `en` → `en`.

## Delivery phases (implementation can split PRs)

1. **Foundation** — `i18n.py`, locale JSON files, middleware/Jinja injection, Cookie-aware `POST /api/settings/lang`, tests for resolve/`t`/endpoint.
2. **Shell** — `base.html` nav/chrome + Settings language UI + global switcher + `__I18N` inject.
3. **Pages** — Replace hardcoded strings in remaining templates page by page.
4. **API messages** — User-facing `message`/`detail` in `routes_api.py` (and related) via `t()`.

## Testing

- Unit: `resolve_lang` priority matrix (cookie / Accept-Language / ASC_LANG / default).
- Unit: `t()` interpolation, missing-key fallback, unknown lang → `en` catalog.
- API: `POST /api/settings/lang` success sets `Set-Cookie: asc_lang=...`; invalid lang → 400.
- Optional: render a small template fragment in zh vs en and assert distinct strings.
- No live ASC network; use pytest + TestClient / mocks.

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Large template string extraction | Phased PRs; foundation merges first so pages can land incrementally |
| Alpine string drift | Inject single `__I18N`; ban ad-hoc English/Chinese literals in new Alpine code |
| Auto-Cookie on detect locks language | Only persist on explicit preference (or localStorage promotion) |
| CLI `i18n.py` confusion | Document Web vs CLI catalogs; only share language codes |

## Success criteria

- Fresh browser with `Accept-Language: en` sees English UI without prior Cookie.
- Fresh browser with `zh-CN` sees Chinese UI.
- Manual switch updates Cookie + localStorage; reload stays on chosen language.
- Settings and nav switchers stay in sync.
- Representative API error/success `message` respects request language.
- Adding a third locale later requires a new JSON file + registry entry, not template rewrites.
