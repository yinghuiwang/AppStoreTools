# Web Agent Right Rail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Agent out of the task-log drawer tabs into a global right icon rail plus pinned conversation panel, leaving logs as an overlay that never replaces or stops Agent.

**Architecture:** `base.html` mounts `[data-agent-rail]` + `[data-agent-panel]` as flex siblings after `<main>`. `#task-log-drawer` stays a `position: fixed` overlay include after that chrome. `agent-dock.js` owns open/bind/`sessionStorage` restore; `task-log-drawer.js` owns only log SSE. Closing logs, collapsing the panel, and navigating are three different events.

**Tech Stack:** Jinja2 templates, vanilla JS (`task-log-drawer.js`, `agent-dock.js`, `dashboard.js`), CSS (`agent-rail.css`, `task-log-drawer.css`), FastAPI TestClient markup tests, Playwright E2E with mocked LLM.

**Spec:** `docs/superpowers/specs/2026-08-14-web-agent-right-rail-design.md` (approved chrome patch). Unchanged backend/tooling/SSE rules remain in `docs/superpowers/specs/2026-08-13-web-failure-agent-design.md` §§5, 7–9, 10.1, 10.2, 12, 13.1–13.3.

## Global Constraints

- Do not change `/api/agent/*` contracts, tool list, plan state machine, or SSE event names.
- Do not add an `/agent` route or replace the main column with an Agent page.
- Icon rail v1 contains only the Agent icon (no logs/settings icons).
- Logs never re-dock into `#task-log-dock` and never share a tablist with Agent.
- Restore / page change / rail-only open must not `auto_analyze` or `POST /api/agent/stream`.
- Do not make the translator streaming; do not add CLI Agent commands.
- `sessionStorage` key is exactly `asc.agent.chrome` with exactly `{agentOpen, sessionId, boundTaskId}`.
- Panel width key is `localStorage` `asc.agentPanel.width`; log width stays `asc.taskLogDrawer.width`; neither key reads the other.
- Selectors: `[data-agent-rail]`, `[data-agent-toggle]`, `[data-agent-panel]`. Do not use `data-open-agent-dock`.
- Public API: `window.AscAgentDock.bindTask(taskId)`, `setOpen(boolean)`, `getState()` → `{ open, sessionId, boundTaskId }`.
- `TaskLogDrawer.open(taskId, options)` must not recognize `options.tab`. `currentTaskId()` is the log overlay task, independent of Agent `boundTaskId`.
- Tests must not call a real LLM vendor.
- Left nav has no Agent item. Full site HTML has no `href="/agent"`.
- Collapse is not stop: `setOpen(false)` must not `abort` or `POST /api/agent/stop`. Closing the log overlay must not touch Agent.
- `pagehide` / real unload still abort fetch + `POST /api/agent/stop`.
- Narrow viewport (existing 1360px query) still squeezes; Agent must not become a modal that covers the icon rail.

---

## File structure

| Path | Responsibility |
|------|----------------|
| Create: `src/asc/web/templates/_agent_chrome.html` | Rail + conversation panel markup only. Included from `base.html`, never from the log drawer. |
| Create: `src/asc/web/static/agent-rail.css` | 48px rail, panel flex width, resize handle, overlay offset vars, Agent conversation styles moved out of `task-log-drawer.css`. |
| Modify: `src/asc/web/templates/base.html` | Delete left-nav Agent button and `#task-log-dock`. After `</main>`: include chrome, then `_task_log_drawer.html`. Link `agent-rail.css`. Keep `agent-dock.js`. |
| Modify: `src/asc/web/templates/_task_log_drawer.html` | Logs only: title, toolbar (including `data-open-agent-task`), output, follow, close, resize. No tablist, no Agent section. |
| Modify: `src/asc/web/templates/index.html` | Delete `{% block right_panel %}` dock host and `{% block task_log_dock %}`. |
| Modify: `src/asc/web/templates/build.html` | Remove `data-task-log-yield` from the scan aside. |
| Modify: `src/asc/web/static/task-log-drawer.js` | Always overlay. `open` ignores `tab`. `close` does not call Agent. Outside-click treats Agent chrome as inside. No `attachDock` / yield. |
| Modify: `src/asc/web/static/task-log-drawer.css` | Always-overlay drawer; `right` uses chrome CSS vars; delete dock/tab/Agent/yield rules. |
| Modify: `src/asc/web/static/agent-dock.js` | Query `[data-agent-panel]`. `setOpen` / `getState` / `sessionStorage` / `restoreChrome` (no stream). `bindTask` may auto-analyze. Delete `onDrawerClose`. |
| Modify: `src/asc/web/static/dashboard.js` | Keep `data-open-agent-task` on error rows. Delete `TaskLogDrawer.attachDock`. Log buttons still `TaskLogDrawer.open(taskId)` with no tab. |
| Modify: `src/asc/web/locales/zh.json`, `src/asc/web/locales/en.json` | Keep `nav.agent` and `drawer.explain_with_agent`. Delete `drawer.tab_logs` / `drawer.tab_agent` after markup no longer references them. Add `agent.resize`. |
| Modify: `tests/test_web_server.py` | Replace 08-13 §13.4 markup assertions with 08-14 §13.1. Rewrite dock/tab/attachDock tests. |
| Modify: `tests/test_web_agent_e2e.py` | Replace tab/left-nav/close-dock-aborts cases with rail/overlay/restore cases from 08-14 §13.2. |
| Do not modify | `src/asc/web/agent.py`, `agent_tools.py`, `agent_store.py`, `routes_agent.py`, `llm.py`, CLI modules. |

**Current coupling to undo (branch `agent`):**

- `base.html:484-492` left-nav `<button data-open-agent-dock>`.
- `base.html:579-582` `#task-log-dock` plus drawer include inside `<main>`.
- `_task_log_drawer.html:11-14,42-65` tablist + `#task-log-panel-agent`.
- `task-log-drawer.js:32-37,204-221,568-573,623-628,639-647,655-668,770-781` tabs, dock, `onDrawerClose`, `data-open-agent-dock`.
- `agent-dock.js:25-30` queries `#task-log-drawer`; `404-406` `open(..., { tab: "logs" })`; `624-626` search opens Agent tab; `638-644` `openBoundTask` opens drawer tab; `699-705` exposes `onDrawerClose: abortStream`.
- `dashboard.js:411-414` `attachDock`.
- `index.html:243-246` extra dock host.
- `build.html:648` `data-task-log-yield`.

---

### Task 1: Right-rail markup (HTML chrome, logs-only drawer, no left-nav Agent)

**Files:**
- Create: `src/asc/web/templates/_agent_chrome.html`
- Modify: `src/asc/web/templates/base.html:430-431` (stylesheet), `477-492` (nav), `571-583` (main/dock/drawer)
- Modify: `src/asc/web/templates/_task_log_drawer.html` (entire file)
- Modify: `src/asc/web/templates/index.html:243-246`
- Modify: `src/asc/web/locales/zh.json:106-107`, `src/asc/web/locales/en.json:106-107`
- Test: `tests/test_web_server.py` (markup tests listed in Step 1)

**Interfaces:**
- Consumes: existing `t("nav.agent")`, `t("agent.*")`, `t("drawer.explain_with_agent")`
- Produces: DOM contract `[data-agent-rail]`, `[data-agent-toggle]` (`aria-controls="agent-panel"`), `[data-agent-panel]#agent-panel` containing `data-agent-stream`, `data-agent-stop`, `data-agent-messages`, `data-agent-task-search`; logs drawer without Agent tabs; chrome is a `body` flex child after `</main>`

- [ ] **Step 1: Write the failing markup tests**

In `tests/test_web_server.py` replace `test_task_log_drawer_exposes_logs_and_agent_tabs` and `test_sidebar_agent_is_button_not_route` with:

```python
def test_homepage_exposes_agent_right_rail_chrome(client):
    resp = client.get("/")
    html = resp.text
    assert "data-agent-rail" in html
    assert "data-agent-toggle" in html
    assert "data-agent-panel" in html
    assert 'id="agent-panel"' in html
    assert "data-agent-stream" in html
    assert "data-agent-stop" in html
    assert "data-agent-messages" in html
    assert "data-agent-task-search" in html
    assert "data-open-agent-task" in html
    assert "data-task-log-resize" in html
    assert "data-agent-resize" in html
    assert 'data-task-log-tab="agent"' not in html
    assert 'id="task-log-tab-agent"' not in html
    assert 'data-task-log-panel="agent"' not in html
    assert "data-open-agent-dock" not in html
    assert 'href="/agent"' not in html
    assert 'id="task-log-dock"' not in html
    assert "agent-rail.css" in html
    assert "agent-dock.js" in html
    assert html.find("</main>") < html.find("data-agent-rail")
    assert html.find("data-agent-rail") < html.find('id="task-log-drawer"')
    nav_start = html.find("<nav")
    nav_end = html.find("</nav>")
    assert nav_start != -1 and nav_end > nav_start
    nav = html[nav_start:nav_end]
    assert "data-agent-toggle" not in nav
    assert ">Agent<" not in nav and "nav.agent" not in nav


def test_sidebar_has_no_agent_entry_and_no_agent_route(client):
    resp = client.get("/")
    assert "data-open-agent-dock" not in resp.text
    assert 'href="/agent"' not in resp.text
```

Keep `test_no_standalone_agent_page`. Update these existing assertions that still require `#task-log-dock`:

- `test_homepage_contains_command_workspace_landmarks`: delete `assert 'id="task-log-dock"' in resp.text`; add `assert "data-agent-rail" in resp.text`.
- `test_metadata_page_uses_shared_task_log_drawer`: replace the two `#task-log-dock` finds with:

```python
    assert resp.text.find('id="metadata-page-state"') < resp.text.find("</main>")
    assert resp.text.find("</main>") < resp.text.find('id="task-log-drawer"')
```

- Replace `test_feature_page_docks_task_log_outside_scrolling_content` with:

```python
@pytest.mark.parametrize(
    "path",
    ["/", "/metadata", "/build", "/urls", "/whats-new", "/iap", "/update"],
)
def test_feature_page_keeps_agent_chrome_outside_main(client, path):
    resp = client.get(path)
    html = resp.text
    assert resp.status_code == 200
    assert 'id="task-log-dock"' not in html
    assert "data-agent-rail" in html
    assert 'id="task-log-drawer"' in html
    assert html.find("</main>") < html.find("data-agent-rail")
    assert html.find("data-agent-panel") < html.find("data-agent-rail")
    assert html.find("data-agent-rail") < html.find('id="task-log-drawer"')
```

- `test_base_layout_includes_task_log_drawer_assets`: delete `assert 'id="task-log-dock"' in resp.text`; add `assert "agent-rail.css?v=" in resp.text` and `assert "data-agent-rail" in resp.text`.

Update the `_div_depth_before_marker` docstring so it no longer mentions `#task-log-dock`.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_web_server.py::test_homepage_exposes_agent_right_rail_chrome \
  tests/test_web_server.py::test_sidebar_has_no_agent_entry_and_no_agent_route \
  tests/test_web_server.py::test_feature_page_keeps_agent_chrome_outside_main \
  tests/test_web_server.py::test_homepage_contains_command_workspace_landmarks \
  tests/test_web_server.py::test_metadata_page_uses_shared_task_log_drawer \
  tests/test_web_server.py::test_base_layout_includes_task_log_drawer_assets -v
```

Expected: FAIL on missing `data-agent-rail` / still seeing `data-open-agent-dock` and `id="task-log-dock"`.

- [ ] **Step 3: Add `_agent_chrome.html`**

Create `src/asc/web/templates/_agent_chrome.html`:

```html
<aside id="agent-panel"
       class="agent-panel"
       data-agent-panel
       aria-hidden="true">
  <div class="agent-panel__resize"
       data-agent-resize
       role="separator"
       aria-orientation="vertical"
       aria-label="{{ t('agent.resize') }}"
       title="{{ t('agent.resize') }}">
    <span class="agent-panel__resize-grip" aria-hidden="true">
      <span></span><span></span><span></span>
    </span>
  </div>
  <div class="agent-dock-toolbar">
    <input type="search"
           class="field-input agent-dock-search"
           data-agent-task-search
           placeholder="{{ t('agent.search_placeholder') }}"
           autocomplete="off">
  </div>
  <div class="agent-dock-messages" data-agent-messages>
    <p class="agent-dock-empty">{{ t("agent.empty") }}</p>
  </div>
  <div class="agent-dock-composer">
    <button type="button" class="task-log-button" data-agent-stop hidden>{{ t("agent.stop") }}</button>
    <form data-agent-stream action="#" method="post">
      <input type="text" name="message" class="field-input agent-dock-input" autocomplete="off">
      <button type="submit" class="task-log-button">{{ t("agent.send") }}</button>
    </form>
  </div>
</aside>
<aside class="agent-rail" data-agent-rail>
  <button type="button"
          class="agent-rail__button"
          data-agent-toggle
          aria-pressed="false"
          aria-controls="agent-panel"
          aria-label="{{ t('nav.agent') }}"
          title="{{ t('nav.agent') }}">
    <svg class="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z"/></svg>
  </button>
</aside>
```

Do not add a panel close button.

- [ ] **Step 4: Patch `base.html` layout**

1. After the `task-log-drawer.css` link (~line 430) add:

```html
  <link rel="stylesheet" href="/static/agent-rail.css?v={{ asset_version }}">
```

2. Delete the entire left-nav Agent `<button type="button" data-open-agent-dock ...>...</button>` block (currently between Dashboard and Metadata). Nav goes Dashboard → Metadata with no Agent text.

3. Replace the main closing + dock + drawer block. Current:

```html
    {% block task_log_dock %}
    <div id="task-log-dock" class="task-log-dock" aria-hidden="true"></div>
    {% endblock %}
    {% include "_task_log_drawer.html" %}
  </main>
```

Must become:

```html
  </main>
  {% include "_agent_chrome.html" %}
  {% include "_task_log_drawer.html" %}
```

`{% block right_panel %}` stays inside `<main>` (build scan). Delete `{% block task_log_dock %}` entirely.

- [ ] **Step 5: Strip Agent from `_task_log_drawer.html`**

Replace the file with logs-only markup (keep `data-open-agent-task` on the toolbar):

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
      <h2 id="task-log-title">{{ t("drawer.title") }}</h2>
    </div>
    <button type="button" class="task-log-icon-button" data-task-log-close aria-label="{{ t('drawer.close') }}" title="{{ t('drawer.close') }}">&#215;</button>
  </header>
  <section id="task-log-panel-logs"
           class="task-log-panel"
           data-task-log-panel="logs">
    <div class="task-log-tools" role="toolbar" aria-label="{{ t('drawer.tools_aria') }}">
      <span class="task-log-status-pill" data-task-log-status-wrap>
        <span class="task-log-status-spinner" aria-hidden="true"></span>
        <span data-task-log-status>{{ t("drawer.waiting") }}</span>
      </span>
      <div>
        <button type="button" class="task-log-button" data-open-agent-task hidden>{{ t("drawer.explain_with_agent") }}</button>
        <button type="button" class="task-log-filter" data-task-log-errors aria-pressed="false">{{ t("drawer.errors_only") }}</button>
        <button type="button" class="task-log-icon-button" data-task-log-copy aria-label="{{ t('drawer.copy') }}" title="{{ t('drawer.copy') }}">&#9633;</button>
        <button type="button" class="task-log-icon-button" data-task-log-clear aria-label="{{ t('drawer.clear') }}" title="{{ t('drawer.clear') }}">&#8856;</button>
      </div>
    </div>
    <pre id="task-log-output" class="task-log-output" tabindex="0" aria-live="polite"><code>{{ t("drawer.placeholder") }}</code></pre>
    <footer class="task-log-follow">
      <label><input type="checkbox" data-task-log-follow checked> {{ t("drawer.follow") }}</label>
      <button type="button" class="task-log-button" data-task-log-latest hidden>{{ t("drawer.latest") }}</button>
      <span data-task-log-position>-- / --</span>
    </footer>
  </section>
  <div class="task-log-drawer__resize"
       data-task-log-resize
       role="separator"
       aria-orientation="vertical"
       aria-label="{{ t('drawer.resize') }}"
       title="{{ t('drawer.resize') }}">
    <span class="task-log-drawer__resize-grip" aria-hidden="true">
      <span></span><span></span><span></span>
    </span>
  </div>
</aside>
```

- [ ] **Step 6: Remove dashboard dock host and unused tab locale keys**

In `src/asc/web/templates/index.html` delete:

```html
{% block right_panel %}
<div id="task-log-dock" class="task-log-dock" aria-hidden="true"></div>
{% endblock %}
{% block task_log_dock %}{% endblock %}
```

In `zh.json` and `en.json` delete `drawer.tab_logs` and `drawer.tab_agent`. Add:

```json
  "agent.resize": "调整 Agent 面板宽度"
```

```json
  "agent.resize": "Resize Agent panel"
```

Keep `nav.agent` and `drawer.explain_with_agent`.

- [ ] **Step 7: Run markup tests to verify they pass**

Run the same pytest command as Step 2.

Expected: PASS. (`agent-rail.css` 404 is OK until Task 3 if the homepage only asserts the `<link>` string, not `client.get("/static/agent-rail.css")`. Do not fetch that URL in Task 1 tests.)

- [ ] **Step 8: Commit**

```bash
git add src/asc/web/templates/_agent_chrome.html \
  src/asc/web/templates/base.html \
  src/asc/web/templates/_task_log_drawer.html \
  src/asc/web/templates/index.html \
  src/asc/web/locales/zh.json \
  src/asc/web/locales/en.json \
  tests/test_web_server.py
git commit -m "$(cat <<'EOF'
feat(web): mount Agent on a right-rail chrome

Move Agent markup out of the log drawer and left nav so every page has a pinned rail+panel shell.
EOF
)"
```

---

### Task 2: Logs overlay-only (no dock, no Agent abort)

**Files:**
- Modify: `src/asc/web/static/task-log-drawer.js` (behavior listed below)
- Modify: `src/asc/web/static/task-log-drawer.css:10-48,129-191` (always overlay; drop dock/tabs)
- Modify: `src/asc/web/static/dashboard.js:411-414`
- Modify: `src/asc/web/templates/build.html:646-650`
- Test: `tests/test_web_server.py` (JS/CSS contract tests in Step 1)

**Interfaces:**
- Consumes: `#task-log-drawer` logs-only DOM from Task 1; CSS vars `--agent-rail-width` / `--agent-panel-width` (fallbacks 48px / 0px until Task 3–4 write them)
- Produces: `TaskLogDrawer.open(taskId, options)` with no `tab`; `close()` never calls `AscAgentDock`; `isOpen()`, `currentTaskId()` unchanged; no `attachDock` / `preferOverlay`

- [ ] **Step 1: Write the failing JS/CSS contract tests**

Replace `test_task_log_drawer_stylesheet_defines_drawer_and_dock_modes` with:

```python
def test_task_log_drawer_stylesheet_is_overlay_only(client):
    css = client.get("/static/task-log-drawer.css").text
    assert ".task-log-drawer" in css
    assert "position: fixed" in css
    assert "var(--agent-rail-width" in css
    assert "var(--agent-panel-width" in css
    assert ".task-log-drawer.is-docked" not in css
    assert ".task-log-dock" not in css
    assert "[data-task-log-yield]" not in css
    assert ".task-log-tabs" not in css
```

Replace `test_dashboard_javascript_delegates_logs_to_task_log_drawer` so it still requires `TaskLogDrawer.open` but **rejects** `attachDock`:

```python
def test_dashboard_javascript_delegates_logs_to_task_log_drawer(client):
    resp = client.get("/static/dashboard.js")
    assert resp.status_code == 200
    assert "TaskLogDrawer.open" in resp.text
    assert "TaskLogDrawer.attachDock" not in resp.text
    assert "data-open-agent-task" in resp.text
```

Replace `test_task_log_drawer_javascript_exposes_public_api` with:

```python
def test_task_log_drawer_javascript_exposes_public_api(client):
    body = client.get("/static/task-log-drawer.js").text
    assert "window.TaskLogDrawer" in body
    assert "function open(" in body
    assert "attachDock" not in body
    assert "preferOverlay" not in body
    assert 'getElementById("task-log-dock")' not in body
    assert "data-task-log-yield" not in body
    assert "AscAgentDock.onDrawerClose" not in body
    assert "/api/agent/stream" not in body
    assert "data-agent-rail" in body
    assert "data-agent-panel" in body
    assert 'closest("main")' in body
    assert "/api/task/" in body
    assert "stream?after=" in body
```

Replace `test_task_log_drawer_javascript_switches_tabs_without_agent_stream` with:

```python
def test_task_log_drawer_javascript_has_no_agent_tabs_or_abort_hook(client):
    js = client.get("/static/task-log-drawer.js").text
    page = client.get("/").text
    assert "options.tab" not in js
    assert "data-task-log-tab" not in js
    assert "data-open-agent-dock" not in js
    assert "/api/agent/stream" not in js
    assert "AscAgentDock.onDrawerClose" not in js
    assert "agent-dock.js" in page
```

Delete `test_task_log_drawer_javascript_closes_on_outside_click_in_overlay_mode` (it asserts `isOverlayMode()`). Replace it with:

```python
def test_task_log_drawer_outside_click_ignores_agent_chrome(client):
    js = client.get("/static/task-log-drawer.js").text
    assert 'closest("[data-agent-rail]")' in js
    assert 'closest("[data-agent-panel]")' in js
    assert 'closest("main")' in js
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_web_server.py::test_task_log_drawer_stylesheet_is_overlay_only \
  tests/test_web_server.py::test_dashboard_javascript_delegates_logs_to_task_log_drawer \
  tests/test_web_server.py::test_task_log_drawer_javascript_exposes_public_api \
  tests/test_web_server.py::test_task_log_drawer_javascript_has_no_agent_tabs_or_abort_hook \
  tests/test_web_server.py::test_task_log_drawer_outside_click_ignores_agent_chrome -v
```

Expected: FAIL (`attachDock` still present, `.is-docked` still in CSS).

- [ ] **Step 3: Rewrite `task-log-drawer.js` overlay-only**

Keep log SSE, status preflight, resize (`asc.taskLogDrawer.width`), copy/clear/errors/follow, `syncExplainButton`. Delete tab/dock/Agent-nav/yield.

Empty stub when `#task-log-drawer` is missing:

```javascript
    window.TaskLogDrawer = {
      open: function () {},
      close: function () {},
      isOpen: function () { return false; },
      currentTaskId: function () { return null; }
    };
```

Delete variables: `tabButtons`, `agentPanel`, `agentNav`, `agentForm`, `overlayMedia`, `dockHost`, `forceOverlay`, `homeParent`, `homeNextSibling`, `activeTab`.

Keep `logsPanel` only if still useful for layout; the remaining section can stay unhidden.

Replace mode helpers with:

```javascript
  function isAgentChrome(node) {
    if (!node || !node.closest) return false;
    return !!(node.closest("[data-agent-rail]") || node.closest("[data-agent-panel]"));
  }

  function setBackgroundInert(enabled) {
    if (enabled) {
      if (backgroundInertEntries) return;
      var main = document.querySelector("body > main");
      if (!main) return;
      backgroundInertEntries = [{ el: main, state: applyInertState(main) }];
    } else if (backgroundInertEntries) {
      backgroundInertEntries.forEach(function (entry) {
        releaseInertState(entry.el, entry.state);
      });
      backgroundInertEntries = null;
    }
  }

  function updateMode() {
    drawer.classList.add("is-overlay");
    drawer.classList.remove("is-docked");
    var modal = isDrawerOpen();
    drawer.setAttribute("aria-modal", modal ? "true" : "false");
    setBackgroundInert(modal);
  }
```

Focus trap: only cycle Tab when focus is **already inside** the drawer. Do not steal focus from the rail/panel:

```javascript
  function trapDrawerFocus(event) {
    if (event.key !== "Tab" || !isDrawerOpen()) return;
    if (!drawer.contains(document.activeElement)) return;
    var focusables = drawerFocusables();
    if (!focusables.length) return;
    var first = focusables[0];
    var last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
```

`open(taskId, options)`: delete `tab` handling. Always logs. If `taskId` is empty, still open the overlay (no stream) so callers can show an empty log pane; do not talk to Agent.

```javascript
  function open(taskId, options) {
    options = options || {};
    var hasTask = taskId != null && String(taskId) !== "";
    if (!hasTask) {
      previouslyFocused = document.activeElement;
      openDrawerPanel();
      suppressNextOutsideClick = true;
      setTimeout(function () { suppressNextOutsideClick = false; }, 0);
      return;
    }
    var nextId = String(taskId);
    if (isDrawerOpen() && activeTaskId === nextId) {
      suppressNextOutsideClick = true;
      setTimeout(function () { suppressNextOutsideClick = false; }, 0);
      return;
    }
    // ... existing closeSource/cancelPreflight/resetLogState/loadStatusThenStream ...
    openDrawerPanel();
  }
```

`close()`: delete the `AscAgentDock.onDrawerClose` block. Do not abort Agent. Keep closing EventSource for **logs**.

Escape: `if (event.key === "Escape" && isDrawerOpen()) close();` — logs only.

Outside click:

```javascript
  document.addEventListener("click", function (event) {
    if (suppressNextOutsideClick) {
      suppressNextOutsideClick = false;
      return;
    }
    if (!isDrawerOpen()) return;
    if (drawer.contains(event.target)) return;
    if (isAgentChrome(event.target)) return;
    if (!event.target.closest || !event.target.closest("main")) return;
    close();
  });
```

Delete `attachDock`, `preferOverlay`, `setYieldPanelsHidden`, `moveToHome`, `setActiveTab`, `updateAgentNavPressed`, tab button listeners, `agentNav` click, `explainControl` click (document-level `data-open-agent-task` lives in `agent-dock.js`), `agentForm` preventDefault, `overlayMedia` listener, and the `#task-log-dock` auto-attach.

Public API:

```javascript
  window.TaskLogDrawer = {
    open: open,
    close: close,
    isOpen: isDrawerOpen,
    currentTaskId: function () { return activeTaskId; }
  };
```

Call `updateMode()` once at init (no dock host).

- [ ] **Step 4: Make drawer CSS always overlay**

In `task-log-drawer.css` replace `.task-log-drawer` positioning so it is never a flex sibling:

```css
.task-log-drawer {
  --task-log-drawer-width: 390px;
  position: fixed;
  top: 0;
  right: calc(var(--agent-rail-width, 48px) + var(--agent-panel-width, 0px));
  bottom: 0;
  z-index: 40;
  width: var(--task-log-drawer-width);
  min-width: 0;
  height: auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: auto minmax(0, 1fr);
  border-left: 1px solid var(--border-default);
  background: #0c0c10;
  box-shadow: -14px 0 30px rgba(0, 0, 0, .22);
  transform: translateX(100%);
  transition: transform .25s cubic-bezier(.4, 0, .2, 1);
  pointer-events: none;
}
```

Delete `.task-log-drawer.is-overlay` / `.is-docked` / `.task-log-dock` / `[data-task-log-yield][data-yielded="true"]` / `.task-log-tabs` rules / `[data-task-log-panel="agent"]` rules.

Keep `.task-log-drawer.is-open`, `[hidden]`, header, resize, logs panel grid, status colors. Leave Agent conversation rules in this file until Task 3 moves them (Task 2 CSS test must not require their absence yet). If `.task-log-tabs` deletion makes `test_task_log_drawer_stylesheet_is_overlay_only` pass, stop.

- [ ] **Step 5: Remove dock callers**

`dashboard.js` — delete:

```javascript
  if (window.TaskLogDrawer) {
    var dock = document.getElementById("task-log-dock");
    TaskLogDrawer.attachDock(dock);
  }
```

`openLogs` already calls `TaskLogDrawer.open(taskId, { title, onProgress, ... })` with no `tab` — leave it.

`build.html` scan aside: delete the `data-task-log-yield` attribute. Keep `x-data`, `x-show`, width classes.

- [ ] **Step 6: Run JS/CSS tests plus the timeout node harness**

Run:

```bash
pytest tests/test_web_server.py::test_task_log_drawer_stylesheet_is_overlay_only \
  tests/test_web_server.py::test_dashboard_javascript_delegates_logs_to_task_log_drawer \
  tests/test_web_server.py::test_task_log_drawer_javascript_exposes_public_api \
  tests/test_web_server.py::test_task_log_drawer_javascript_has_no_agent_tabs_or_abort_hook \
  tests/test_web_server.py::test_task_log_drawer_outside_click_ignores_agent_chrome \
  tests/test_web_server.py::test_task_log_drawer_timeout_reconnect_resumes_from_last_sequence \
  tests/test_web_server.py::test_task_log_drawer_reconnects_after_timeout \
  tests/test_web_server.py::test_task_log_drawer_resize_handle_contract -v
```

Expected: PASS. Node harness still evals `task-log-drawer.js` against a fake `#task-log-drawer`; it must not require `#task-log-dock`. Do not restore `isOverlayMode`.

- [ ] **Step 7: Commit**

```bash
git add src/asc/web/static/task-log-drawer.js \
  src/asc/web/static/task-log-drawer.css \
  src/asc/web/static/dashboard.js \
  src/asc/web/templates/build.html \
  tests/test_web_server.py
git commit -m "$(cat <<'EOF'
fix(web): keep task logs as an overlay

Stop docking logs into the main column and stop aborting Agent when the log overlay closes.
EOF
)"
```

---

### Task 3: Agent rail CSS and overlay offset tokens

**Files:**
- Create: `src/asc/web/static/agent-rail.css`
- Modify: `src/asc/web/static/task-log-drawer.css` (delete remaining `.agent-*` rules after the copy)
- Modify: `tests/test_web_server.py` (`test_agent_dock_renders_assistant_markdown` CSS source)
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: Task 1 markup classes (`agent-rail`, `agent-panel`, `data-agent-resize`); Task 2 overlay `right: calc(var(--agent-rail-width) + var(--agent-panel-width))`
- Produces: `:root { --agent-rail-width: 48px; --agent-panel-width: 0px; }`; `[data-agent-panel].is-open` uses `--agent-panel-width`; Agent markdown/card styles live in `agent-rail.css`

- [ ] **Step 1: Write the failing stylesheet tests**

Add:

```python
def test_agent_rail_stylesheet_defines_chrome_layout(client):
    resp = client.get("/static/agent-rail.css")
    assert resp.status_code == 200
    css = resp.text
    assert "--agent-rail-width: 48px" in css
    assert "--agent-panel-width" in css
    assert "[data-agent-rail]" in css
    assert "[data-agent-panel]" in css
    assert "[data-agent-panel].is-open" in css
    assert "flex: 0 0 48px" in css or "width: 48px" in css
    assert ".agent-msg--md" in css
    assert "list-style: disc" in css
    assert "[data-agent-resize]" in css or ".agent-panel__resize" in css
```

Change `test_agent_dock_renders_assistant_markdown` so markdown CSS is loaded from `agent-rail.css`:

```python
    css = client.get("/static/agent-rail.css").text
    assert ".agent-msg--md" in css
    assert "list-style: disc" in css
```

Also assert Agent rules are gone from the log stylesheet:

```python
def test_task_log_drawer_css_has_no_agent_conversation_rules(client):
    css = client.get("/static/task-log-drawer.css").text
    assert ".agent-msg--md" not in css
    assert ".agent-plan-card" not in css
    assert ".agent-dock-messages" not in css
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_web_server.py::test_agent_rail_stylesheet_defines_chrome_layout \
  tests/test_web_server.py::test_agent_dock_renders_assistant_markdown \
  tests/test_web_server.py::test_task_log_drawer_css_has_no_agent_conversation_rules -v
```

Expected: FAIL (`/static/agent-rail.css` 404).

- [ ] **Step 3: Create `agent-rail.css`**

Create `src/asc/web/static/agent-rail.css` with:

```css
:root {
  --agent-rail-width: 48px;
  --agent-panel-width: 0px;
}

[data-agent-rail] {
  flex: 0 0 48px;
  width: 48px;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 0;
  border-left: 1px solid var(--border-default);
  background: var(--bg-raised);
  z-index: 50;
}

.agent-rail__button {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.agent-rail__button[aria-pressed="true"] {
  background: var(--accent-glow);
  color: var(--accent);
}

[data-agent-panel] {
  flex: 0 0 0;
  width: 0;
  min-width: 0;
  height: 100%;
  overflow: hidden;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  background: #0c0c10;
  border-left: 1px solid var(--border-default);
  z-index: 45;
}

[data-agent-panel].is-open {
  flex: 0 0 var(--agent-panel-width, 390px);
  width: var(--agent-panel-width, 390px);
  overflow: hidden;
}

.agent-panel__resize { /* copy geometry from .task-log-drawer__resize */ }
```

Then **cut** (do not duplicate forever) every `.agent-dock-*`, `.agent-msg*`, `.agent-tool-status`, `.agent-plan-*`, `.agent-bound-meta`, `.agent-search-results` block from `task-log-drawer.css` (currently ~lines 193–356) into this file. Keep log-only rules in `task-log-drawer.css`.

Do not add a `@media (max-width: 1360px)` rule that turns the panel into a full-screen modal or sets the rail to `display: none`.

- [ ] **Step 4: Run stylesheet tests to verify they pass**

Run the same pytest command as Step 2.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/static/agent-rail.css \
  src/asc/web/static/task-log-drawer.css \
  tests/test_web_server.py
git commit -m "$(cat <<'EOF'
feat(web): style the Agent right rail

Give the pinned rail and panel their own stylesheet so log overlay CSS no longer owns Agent chrome.
EOF
)"
```

---

### Task 4: Agent chrome state (`setOpen`, `getState`, `sessionStorage`, restore without stream)

**Files:**
- Modify: `src/asc/web/static/agent-dock.js` (new chrome functions; keep markdown/SSE/cards)
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: Task 1 `[data-agent-panel]` / `[data-agent-toggle]` / `[data-agent-resize]`; `GET /api/agent/sessions?task_id=` `{ session: { id, profile, ... }, messages, plans }` (unchanged)
- Produces:
  - `window.AscAgentDock.setOpen(boolean)` — toggles panel only
  - `window.AscAgentDock.getState()` → `{ open: boolean, sessionId: string, boundTaskId: string }`
  - `persistChrome()` writes `sessionStorage["asc.agent.chrome"]`
  - `restoreChrome()` may GET sessions + `renderHistory`; function body contains no `auto_analyze: true` and does not call `startStream`
  - `--agent-panel-width` on `document.documentElement`; `localStorage["asc.agentPanel.width"]`

- [ ] **Step 1: Write the failing chrome-API tests**

Add to `tests/test_web_server.py`:

```python
def _js_function_source(js: str, name: str) -> str:
    marker = "function " + name + "("
    start = js.index(marker)
    i = js.index("{", start)
    depth = 0
    for index, char in enumerate(js[i:], start=i):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return js[start : index + 1]
    raise AssertionError("unterminated function " + name)


def test_agent_dock_javascript_exposes_chrome_state_and_restore(client):
    js = client.get("/static/agent-dock.js").text
    assert 'sessionStorage.setItem("asc.agent.chrome"' in js or "sessionStorage.setItem('asc.agent.chrome'" in js
    assert "function setOpen(" in js
    assert "function getState(" in js
    assert "function restoreChrome(" in js
    assert "function persistChrome(" in js
    assert "function bindTask(" in js
    assert "onDrawerClose" not in js
    assert "getElementById(\"task-log-drawer\")" not in js
    assert 'querySelector("[data-agent-panel]")' in js
    assert 'querySelector("[data-agent-toggle]")' in js
    assert "asc.agentPanel.width" in js
    assert "AscAgentDock" in js
    assert "setOpen: setOpen" in js
    assert "getState: getState" in js
    assert "bindTask: bindTask" in js
    restore = _js_function_source(js, "restoreChrome")
    assert "auto_analyze: true" not in restore
    assert "startStream" not in restore
    bind = _js_function_source(js, "bindTask")
    assert "auto_analyze: true" in bind
```

Keep `test_agent_dock_javascript_uses_post_stream_not_event_source` (still requires stream/apply/reject URLs). Add to it (or this new test): `assert '{ tab: "logs" }' not in js` and `assert '{ tab: "agent" }' not in js`.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_web_server.py::test_agent_dock_javascript_exposes_chrome_state_and_restore -v
```

Expected: FAIL (`restoreChrome` missing; `onDrawerClose` still present).

- [ ] **Step 3: Retarget `agent-dock.js` to the panel and add chrome state**

Replace the top DOM lookup:

```javascript
  var panel = document.querySelector("[data-agent-panel]");
  var toggle = document.querySelector("[data-agent-toggle]");
  var messagesEl = panel ? panel.querySelector("[data-agent-messages]") : null;
  var stopBtn = panel ? panel.querySelector("[data-agent-stop]") : null;
  var form = panel ? panel.querySelector("[data-agent-stream]") : null;
  var searchInput = panel ? panel.querySelector("[data-agent-task-search]") : null;
  var toolbar = panel ? panel.querySelector(".agent-dock-toolbar") : null;
  var resizeHandle = panel ? panel.querySelector("[data-agent-resize]") : null;
```

Add state + storage (next to `boundTaskId` / `sessionId`):

```javascript
  var agentOpen = false;
  var CHROME_STORAGE_KEY = "asc.agent.chrome";
  var PANEL_WIDTH_STORAGE_KEY = "asc.agentPanel.width";
  var DEFAULT_PANEL_WIDTH = 390;
  var MIN_PANEL_WIDTH = 280;
  var MAX_PANEL_WIDTH = 720;

  function clampPanelWidth(px) {
    var minW = MIN_PANEL_WIDTH;
    var viewport = Number(window.innerWidth);
    if (!Number.isFinite(viewport) || viewport <= 0) viewport = 1440;
    var maxW = Math.min(MAX_PANEL_WIDTH, Math.round(viewport * 0.5));
    if (maxW < minW) maxW = minW;
    var n = Number(px);
    if (!Number.isFinite(n)) n = DEFAULT_PANEL_WIDTH;
    return Math.round(Math.min(maxW, Math.max(minW, n)));
  }

  function readStoredPanelWidth() {
    try {
      var raw = localStorage.getItem(PANEL_WIDTH_STORAGE_KEY);
      if (raw == null || raw === "") return DEFAULT_PANEL_WIDTH;
      return clampPanelWidth(raw);
    } catch (error) {
      return DEFAULT_PANEL_WIDTH;
    }
  }

  var panelWidth = readStoredPanelWidth();

  function persistPanelWidth(px) {
    panelWidth = clampPanelWidth(px);
    try { localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(panelWidth)); } catch (error) { /* ignore */ }
    return panelWidth;
  }

  function applyPanelWidthVar() {
    var widthPx = agentOpen ? panelWidth : 0;
    try {
      document.documentElement.style.setProperty("--agent-panel-width", widthPx + "px");
    } catch (error) { /* ignore */ }
  }

  function emptyChrome() {
    return { agentOpen: false, sessionId: "", boundTaskId: "" };
  }

  function readChrome() {
    try {
      var raw = sessionStorage.getItem(CHROME_STORAGE_KEY);
      if (!raw) return emptyChrome();
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return emptyChrome();
      return {
        agentOpen: parsed.agentOpen === true,
        sessionId: typeof parsed.sessionId === "string" ? parsed.sessionId : "",
        boundTaskId: typeof parsed.boundTaskId === "string" ? parsed.boundTaskId : ""
      };
    } catch (error) {
      return emptyChrome();
    }
  }

  function persistChrome() {
    try {
      sessionStorage.setItem(CHROME_STORAGE_KEY, JSON.stringify({
        agentOpen: !!agentOpen,
        sessionId: sessionId ? String(sessionId) : "",
        boundTaskId: boundTaskId ? String(boundTaskId) : ""
      }));
    } catch (error) { /* in-memory only */ }
  }

  function getState() {
    return {
      open: !!agentOpen,
      sessionId: sessionId ? String(sessionId) : "",
      boundTaskId: boundTaskId ? String(boundTaskId) : ""
    };
  }

  function setOpen(open) {
    agentOpen = !!open;
    if (panel) {
      panel.classList.toggle("is-open", agentOpen);
      panel.setAttribute("aria-hidden", agentOpen ? "false" : "true");
    }
    if (toggle) {
      toggle.setAttribute("aria-pressed", agentOpen ? "true" : "false");
    }
    applyPanelWidthVar();
    persistChrome();
  }

  async function restoreChrome() {
    var chrome = readChrome();
    sessionId = chrome.sessionId || "";
    boundTaskId = chrome.boundTaskId || "";
    setOpen(chrome.agentOpen);
    if (!boundTaskId) {
      showEmpty();
      return;
    }
    var seq = ++bindSeq;
    try {
      var response = await fetch("/api/agent/sessions?task_id=" + encodeURIComponent(boundTaskId), {
        headers: { Accept: "application/json" }
      });
      if (seq !== bindSeq) return;
      if (!response.ok) {
        showEmpty();
        return;
      }
      var payload = await response.json();
      if (seq !== bindSeq) return;
      var session = payload.session || {};
      if (session.id) sessionId = String(session.id);
      persistChrome();
      setBoundMeta({ id: boundTaskId, profile: session.profile }, session.profile);
      renderHistory(payload);
    } catch (error) {
      if (seq !== bindSeq) return;
      showEmpty();
    }
  }
```

`restoreChrome` must not call `startStream` or `bindTask`.

Wire toggle + boot + persist on SSE ids:

- After `handleFrame` sets `sessionId` / `boundTaskId` on `session` or `done`, call `persistChrome()`.
- `if (toggle) toggle.addEventListener("click", function () { setOpen(!agentOpen); });`
- At end of IIFE: `restoreChrome();`
- Keep existing `pagehide` → `abortStream()` (this **is** stop). `setOpen(false)` must **not** call `abortStream` or `requestStop`.

Panel resize: copy the pointerdown/move/up pattern from the log drawer, but write `PANEL_WIDTH_STORAGE_KEY` and call `applyPanelWidthVar()` while `agentOpen` is true. Ignore pointer events when the panel is collapsed.

Replace the public object (keep markdown helpers used by E2E):

```javascript
  window.AscAgentDock = {
    bindTask: bindTask,
    setOpen: setOpen,
    getState: getState,
    renderMarkdown: renderMarkdown,
    setAssistantMarkdown: setAssistantMarkdown
  };
```

Delete `start` and `onDrawerClose`.

Leave `bindTask` / search / apply wiring for Task 5 **except** `bindTask` must keep compiling. If `openBoundTask` still calls `TaskLogDrawer.open(..., { tab: "agent" })`, delete the `tab` argument now so Task 1/2 tests that forbid `{ tab: "agent" }` in this file can pass:

```javascript
  function openBoundTask(taskId) {
    if (!taskId) return;
    setOpen(true);
    bindTask(taskId);
  }
```

Do **not** add `auto_analyze` to `restoreChrome` even if history is empty.

- [ ] **Step 4: Run chrome-API tests to verify they pass**

Run:

```bash
pytest tests/test_web_server.py::test_agent_dock_javascript_exposes_chrome_state_and_restore \
  tests/test_web_server.py::test_agent_dock_javascript_uses_post_stream_not_event_source \
  tests/test_web_server.py::test_agent_dock_renders_assistant_markdown -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/static/agent-dock.js tests/test_web_server.py
git commit -m "$(cat <<'EOF'
feat(web): persist Agent chrome across pages

Restore open state and bound history from sessionStorage without starting a new LLM stream.
EOF
)"
```

---

### Task 5: Bind, explain, apply, and search without drawer tabs

**Files:**
- Modify: `src/asc/web/static/agent-dock.js` (`bindTask`, search click, `applyPlan`, `openBoundTask`)
- Test: `tests/test_web_server.py` (string contracts)

**Interfaces:**
- Consumes: `setOpen` / `persistChrome` / `restoreChrome` from Task 4; `TaskLogDrawer.open(taskId)` overlay-only from Task 2; `GET /api/agent/failed-tasks`; `POST /api/agent/apply`
- Produces: `bindTask(taskId)` always `setOpen(true)` then history-or-`auto_analyze` (08-13 §10.2); explain does not close logs; apply with `new_task_id` opens logs overlay and does **not** call `bindTask`; search click does not call `TaskLogDrawer.open`

- [ ] **Step 1: Write the failing bind/apply tests**

Add:

```python
def test_agent_dock_bind_and_apply_do_not_use_log_tabs(client):
    js = client.get("/static/agent-dock.js").text
    bind = _js_function_source(js, "bindTask")
    assert "setOpen(true)" in bind
    assert "auto_analyze: true" in bind
    apply_src = _js_function_source(js, "applyPlan")
    assert "TaskLogDrawer.open" in apply_src
    assert "bindTask" not in apply_src
    assert "tab:" not in apply_src
    assert "TaskLogDrawer.open(task.id" not in js
    assert '{ tab: "agent" }' not in js
    assert '{ tab: "logs" }' not in js
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/test_web_server.py::test_agent_dock_bind_and_apply_do_not_use_log_tabs -v
```

Expected: FAIL until `applyPlan` / search stop passing `tab` and search stops opening the log drawer.

- [ ] **Step 3: Implement bind/explain/apply/search**

`bindTask` — keep abort of the **previous Agent stream** when switching tasks (that is a bind change, not overlay close). Prefix with `setOpen(true)` and `persistChrome()` after ids settle:

```javascript
  async function bindTask(taskId) {
    if (taskId == null || String(taskId) === "") return;
    var seq = ++bindSeq;
    abortStream();
    boundTaskId = String(taskId);
    sessionId = null;
    setOpen(true);
    persistChrome();
    showEmpty();
    setBoundMeta({ id: boundTaskId }, "");
    var payload;
    try {
      var response = await fetch("/api/agent/sessions?task_id=" + encodeURIComponent(boundTaskId), {
        headers: { Accept: "application/json" }
      });
      if (seq !== bindSeq) return;
      if (!response.ok) return;
      payload = await response.json();
    } catch (error) {
      if (seq !== bindSeq) return;
      return;
    }
    if (seq !== bindSeq) return;
    var session = payload.session || {};
    sessionId = session.id || null;
    persistChrome();
    setBoundMeta({ id: boundTaskId, profile: session.profile }, session.profile);
    renderHistory(payload);
    if (!hasUserOrAssistant(payload.messages)) {
      appendBubble("user", tt("agent.auto_analyze_label"));
      startStream({
        task_id: boundTaskId,
        session_id: sessionId,
        message: "",
        auto_analyze: true
      });
    }
  }
```

Search result click — delete `TaskLogDrawer.open`. Only `bindTask(task.id)` (which opens the panel).

`applyPlan` success branch:

```javascript
      setCardStatus(card, payload.status || "applied", payload.rerun_error);
      if (payload.new_task_id && window.TaskLogDrawer) {
        TaskLogDrawer.open(payload.new_task_id);
      }
```

Do not call `bindTask(payload.new_task_id)`. Do not change `sessionId` / `boundTaskId` / `agentOpen`.

Document click for `[data-open-agent-task]` already calls `openBoundTask`. Keep using `TaskLogDrawer.currentTaskId()` as fallback when the toolbar button has no `data-task-id`. Do not call `TaskLogDrawer.close()`.

Composer submit: unchanged (`auto_analyze: false`). Opening the rail with no bound task still must not stream (existing `if (!taskId && !sid) return` in `startStream`).

- [ ] **Step 4: Run bind/apply tests to verify they pass**

Run:

```bash
pytest tests/test_web_server.py::test_agent_dock_bind_and_apply_do_not_use_log_tabs \
  tests/test_web_server.py::test_agent_dock_javascript_exposes_chrome_state_and_restore \
  tests/test_web_server.py::test_dashboard_javascript_adds_explain_on_error_rows -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/static/agent-dock.js tests/test_web_server.py
git commit -m "$(cat <<'EOF'
feat(web): bind Agent without stealing the log overlay

Explain and search retarget the pinned panel; apply opens logs for the new task without rebinding the session.
EOF
)"
```

---

### Task 6: Playwright E2E for rail, overlay, restore, and apply

**Files:**
- Modify: `tests/test_web_agent_e2e.py`
- Test: `tests/test_web_agent_e2e.py`

**Interfaces:**
- Consumes: `AscAgentDock.setOpen` / `getState` / `bindTask` from Tasks 4–5; `TaskLogDrawer.open` overlay from Task 2; `AgentStore.append_message` / `get_or_create_session`
- Produces: E2E coverage for 08-14 §13.2; old `#task-log-tab-agent` / `data-open-agent-dock` / close-dock-aborts cases gone

- [ ] **Step 1: Rewrite helpers and delete obsolete cases**

Replace `_expect_agent_tab` / `_open_*` / `_close_dock` usage.

```python
def _expect_agent_open(page: Page) -> None:
    expect(page.locator("[data-agent-rail]")).to_be_visible()
    expect(page.locator("[data-agent-panel].is-open")).to_be_visible()
    assert page.evaluate("() => window.AscAgentDock.getState().open") is True


def _expect_agent_closed(page: Page) -> None:
    assert page.evaluate("() => window.AscAgentDock.getState().open") is False
    expect(page.locator("[data-agent-rail]")).to_be_visible()


def _open_dashboard_explain(page: Page, task_id: str) -> None:
    page.locator('[data-dashboard-filter="status"]').select_option("error")
    button = page.locator(f'.dashboard-history [data-open-agent-task][data-task-id="{task_id}"]')
    expect(button).to_be_visible()
    button.click()
    _expect_agent_open(page)


def _open_drawer_explain(page: Page, task_id: str) -> None:
    page.locator(f'[data-dashboard-log-task="{task_id}"]').first.click()
    expect(page.locator("#task-log-drawer.is-open")).to_be_visible()
    explain = page.locator("#task-log-drawer [data-open-agent-task]")
    expect(explain).to_be_visible()
    explain.click()
    _expect_agent_open(page)
    expect(page.locator("#task-log-drawer.is-open")).to_be_visible()


def _close_log_overlay(page: Page, how: str) -> None:
    expect(page.locator("#task-log-drawer.is-open")).to_be_visible()
    if how == "x":
        page.locator("[data-task-log-close]").click()
    elif how == "escape":
        page.keyboard.press("Escape")
    elif how == "overlay":
        page.locator("main").click(position={"x": 24, "y": 24}, force=True)
    else:
        raise ValueError(how)
    expect(page.locator("#task-log-drawer.is-open")).to_have_count(0)
```

Delete tests that click `[data-open-agent-dock]` or assert `#task-log-tab-agent` / `#task-log-tab-logs`.

Replace `test_sidebar_agent_opens_dock_without_streaming` with rail toggle:

```python
def test_agent_rail_toggle_opens_panel_without_streaming(agent_ui: AgentE2E):
    page = agent_ui.page
    _goto_ready(page)
    expect(page.locator("[data-agent-rail]")).to_be_visible()
    page.locator("[data-agent-toggle]").click()
    _expect_agent_open(page)
    expect(page.locator("[data-agent-messages] .agent-dock-empty")).to_be_visible()
    page.wait_for_timeout(400)
    assert agent_ui.spies["stream"] == []
    assert agent_ui.llm.calls == 0
    page.locator("[data-agent-toggle]").click()
    _expect_agent_closed(page)
    expect(page.locator("[data-agent-rail]")).to_be_visible()
```

Replace drawer-resize-via-agent-nav tests:

- `test_agent_panel_drag_resizes_and_persists`: open via `[data-agent-toggle]`, drag `[data-agent-resize]`, assert `localStorage.asc.agentPanel.width`.
- Keep a log-overlay resize test that opens a task log (`[data-dashboard-log-task]`) and drags `[data-task-log-resize]`, asserting `asc.taskLogDrawer.width` and that `asc.agentPanel.width` is unchanged.

Markdown tests that used the left-nav button should open via `[data-agent-toggle]` + `setAssistantMarkdown` evaluate, or via `_open_dashboard_explain`.

- [ ] **Step 2: Add §13.2 overlay / restore / apply cases**

```python
def test_opening_and_closing_logs_does_not_change_agent_session(agent_ui: AgentE2E):
    agent_ui.llm.impl = ScriptedLLM([[
        {"content": TOKEN_STREAM, "finish_reason": "stop"},
    ]])
    page = agent_ui.page
    _goto_ready(page)
    _open_dashboard_explain(page, agent_ui.task_id)
    expect(page.locator(".agent-msg--assistant")).to_contain_text(TOKEN_STREAM)
    before = page.evaluate("() => window.AscAgentDock.getState()")
    page.locator(f'[data-dashboard-log-task="{agent_ui.task_id}"]').first.click()
    expect(page.locator("#task-log-drawer.is-open")).to_be_visible()
    mid = page.evaluate("() => window.AscAgentDock.getState()")
    assert mid["sessionId"] == before["sessionId"]
    assert mid["boundTaskId"] == before["boundTaskId"]
    _close_log_overlay(page, "x")
    after = page.evaluate("() => window.AscAgentDock.getState()")
    assert after["sessionId"] == before["sessionId"]
    assert after["boundTaskId"] == before["boundTaskId"]
    assert after["open"] is True


def test_collapsing_agent_does_not_close_log_overlay(agent_ui: AgentE2E):
    page = agent_ui.page
    _goto_ready(page)
    page.locator(f'[data-dashboard-log-task="{agent_ui.task_id}"]').first.click()
    expect(page.locator("#task-log-drawer.is-open")).to_be_visible()
    page.locator("[data-agent-toggle]").click()
    _expect_agent_open(page)
    page.locator("[data-agent-toggle]").click()
    _expect_agent_closed(page)
    expect(page.locator("#task-log-drawer.is-open")).to_be_visible()


def test_explain_keeps_log_overlay_open(agent_ui: AgentE2E):
    agent_ui.llm.impl = ScriptedLLM([[
        {"content": TOKEN_STREAM, "finish_reason": "stop"},
    ]])
    page = agent_ui.page
    _goto_ready(page)
    _open_drawer_explain(page, agent_ui.task_id)
    expect(page.locator("#task-log-drawer.is-open")).to_be_visible()
    expect(page.locator(".agent-msg--assistant")).to_contain_text(TOKEN_STREAM)


def test_restore_chrome_renders_history_without_streaming(agent_ui: AgentE2E):
    session = agent_ui.agents.get_or_create_session(agent_ui.task_id, "myapp")
    agent_ui.agents.append_message(session["id"], "user", "please explain")
    agent_ui.agents.append_message(session["id"], "assistant", "history-restore-ok")
    page = agent_ui.page
    _goto_ready(page)
    page.evaluate(
        """([open, sessionId, boundTaskId]) => {
          sessionStorage.setItem("asc.agent.chrome", JSON.stringify({
            agentOpen: open, sessionId, boundTaskId
          }));
        }""",
        [True, session["id"], agent_ui.task_id],
    )
    agent_ui.spies["stream"].clear()
    page.reload(wait_until="domcontentloaded")
    page.wait_for_function("() => window.TaskLogDrawer && window.AscAgentDock && window.t")
    _expect_agent_open(page)
    expect(page.locator("[data-agent-messages]")).to_contain_text("history-restore-ok")
    page.wait_for_timeout(400)
    assert agent_ui.spies["stream"] == []
    assert agent_ui.llm.calls == 0


def test_apply_opens_log_overlay_without_rebinding_session(agent_ui: AgentE2E):
    rounds = _propose_rounds(
        agent_ui.task_id,
        "app.csv",
        mutations=[_csv_mutation("app.csv")],
        summary=PLAN_MUTATIONS,
        token=TOKEN_MUTATIONS,
    )
    agent_ui.llm.impl = ScriptedLLM(rounds)
    page = agent_ui.page
    _goto_ready(page)
    _open_dashboard_explain(page, agent_ui.task_id)
    card = page.locator(".agent-plan-card")
    expect(card.get_by_role("button", name="应用", exact=True)).to_be_visible()
    before = page.evaluate("() => window.AscAgentDock.getState()")
    card.get_by_role("button", name="应用", exact=True).click()
    expect(page.locator("#task-log-drawer.is-open")).to_be_visible()
    after = page.evaluate("() => window.AscAgentDock.getState()")
    assert after["sessionId"] == before["sessionId"]
    assert after["boundTaskId"] == before["boundTaskId"]
    assert after["open"] is True
    assert "new" in agent_ui.csv_path.read_text(encoding="utf-8")
```

Replace `test_closing_dock_does_not_apply` to close the **log overlay** (x / escape / main click) after a plan card is visible, and also assert `getState().open is True` and `spies["apply"] == []`.

**Delete** `test_closing_dock_aborts_stream_and_posts_stop`. Replace with:

```python
def test_closing_log_overlay_does_not_stop_agent_stream(agent_ui: AgentE2E):
    started = threading.Event()
    release = threading.Event()
    agent_ui.llm.impl = BlockingLLM(started, release)
    page = agent_ui.page
    try:
        _goto_ready(page)
        _open_drawer_explain(page, agent_ui.task_id)
        expect(page.locator(".agent-msg--assistant")).to_contain_text(TOKEN_BLOCKING)
        assert started.wait(timeout=5)
        stop_before = list(agent_ui.spies["stop"])
        _close_log_overlay(page, "x")
        page.wait_for_timeout(400)
        assert agent_ui.spies["stop"] == stop_before
        assert page.evaluate("() => window.AscAgentDock.getState().open") is True
        expect(page.locator(".agent-msg--assistant")).to_contain_text(TOKEN_BLOCKING)
    finally:
        release.set()


def test_collapsing_panel_does_not_stop_agent_stream(agent_ui: AgentE2E):
    started = threading.Event()
    release = threading.Event()
    agent_ui.llm.impl = BlockingLLM(started, release)
    page = agent_ui.page
    try:
        _goto_ready(page)
        _open_dashboard_explain(page, agent_ui.task_id)
        expect(page.locator(".agent-msg--assistant")).to_contain_text(TOKEN_BLOCKING)
        assert started.wait(timeout=5)
        page.locator("[data-agent-toggle]").click()
        _expect_agent_closed(page)
        page.wait_for_timeout(300)
        assert agent_ui.spies["stop"] == []
        page.locator("[data-agent-toggle]").click()
        _expect_agent_open(page)
        expect(page.locator(".agent-msg--assistant")).to_contain_text(TOKEN_BLOCKING)
    finally:
        release.set()
```

Keep plan-card apply-visible-after-done / empty-mutations tests; they should use `_open_drawer_explain` or `_open_dashboard_explain` (both now keep/open the rail, not tabs).

- [ ] **Step 3: Run E2E (skip allowed if Chromium missing)**

Run:

```bash
pytest tests/test_web_agent_e2e.py -v
```

Expected: PASS, or skip with Playwright/Chromium missing (same as today). Must not skip because of missing `#task-log-tab-agent`.

Also run the markup suite:

```bash
pytest tests/test_web_server.py::test_homepage_exposes_agent_right_rail_chrome \
  tests/test_web_server.py::test_agent_dock_javascript_exposes_chrome_state_and_restore \
  tests/test_web_server.py::test_task_log_drawer_javascript_has_no_agent_tabs_or_abort_hook \
  tests/test_cli_no_agent.py -v
```

Expected: PASS. CLI still has no Agent command.

- [ ] **Step 4: Commit**

```bash
git add tests/test_web_agent_e2e.py
git commit -m "$(cat <<'EOF'
test(web): cover Agent right rail and log overlay

Lock toggle, restore-without-stream, and apply-without-rebind so the old dock tabs cannot regress.
EOF
)"
```

---

## Self-review

**Spec coverage**

| Spec | Task |
|------|------|
| 3.1 / 6.1 three-column chrome, rail after `main` | 1, 3 |
| 6.1 logs overlay; no `#task-log-dock`; overlay `right` offset | 2, 3, 4 |
| 6.2 no Agent modal on narrow screens | 3 |
| 6.3 build scan no yield; Agent stays | 2 |
| 6.4 no left-nav Agent; no `/agent` | 1 |
| 7.1 toggle/collapse ≠ stop; logs ≠ Agent | 2, 4, 6 |
| 7.2–7.3 explain/search `bindTask` + `setOpen(true)`; logs stay | 5, 6 |
| 7.4 apply + `new_task_id` opens overlay, no rebind | 5, 6 |
| 7.5 `pagehide` still abort+stop | 4 (existing listener) |
| 8 `asc.agent.chrome` restore without stream | 4, 6 |
| 9 file split + public API | 1–5 |
| 12 storage failure / restore 4xx / two width keys | 4 (`try/catch`, restore `!ok`) |
| 13.1 markup/JS string tests | 1–5 |
| 13.2 Playwright | 6 |
| 13.1–13.3 backend tests unchanged | no task (do not edit) |
| 14 CLI `--help` has no Agent | Task 6 rerun `test_cli_no_agent.py` |

**Placeholder scan:** no TBD/TODO; each code step includes the functions/markup to land.

**Type consistency:** `getState()` fields are `open`, `sessionId`, `boundTaskId` (booleans/strings). Storage JSON uses `agentOpen` not `open`. `setOpen(boolean)` vs `getState().open`. `restoreChrome` ≠ `bindTask`. Overlay `TaskLogDrawer.open(taskId)` has no `tab`. Width keys `asc.agentPanel.width` vs `asc.taskLogDrawer.width`.
