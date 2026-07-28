# Shared Task Log Drawer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the dashboard task log drawer into a shared module and replace inline SSE log panels on all feature pages with the same auto-open / reopen drawer UX.

**Architecture:** Add `TaskLogDrawer` (`task-log-drawer.js/css` + `_task_log_drawer.html`) mounted once from `base.html`. Dashboard docks it into a right-panel host; feature pages use overlay mode so build’s scan side panel is untouched. Feature pages call `TaskLogDrawer.open(taskId, callbacks)` on task start and via a「日志」button.

**Tech Stack:** Jinja2 templates, vanilla JS (IIFE / `window.TaskLogDrawer`), existing FastAPI SSE endpoints, pytest string-contract tests (matching current `test_web_server.py` style).

## Global Constraints

- Do not change `/api/task/{id}/stream`, `/status`, or `/cancel` contracts.
- Do not modify `task_list.html` / `window.toggleTaskLogs` historical panels.
- Do not redesign build「自动检测结果」side panel.
- Preserve dashboard drawer UX: error filter, copy, clear, follow, Escape, outside-click (overlay), focus trap, slide animation.
- Cache-bust shared assets with `?v={{ asset_version }}`.
- Spec: `docs/superpowers/specs/2026-07-28-shared-task-log-drawer-design.md`.

## File map

| Path | Responsibility |
|------|----------------|
| Create `src/asc/web/templates/_task_log_drawer.html` | Shared drawer markup (`data-task-log-*`) |
| Create `src/asc/web/static/task-log-drawer.css` | Drawer chrome / dock / overlay styles |
| Create `src/asc/web/static/task-log-drawer.js` | `window.TaskLogDrawer` API |
| Modify `src/asc/web/templates/base.html` | Include CSS/JS + drawer partial |
| Modify `src/asc/web/templates/index.html` | Dock host; remove old drawer markup |
| Modify `src/asc/web/static/dashboard.js` | Call `TaskLogDrawer`; drop local drawer/SSE |
| Modify `src/asc/web/static/dashboard.css` | Remove moved drawer rules |
| Modify feature templates | metadata, urls, whats_new, iap, update, build |
| Modify `tests/test_web_server.py` | Point contracts at shared module + page smokes |

---

### Task 1: Shared module contract tests (failing first)

**Files:**
- Create: `src/asc/web/static/task-log-drawer.js` (stub only in later step — tests first expect 404 until created)
- Test: `tests/test_web_server.py`

**Interfaces:**
- Produces (expected by later tasks): served path `/static/task-log-drawer.js` exporting identifiable `window.TaskLogDrawer` API strings

- [ ] **Step 1: Add failing contract tests**

Append to `tests/test_web_server.py`:

```python
def test_task_log_drawer_javascript_exposes_public_api(client):
    resp = client.get("/static/task-log-drawer.js")
    assert resp.status_code == 200
    body = resp.text
    assert "window.TaskLogDrawer" in body
    assert "function open(" in body or "open: function" in body or "open(" in body
    assert "attachDock" in body
    assert "/api/task/" in body
    assert '"/status"' in body or "/status" in body
    assert "stream?after=0" in body
    assert "data-task-log-errors" in body
    assert "data-task-log-follow" in body
    assert "任务不存在或已被清理" in body


def test_base_layout_includes_task_log_drawer_assets(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "task-log-drawer.css?v=" in resp.text
    assert "task-log-drawer.js?v=" in resp.text
    assert 'id="task-log-drawer"' in resp.text
    assert "data-task-log-close" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_server.py::test_task_log_drawer_javascript_exposes_public_api tests/test_web_server.py::test_base_layout_includes_task_log_drawer_assets -v`

Expected: FAIL (404 for JS and/or missing base includes)

- [ ] **Step 3: Commit the failing tests only**

```bash
git add tests/test_web_server.py
git commit -m "test(web): add shared task log drawer contract stubs"
```

---

### Task 2: Drawer markup, CSS, and base mount

**Files:**
- Create: `src/asc/web/templates/_task_log_drawer.html`
- Create: `src/asc/web/static/task-log-drawer.css`
- Modify: `src/asc/web/templates/base.html`
- Test: `tests/test_web_server.py` (base include test from Task 1)

**Interfaces:**
- Produces: DOM ids/attrs — `#task-log-drawer`, `#task-log-title`, `#task-log-output`, `data-task-log-close|status|errors|copy|clear|follow|latest|position`
- Consumes: `asset_version` from template context

- [ ] **Step 1: Create `_task_log_drawer.html`**

Move structure from `index.html` `{% block right_panel %}` drawer, renaming hooks:

```html
<aside id="task-log-drawer"
       class="task-log-drawer"
       role="dialog"
       aria-modal="false"
       aria-labelledby="task-log-title"
       hidden>
  <header class="task-log-drawer__header">
    <div>
      <p class="task-log-kicker">TASK OUTPUT</p>
      <h2 id="task-log-title">任务日志</h2>
    </div>
    <button type="button" class="task-log-icon-button" data-task-log-close aria-label="关闭日志面板" title="关闭日志面板">&#215;</button>
  </header>
  <div class="task-log-tools" role="toolbar" aria-label="日志工具">
    <span data-task-log-status>等待选择任务</span>
    <div>
      <button type="button" class="task-log-filter" data-task-log-errors aria-pressed="false">仅错误</button>
      <button type="button" class="task-log-icon-button" data-task-log-copy aria-label="复制日志" title="复制日志">&#9633;</button>
      <button type="button" class="task-log-icon-button" data-task-log-clear aria-label="清空显示" title="清空显示">&#8856;</button>
    </div>
  </div>
  <pre id="task-log-output" class="task-log-output" tabindex="0" aria-live="polite"><code>从任务列表中选择“日志”以查看实时输出。</code></pre>
  <footer class="task-log-follow">
    <label><input type="checkbox" data-task-log-follow checked> 自动跟随最新输出</label>
    <button type="button" class="task-log-button" data-task-log-latest hidden>回到最新</button>
    <span data-task-log-position>-- / --</span>
  </footer>
</aside>
```

- [ ] **Step 2: Create `task-log-drawer.css`**

Copy drawer-related rules from `dashboard.css` (`.dashboard-log-drawer*` through overlay media queries and reduced-motion), rename prefixes to `.task-log-drawer` / `.task-log-*`.

Add dock/overlay modes:

```css
.task-log-drawer.is-overlay {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 40;
}
.task-log-drawer.is-docked {
  position: relative;
  flex: 0 0 390px;
  width: 390px;
}
```

Keep slide transform + `.is-open` behavior from the dashboard drawer.

- [ ] **Step 3: Mount in `base.html`**

In `<head>` (after existing CSS links):

```html
<link rel="stylesheet" href="/static/task-log-drawer.css?v={{ asset_version }}">
```

Before `</body>` (after main content / scripts that pages need, but before page-specific blocks finish — typically end of `<main>` or just inside `<body>` after `{% block right_panel %}`):

```html
{% include "_task_log_drawer.html" %}
<script src="/static/task-log-drawer.js?v={{ asset_version }}" defer></script>
```

Preferred placement: immediately after `{% block right_panel %}{% endblock %}` inside `<main>`, so the drawer is a sibling of content + optional right panel.

Also ensure every template path using `base.html` still receives `asset_version` (already from `_get_profile_context`).

- [ ] **Step 4: Add a minimal stub `task-log-drawer.js` so StaticFiles serves 200**

```js
(function (global) {
  "use strict";
  global.TaskLogDrawer = {
    open: function () {},
    close: function () {},
    isOpen: function () { return false; },
    currentTaskId: function () { return null; },
    attachDock: function () {}
  };
})(window);
```

(Full implementation is Task 3; stub unblocks HTML include test.)

- [ ] **Step 5: Run base include test**

Run: `pytest tests/test_web_server.py::test_base_layout_includes_task_log_drawer_assets -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/asc/web/templates/_task_log_drawer.html src/asc/web/static/task-log-drawer.css src/asc/web/static/task-log-drawer.js src/asc/web/templates/base.html
git commit -m "feat(web): mount shared task log drawer shell in base layout"
```

---

### Task 3: Implement `TaskLogDrawer` behavior

**Files:**
- Modify: `src/asc/web/static/task-log-drawer.js`
- Test: `tests/test_web_server.py::test_task_log_drawer_javascript_exposes_public_api`

**Interfaces:**
- Consumes: `#task-log-drawer` DOM from Task 2
- Produces:

```js
window.TaskLogDrawer = {
  open(taskId: string, options?: {
    title?: string,
    onProgress?: (pct: number, msg: string) => void,
    onDone?: () => void,
    onError?: (payload?: string) => void,
    onCanceled?: () => void,
  }): void,
  close(): void,
  isOpen(): boolean,
  currentTaskId(): string | null,
  attachDock(hostElement: Element | null): void,
}
```

- [ ] **Step 1: Port drawer logic from `dashboard.js`**

Move/adapt these concerns from `src/asc/web/static/dashboard.js` into `task-log-drawer.js` (keep as one IIFE):

- Element queries using `data-task-log-*` / `#task-log-*`
- `open(taskId, options)`: close prior stream; set title; reset log buffer; preflight `GET /api/task/{id}/status`; on 404 show「任务不存在或已被清理」; else `EventSource(/api/task/{id}/stream?after=0)`
- Event handlers: `log`, `progress` (call `options.onProgress`), `done` / `canceled` / `error_event` (timeout reconnect copy vs finish + callbacks)
- Tools: errors filter, copy, clear, follow, latest, position
- `close()`: close EventSource, hide panel, clear callbacks ownership safely
- Overlay vs dock: if `dockHost` set and viewport > 1360px, add `is-docked` and append drawer into host; else `is-overlay` + focus trap + outside click + `inert` on `main`/sidebar as today’s dashboard does for overlay
- `attachDock(host)` stores host; call `updateMode()` 
- Opening same or different task: always tear down previous EventSource first; reopen with `after=0`

Do **not** keep `#dashboard-root`-only assumptions inside the shared module.

- [ ] **Step 2: Run shared JS contract test**

Run: `pytest tests/test_web_server.py::test_task_log_drawer_javascript_exposes_public_api -v`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/asc/web/static/task-log-drawer.js
git commit -m "feat(web): implement TaskLogDrawer SSE and overlay/dock behavior"
```

---

### Task 4: Point dashboard at `TaskLogDrawer`

**Files:**
- Modify: `src/asc/web/templates/index.html`
- Modify: `src/asc/web/static/dashboard.js`
- Modify: `src/asc/web/static/dashboard.css`
- Modify: `tests/test_web_server.py` (update drawer contract assertions to shared module / dual-check)

**Interfaces:**
- Consumes: `TaskLogDrawer.open/close/attachDock`
- Produces: dashboard「日志」buttons still use `data-dashboard-log-task` as open triggers

- [ ] **Step 1: Replace `index.html` right_panel drawer with dock host**

```html
{% block right_panel %}
<div id="task-log-dock" class="task-log-dock" aria-hidden="true"></div>
{% endblock %}
```

Remove the old `#dashboard-log-drawer` markup from `index.html` (now in base include).

- [ ] **Step 2: Wire `dashboard.js`**

On init (after root exists):

```js
if (window.TaskLogDrawer) {
  var dock = document.getElementById("task-log-dock");
  TaskLogDrawer.attachDock(dock);
}
```

Replace `openLogs(taskId, trigger)` body to:

```js
TaskLogDrawer.open(taskId, {
  title: (titleText || "任务") + " 日志",
  onProgress: function (pct, msg) {
    updateTaskProgress(taskId, { pct: pct, msg: msg });
  },
  onDone: function () { refreshDashboard(); },
  onError: function () { refreshDashboard(); },
  onCanceled: function () { refreshDashboard(); }
});
```

Delete local EventSource/drawer helpers that moved (`openDrawerPanel`, stream handlers, copy/filter/follow drawer-only code). Keep dashboard refresh/filters/running-list/cancel.

Keep click handler on `[data-dashboard-log-task]` calling the thin `openLogs` wrapper. Update focus restore if it referenced drawer nodes — restore to the log button only.

- [ ] **Step 3: Remove duplicated drawer CSS from `dashboard.css`**

Delete `.dashboard-log-drawer*` rules now living in `task-log-drawer.css`. Keep `.dashboard-log-button` styles used by list actions.

- [ ] **Step 4: Update tests**

- Change homepage assertions from `id="dashboard-log-drawer"` to `id="task-log-drawer"` (still present via base) and optionally `id="task-log-dock"`.
- Point log-drawer behavior contracts at `/static/task-log-drawer.js` (and/or keep smoke that dashboard.js calls `TaskLogDrawer.open`).
- Update CSS test to look for `.task-log-drawer` in `task-log-drawer.css`.

Example addition:

```python
def test_dashboard_javascript_delegates_logs_to_task_log_drawer(client):
    resp = client.get("/static/dashboard.js")
    assert resp.status_code == 200
    assert "TaskLogDrawer.open" in resp.text
    assert "TaskLogDrawer.attachDock" in resp.text
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
pytest tests/test_web_server.py -k "dashboard and (log or drawer or stylesheet or homepage_contains or homepage_loads_dashboard)" -v
```

Expected: PASS (adjust `-k` if needed until green)

- [ ] **Step 6: Manual smoke**

Run: `asc web stop && asc web` then open `/`, click a history「日志」, confirm drawer opens and streams.

- [ ] **Step 7: Commit**

```bash
git add src/asc/web/templates/index.html src/asc/web/static/dashboard.js src/asc/web/static/dashboard.css tests/test_web_server.py
git commit -m "refactor(web): dashboard uses shared TaskLogDrawer"
```

---

### Task 5: Migrate metadata page

**Files:**
- Modify: `src/asc/web/templates/metadata.html`
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: `TaskLogDrawer.open(taskId, { title, onProgress, onDone, onError, onCanceled })`
- Produces: `data-task-log-open` button on run step

- [ ] **Step 1: Write failing page smoke test**

```python
def test_metadata_page_uses_shared_task_log_drawer(client):
    resp = client.get("/metadata")
    assert resp.status_code == 200
    assert "TaskLogDrawer.open" in resp.text
    assert 'data-task-log-open' in resp.text
    assert "new EventSource(`/api/task/${taskId}/stream`)" not in resp.text
    assert 'id="log-panel"' not in resp.text
```

Run: `pytest tests/test_web_server.py::test_metadata_page_uses_shared_task_log_drawer -v`  
Expected: FAIL

- [ ] **Step 2: Replace inline logs + `startSSE`**

In the execution step card:

1. Remove the collapsible log block (`x-data="{ open: true }"` … `#log-panel`).
2. Keep progress track + cancel + 重新运行.
3. Add:

```html
<button type="button"
        class="text-xs text-amber-550 hover:text-amber-500 ..."
        x-show="taskId"
        data-task-log-open
        @click="TaskLogDrawer.open(taskId, metadataLogOptions())">日志</button>
```

4. Replace `startSSE(taskId)` with:

```js
function metadataLogOptions() {
  const root = document.querySelector('[x-data]');
  const d = Alpine.$data(root);
  return {
    title: "元数据上传日志",
    onProgress(pct, msg) { d.progress = pct; d.progressMsg = msg || ""; },
    onDone() { d.status = "done"; d.progress = 100; },
    onError() { d.status = "error"; },
    onCanceled() { d.status = "canceled"; d.canceling = false; d.progressMsg = "上传已终止"; },
  };
}
function startTaskLogs(taskId) {
  TaskLogDrawer.open(taskId, metadataLogOptions());
}
```

Call `startTaskLogs(data.task_id)` wherever the run response currently calls `startSSE`.

Keep `cancelTask` using `/api/task/{id}/cancel` as today.

- [ ] **Step 3: Run smoke test**

Run: `pytest tests/test_web_server.py::test_metadata_page_uses_shared_task_log_drawer -v`  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/asc/web/templates/metadata.html tests/test_web_server.py
git commit -m "feat(web): metadata page uses shared task log drawer"
```

---

### Task 6: Migrate urls + whats-new pages

**Files:**
- Modify: `src/asc/web/templates/urls.html`
- Modify: `src/asc/web/templates/whats_new.html`
- Test: `tests/test_web_server.py`

**Interfaces:** Same `TaskLogDrawer.open` pattern as Task 5.

- [ ] **Step 1: Add failing smokes**

```python
@pytest.mark.parametrize("path", ["/urls", "/whats-new"])
def test_feature_page_uses_shared_task_log_drawer(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "TaskLogDrawer.open" in resp.text
    assert "data-task-log-open" in resp.text
    assert "new EventSource(" not in resp.text or "TaskLogDrawer" in resp.text
```

Prefer asserting absence of page-local `function startSSE` and presence of `TaskLogDrawer.open`.

- [ ] **Step 2: Migrate `urls.html`**

Remove `#log-panel` + `startSSE`. On run success and「日志」button call:

```js
TaskLogDrawer.open(taskId, {
  title: "URL 更新日志",
  onDone() { /* set Alpine status done */ },
  onError() { /* status error */ },
  onCanceled() { /* status canceled */ },
});
```

(No progress events required today.)

- [ ] **Step 3: Migrate `whats_new.html`**

Same pattern; wire `onProgress` to existing progress fields; title `"更新说明上传日志"`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_web_server.py::test_feature_page_uses_shared_task_log_drawer -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/templates/urls.html src/asc/web/templates/whats_new.html tests/test_web_server.py
git commit -m "feat(web): urls and whats-new use shared task log drawer"
```

---

### Task 7: Migrate iap + update pages

**Files:**
- Modify: `src/asc/web/templates/iap.html`
- Modify: `src/asc/web/templates/update.html`
- Test: `tests/test_web_server.py`

**Interfaces:** Same `TaskLogDrawer.open` API; update page must still call `checkUpdate()` on done.

- [ ] **Step 1: Add failing smokes for `/iap` and `/update`**

Mirror Task 6 parametrize including these paths (or extend the existing parametrize list).

- [ ] **Step 2: Migrate `iap.html`**

Remove `#iap-log-panel` / `startIapSSE`. Open drawer with title `"IAP 上传日志"` (and review-screenshot flow title if separate). Wire progress + terminal callbacks.

- [ ] **Step 3: Migrate `update.html`**

```js
onDone() {
  d.status = "done";
  checkUpdate();
}
```

Title: `"工具更新日志"`.

- [ ] **Step 4: Run tests + commit**

```bash
pytest tests/test_web_server.py -k "shared_task_log_drawer" -v
git add src/asc/web/templates/iap.html src/asc/web/templates/update.html tests/test_web_server.py
git commit -m "feat(web): iap and update use shared task log drawer"
```

---

### Task 8: Migrate build page (overlay + phase)

**Files:**
- Modify: `src/asc/web/templates/build.html`
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: overlay-mode drawer (no `attachDock` on this page)
- Must keep `{% block right_panel %}` scan panel unchanged

- [ ] **Step 1: Failing smoke**

```python
def test_build_page_uses_shared_task_log_drawer_and_keeps_scan_panel(client):
    resp = client.get("/build")
    assert resp.status_code == 200
    assert "TaskLogDrawer.open" in resp.text
    assert "data-task-log-open" in resp.text
    assert "自动检测结果" in resp.text
    assert "startBuildSSE" not in resp.text
    assert 'id="build-log-panel"' not in resp.text
```

- [ ] **Step 2: Replace build log panel / `startBuildSSE`**

Keep phase gauges and scan `right_panel`. Remove `#build-log-panel` block.

```js
function buildLogOptions() {
  const d = Alpine.$data(document.getElementById("build-page-state"));
  return {
    title: "构建上传日志",
    onProgress(pct, msg) {
      d.progress = pct;
      d.progressMsg = msg || "";
      // keep existing phase heuristics if they parse log lines —
      // if phase was inferred from log text, move that into onProgress
      // only when msg matches prior patterns; otherwise leave phase updates
      // to done handler defaults already used today
    },
    onDone() { d.status = "done"; d.progress = 100; d.phase = 3; },
    onError() { d.status = "error"; },
    onCanceled() { d.status = "canceled"; d.canceling = false; d.progressMsg = "上传已终止"; },
  };
}
```

If current `startBuildSSE` advances `phase` by scanning log lines, port that scan into the `log` path by adding optional `onLog(line)` to `TaskLogDrawer.open` **only if needed**. Prefer extending the shared API:

```js
onLog?: (line: string) => void
```

Add `onLog` to `task-log-drawer.js` when appending log lines (call after store). Update Task 3 API docs in code comments. Build uses `onLog` for phase heuristics.

- [ ] **Step 3: Verify overlay does not remove scan panel**

Manual: open `/build`, confirm right scan panel visible; start a dry-run task; drawer overlays; scan panel still in DOM.

- [ ] **Step 4: Tests + commit**

```bash
pytest tests/test_web_server.py::test_build_page_uses_shared_task_log_drawer_and_keeps_scan_panel -v
git add src/asc/web/templates/build.html src/asc/web/static/task-log-drawer.js tests/test_web_server.py
git commit -m "feat(web): build page uses shared task log drawer overlay"
```

---

### Task 9: Final cleanup and full regression

**Files:**
- Modify: any leftover `dashboard-*` drawer references
- Test: `tests/test_web_server.py`, optionally `tests/test_web_dashboard.py`

- [ ] **Step 1: Grep for leftovers**

Run:

```bash
rg -n "dashboard-log-drawer|startSSE|startBuildSSE|startIapSSE|build-log-panel|id=\"log-panel\"" src/asc/web tests
```

Expected: only historical notes / `task_list` static panels / intentional absences.

- [ ] **Step 2: Full web server test slice**

Run:

```bash
pytest tests/test_web_server.py -q
```

Expected: PASS

- [ ] **Step 3: Commit any cleanup**

```bash
git add -A
git commit -m "chore(web): finish shared task log drawer cleanup"
```

---

## Spec coverage checklist

| Spec item | Task |
|-----------|------|
| Shared partial/css/js | 2–3 |
| `TaskLogDrawer` API | 3 (+ `onLog` in 8 if required) |
| Mount in `base.html` + asset_version | 2 |
| Dock vs overlay | 3–4, 8 |
| Dashboard migration | 4 |
| Feature pages auto-open + reopen | 5–8 |
| Build scan panel untouched | 8 |
| Tests migrated/added | 1, 4–9 |
| No SSE API changes | all |
| `task_list` unchanged | all |

## Placeholder / consistency review

- Attribute prefix standardized on `data-task-log-*` / `#task-log-*`.
- Public API names fixed: `open`, `close`, `isOpen`, `currentTaskId`, `attachDock`; optional `onLog` only if build phase needs it.
- No TBD steps remain.
