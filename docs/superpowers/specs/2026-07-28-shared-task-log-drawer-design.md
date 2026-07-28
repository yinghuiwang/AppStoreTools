# Shared Task Log Drawer Design

**Date:** 2026-07-28  
**Status:** Approved for planning  
**Branch context:** Web UI task-log experience unification

## Problem

ASC Web UI has two separate task-log experiences:

1. **Dashboard** — right-side drawer with SSE streaming, error filter, copy, clear, auto-follow, focus trap, and overlay mode on narrow viewports (`index.html` + `dashboard.js` / `dashboard.css`).
2. **Feature pages** (metadata, build, urls, whats-new, iap, update) — each copies a small Alpine + `EventSource` loop into an inline collapsible `.log-panel`, without the drawer tooling.

Shared backend already exists (`GET /api/task/{id}/stream`, `GET /api/task/{id}/status`). Only the presentation layer is duplicated and uneven.

## Goals

- Extract the dashboard log drawer into a reusable module.
- Replace inline feature-page log panels with the same drawer UI/behavior.
- On task start: **auto-open** the drawer and attach SSE.
- After the user closes it: allow **re-open** via a per-page「日志」control.
- Keep page-local concerns on the page: progress bars, build phase gauges, cancel buttons, Alpine step state machines.

## Non-goals

- No changes to SSE/status/cancel API contracts.
- No rewrite of `task_list.html` historical static log expand/collapse.
- No redesign of build「自动检测结果」side panel content.
- No new notification or webhook behavior.

## Decisions

| Topic | Choice |
|-------|--------|
| Reuse shape | Replace feature-page inline logs with the shared drawer (not “SSE-only” extraction) |
| Open behavior | Auto-open on task start **and** manual reopen via「日志」 |
| Implementation | Shared partial + CSS + JS module; dashboard and feature pages both call it |
| Build page conflict | Build already uses `right_panel` for scan results → log drawer must not steal that slot |

## Architecture

### New assets

| Path | Role |
|------|------|
| `src/asc/web/templates/_task_log_drawer.html` | Drawer markup using generic `data-task-log-*` hooks |
| `src/asc/web/static/task-log-drawer.css` | Styles moved out of `dashboard.css` (drawer chrome, overlay, animation) |
| `src/asc/web/static/task-log-drawer.js` | Drawer controller exposed as `window.TaskLogDrawer` |

### Public JS API

```js
TaskLogDrawer.open(taskId, {
  title,        // string, drawer heading
  onProgress,   // optional (pct: number, msg: string) => void
  onDone,       // optional () => void
  onError,      // optional (payload?: string) => void
  onCanceled,   // optional () => void
})
TaskLogDrawer.close()
TaskLogDrawer.isOpen()
TaskLogDrawer.currentTaskId()
TaskLogDrawer.attachDock(hostElement) // optional; dashboard only
```

Behavior preserved from the current dashboard drawer:

- Preflight `GET /api/task/{id}/status` (handle 404)
- `EventSource` on `/api/task/{id}/stream?after=0` with seq/`lastEventId` dedupe
- Events: `log`, `progress`, `done`, `error_event` (incl. timeout reconnect copy), `canceled`
- Tools: errors-only filter, copy, clear display, auto-follow, “back to latest”, position label
- Close: header button, Escape, click-outside (when overlay)
- Narrow viewport: overlay + `inert` background + focus trap
- Opening a different `taskId` while open replaces the stream cleanly

### Mounting model

Include the drawer markup once from `base.html` so every page has a single instance.

**Dock vs overlay**

- If a dock host is attached (`TaskLogDrawer.attachDock(...)`), desktop mode docks into that host (current dashboard flex side column). Narrow screens still overlay.
- If no dock host (feature pages, including build), the drawer always uses **overlay / fixed slide-in**, so it never competes with build’s scan `right_panel`.

Dashboard keeps a dock host adjacent to `#dashboard-root` (or inside the existing right-panel region) and calls `attachDock` on load.

### Asset loading

- `base.html` loads `task-log-drawer.css` and `task-log-drawer.js` with `?v={{ asset_version }}` (same cache-bust pattern as dashboard assets).
- Every page rendered through `_get_profile_context` already provides `asset_version` from `asc.__version__`; keep that contract so base includes resolve.

## Page migrations

### Feature pages

For `metadata.html`, `build.html`, `urls.html`, `whats_new.html`, `iap.html`, `update.html`:

1. Remove inline collapsible log markup and per-page `startSSE` / `startBuildSSE` / `startIapSSE` duplication.
2. Keep status header, progress UI, cancel, and “重新运行”.
3. On successful task create (`task_id` returned):  
   `TaskLogDrawer.open(taskId, { title, onProgress, onDone, onError, onCanceled })`.
4. Add a「日志」button visible while a `taskId` exists (and ideally while status is running/done/error/canceled for that run) that re-opens the same task’s drawer.
5. Wire callbacks to existing Alpine state (`progress`, `progressMsg`, `status`, build `phase`, update’s post-done `checkUpdate`, etc.).

### Dashboard

1. Replace embedded drawer markup with the shared partial (or rely on base include + dock host only).
2. `dashboard.js` calls `TaskLogDrawer.open/close` instead of local EventSource/drawer helpers.
3. Remove duplicated drawer CSS from `dashboard.css` (keep dashboard-specific task list/button styles).
4. Existing「日志」buttons on running/history rows keep working via the shared API.
5. Progress updates for running cards continue via `onProgress` or an equivalent hook that updates DOM the dashboard already owns.

### Explicitly unchanged

- `task_list.html` + `window.toggleTaskLogs` for server-rendered historical snippets.
- Build scan side panel markup and `buildScanPanel()` behavior.

## Error and edge cases

| Case | Behavior |
|------|----------|
| Task 404 on preflight | Show “任务不存在或已被清理”; do not start EventSource |
| Stream timeout event | Keep current reconnect messaging |
| User cancels task | Drawer receives `canceled` (or status refresh); page callback sets Alpine canceled state |
| Second open same task | Reattach stream with `after=0`; must not leak EventSources |
| Open while another task streaming | Close previous stream first |
| Drawer closed mid-run | Stream closed; reopen attaches fresh stream with `after=0` (full replay from store) |

## Testing

- Migrate dashboard log-drawer contract tests in `tests/test_web_server.py` to assert the shared module files and/or base include (EventSource, filter, copy, follow, focus trap, slide animation).
- Add tests that `task-log-drawer.js` exposes `TaskLogDrawer.open/close` and references `/api/task/` status + stream + cancel-adjacent contracts as needed.
- Smoke expectations (string/HTML contracts acceptable, matching current style):
  - Feature page no longer contains `#log-panel` / `#build-log-panel` style live SSE panels for active runs (or equivalent removed markers).
  - Feature page contains a control that opens the shared drawer (`data-task-log-open` or documented hook).
- Keep existing `test_task_stream_*` API tests unchanged.

## Rollout / implementation order

1. Extract shared partial/CSS/JS; mount in `base.html`; keep dashboard behavior green.
2. Point dashboard at `TaskLogDrawer`; delete duplicated dashboard drawer code.
3. Migrate feature pages one cluster at a time (metadata → urls/whats-new → iap/update → build last because of overlay + phase callbacks).
4. Update tests after each cluster if helpful; full contract suite before merge.

## Success criteria

- One log-drawer implementation used by dashboard and all listed feature pages.
- Starting a task auto-opens the drawer; closing then clicking「日志」reopens it for that task.
- Build scan side panel still works; log overlay does not replace it.
- Existing dashboard drawer UX (filter/copy/follow/focus/overlay) remains intact.
