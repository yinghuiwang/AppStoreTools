# Dashboard Command Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the task-history-only homepage with the approved Command Workspace dashboard, fixed-baseline efficiency metrics, filters, and a right-side live log drawer that pauses auto-scroll when the user reads older logs.

**Architecture:** Keep dashboard aggregation in a pure Python module fed by task metadata from `TaskStore`; expose the same data through server-rendered initial context and a read-only JSON refresh endpoint. Keep logs on the existing sequenced SSE route, while a dashboard-only JavaScript controller owns drawer state, EventSource lifecycle, deduplication, and scroll-follow behavior.

**Tech Stack:** Python 3.9+, FastAPI, Jinja2, SQLite, pytest, HTMX/Tailwind-compatible HTML, browser-native JavaScript and EventSource.

---

## File Map

- Create `src/asc/web/dashboard.py`: fixed manual baselines, filtering, metric calculation, JSON-ready task summaries.
- Create `src/asc/web/static/dashboard.css`: Command Workspace layout, right drawer, responsive behavior, reduced-motion states.
- Create `src/asc/web/static/dashboard.js`: dashboard polling/filter refresh, log drawer SSE lifecycle, scroll-follow state.
- Modify `src/asc/web/tasks.py`: add a metadata-only recent task query that never loads task logs.
- Modify `src/asc/web/server.py`: mount static assets and provide initial dashboard context.
- Modify `src/asc/web/routes_api.py`: validate filters and expose `GET /api/dashboard/summary`.
- Replace `src/asc/web/templates/index.html`: render the dashboard, task list, quick actions, and right drawer hooks.
- Preserve `src/asc/web/templates/task_list.html` and `GET /api/tasks/recent` for compatibility; the new homepage no longer depends on them.
- Create `tests/test_web_dashboard.py`: pure aggregation tests.
- Modify `tests/test_web_tasks.py`: metadata-only query tests.
- Modify `tests/test_web_server.py`: API, initial markup, static asset, and SSE hook integration tests.

### Task 1: Add Metadata-Only Task Queries

**Files:**
- Modify: `src/asc/web/tasks.py:270`
- Test: `tests/test_web_tasks.py`

- [ ] **Step 1: Write the failing in-memory and SQLite tests**

Append:

```python
def test_list_recent_states_returns_newest_tasks_without_logs():
    store = TaskStore()
    first = store.create("metadata", profile="one")
    second = store.create("build", profile="two")
    store.append_log(second, "large log")

    states = store.list_recent_states(limit=2)

    assert [task["id"] for task in states] == [second, first]
    assert states[0]["logs"] == []
    assert states[0]["profile"] == "two"


def test_sqlite_list_recent_states_does_not_query_task_logs(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build")
    store.append_log(task_id, "line")

    states = store.list_recent_states(limit=10)

    assert states[0]["id"] == task_id
    assert states[0]["logs"] == []
```

- [ ] **Step 2: Run the tests and verify the missing method failure**

Run: `pytest tests/test_web_tasks.py -k list_recent_states -v`  
Expected: FAIL with `AttributeError: 'TaskStore' object has no attribute 'list_recent_states'`.

- [ ] **Step 3: Implement `list_recent_states`**

Add after `list_recent`:

```python
def list_recent_states(self, limit: int = 500) -> list[dict]:
    """Return newest task metadata without loading log history."""
    safe_limit = max(1, min(int(limit), 5000))
    with self._lock:
        if self._db_path is not None:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT r.*, o.position FROM task_order o
                    JOIN task_runs r ON r.id = o.task_id
                    ORDER BY o.position DESC LIMIT ?""",
                    (safe_limit,),
                ).fetchall()
            return [self._public_task(self._task_from_row(row, [])) for row in rows]

        self._refresh_db()
        states = []
        for task_id in reversed(self._order):
            task = self._tasks.get(task_id)
            if task is None:
                continue
            state = dict(task)
            state["logs"] = []
            states.append(self._public_task(state))
            if len(states) >= safe_limit:
                break
        return states
```

- [ ] **Step 4: Run focused task-store tests**

Run: `pytest tests/test_web_tasks.py -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/tasks.py tests/test_web_tasks.py
git commit -m "feat(web): query task metadata without logs"
```

### Task 2: Implement Dashboard Aggregation

**Files:**
- Create: `src/asc/web/dashboard.py`
- Create: `tests/test_web_dashboard.py`

- [ ] **Step 1: Write failing metric and filter tests**

Create `tests/test_web_dashboard.py`:

```python
from datetime import datetime

import pytest

from asc.web.dashboard import build_dashboard_summary


NOW = datetime.fromisoformat("2026-07-21T12:00:00")


def task(kind, status, seconds, *, profile="myapp", created="2026-07-20T10:00:00"):
    return {
        "id": f"{kind}-{status}-{seconds}",
        "kind": kind,
        "title": kind,
        "profile": profile,
        "status": status,
        "created_at": created,
        "completed_at": "2026-07-20T10:10:00",
        "updated_at": "2026-07-20T10:10:00",
        "duration_seconds": seconds,
        "duration_label": f"{seconds}s",
        "progress": {"pct": 50, "msg": "working"},
        "retry_path": "/retry",
    }


def test_summary_counts_only_successful_tasks_as_savings():
    result = build_dashboard_summary(
        [task("metadata", "done", 600), task("build", "error", 120)],
        days=30,
        now=NOW,
    )
    assert result["metrics"] == {
        "saved_seconds": 1200,
        "success_rate": 50.0,
        "failed_seconds": 120,
        "running_count": 0,
        "completed_count": 2,
    }


def test_summary_clamps_negative_savings_to_zero():
    result = build_dashboard_summary([task("urls", "done", 900)], days=30, now=NOW)
    assert result["metrics"]["saved_seconds"] == 0


def test_summary_returns_none_success_rate_without_terminal_tasks():
    result = build_dashboard_summary([task("build", "running", 30)], days=30, now=NOW)
    assert result["metrics"]["success_rate"] is None
    assert result["metrics"]["running_count"] == 1


def test_summary_filters_by_date_profile_kind_and_status():
    tasks = [
        task("metadata", "done", 60, profile="myapp"),
        task("build", "done", 60, profile="other"),
        task("metadata", "error", 60, profile="myapp"),
        task("metadata", "done", 60, profile="myapp", created="2026-01-01T00:00:00"),
    ]
    result = build_dashboard_summary(
        tasks,
        days=30,
        profile="myapp",
        kind="metadata",
        status="done",
        now=NOW,
    )
    assert [item["id"] for item in result["tasks"]] == ["metadata-done-60"]


@pytest.mark.parametrize("days", [7, 30, 90])
def test_summary_exposes_fixed_baselines(days):
    result = build_dashboard_summary([], days=days, now=NOW)
    assert result["baseline_minutes"]["metadata"] == 30
    assert result["range_days"] == days
```

- [ ] **Step 2: Run the tests and verify the module failure**

Run: `pytest tests/test_web_dashboard.py -v`  
Expected: collection FAIL with `ModuleNotFoundError: No module named 'asc.web.dashboard'`.

- [ ] **Step 3: Implement the pure aggregation module**

Create `src/asc/web/dashboard.py`:

```python
"""Pure dashboard filtering and efficiency metric calculation."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Optional


MANUAL_BASELINE_MINUTES = {
    "metadata": 30,
    "build": 45,
    "whats-new": 10,
    "iap": 25,
    "iap-review-screenshots": 20,
    "urls": 8,
    "update": 5,
}
TERMINAL_STATUSES = {"done", "error", "canceled"}
FAILED_STATUSES = {"error", "canceled"}


def _status_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _created_at(task: dict[str, Any]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(task.get("created_at", "")))
    except ValueError:
        return None


def build_dashboard_summary(
    tasks: Iterable[dict[str, Any]],
    *,
    days: int,
    profile: str = "",
    kind: str = "",
    status: str = "",
    now: Optional[datetime] = None,
    task_limit: int = 20,
) -> dict[str, Any]:
    current = now or datetime.now()
    cutoff = current - timedelta(days=days)
    filtered = []
    for source in tasks:
        task = dict(source)
        task_status = _status_value(task.get("status"))
        created = _created_at(task)
        if created is None or created < cutoff:
            continue
        if profile and task.get("profile") != profile:
            continue
        if kind and task.get("kind") != kind:
            continue
        if status and task_status != status:
            continue
        task["status"] = task_status
        filtered.append(task)

    saved_seconds = 0
    failed_seconds = 0
    terminal_count = 0
    success_count = 0
    running_count = 0
    for task in filtered:
        task_status = task["status"]
        duration = max(0, int(task.get("duration_seconds", 0)))
        if task_status in {"pending", "running"}:
            running_count += 1
        if task_status in TERMINAL_STATUSES:
            terminal_count += 1
        if task_status == "done":
            success_count += 1
            baseline = MANUAL_BASELINE_MINUTES.get(task.get("kind"), 0) * 60
            saved_seconds += max(baseline - duration, 0)
        elif task_status in FAILED_STATUSES:
            failed_seconds += duration

    return {
        "metrics": {
            "saved_seconds": saved_seconds,
            "success_rate": round(success_count / terminal_count * 100, 1) if terminal_count else None,
            "failed_seconds": failed_seconds,
            "running_count": running_count,
            "completed_count": terminal_count,
        },
        "tasks": filtered[: max(1, min(task_limit, 100))],
        "baseline_minutes": dict(MANUAL_BASELINE_MINUTES),
        "range_days": days,
    }
```

- [ ] **Step 4: Run aggregation tests**

Run: `pytest tests/test_web_dashboard.py -v`  
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/dashboard.py tests/test_web_dashboard.py
git commit -m "feat(web): calculate dashboard efficiency metrics"
```

### Task 3: Expose Dashboard Data Through FastAPI

**Files:**
- Create: `src/asc/web/static/.gitkeep`
- Modify: `src/asc/web/routes_api.py:1002`
- Modify: `src/asc/web/server.py:1-75`
- Test: `tests/test_web_server.py`

- [ ] **Step 1: Write failing API and initial-context tests**

Append to `tests/test_web_server.py`:

```python
def test_dashboard_summary_api_filters_tasks(client, monkeypatch):
    from asc.web import routes_api

    monkeypatch.setattr(routes_api._task_store, "list_recent_states", lambda limit=500: [{
        "id": "one", "kind": "metadata", "title": "元数据上传", "profile": "myapp",
        "status": "done", "created_at": "2026-07-20T10:00:00",
        "duration_seconds": 60, "duration_label": "1m", "progress": {"pct": 100, "msg": ""},
        "retry_path": "/metadata",
    }])

    response = client.get("/api/dashboard/summary?range=30d&profile=myapp&kind=metadata&status=done")

    assert response.status_code == 200
    assert response.json()["tasks"][0]["id"] == "one"
    assert response.json()["metrics"]["saved_seconds"] == 1740


@pytest.mark.parametrize("query", ["range=1d", "range=30d&status=unknown", "range=30d&kind=unknown"])
def test_dashboard_summary_rejects_invalid_filters(client, query):
    response = client.get(f"/api/dashboard/summary?{query}")
    assert response.status_code == 400


def test_homepage_renders_initial_dashboard_context(client):
    response = client.get("/", cookies={"asc_profile": "myapp"})
    assert response.status_code == 200
    assert 'id="dashboard-root"' in response.text
    assert 'data-current-profile="myapp"' in response.text
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `pytest tests/test_web_server.py -k dashboard -v`  
Expected: FAIL because the endpoint and new root markup do not exist.

- [ ] **Step 3: Add the JSON endpoint with explicit validation**

Add imports and route in `routes_api.py`:

```python
from fastapi import HTTPException
from asc.web.dashboard import MANUAL_BASELINE_MINUTES, build_dashboard_summary


@router.get("/dashboard/summary")
async def dashboard_summary(
    time_range: str = Query("30d", alias="range"),
    profile: str = Query(""),
    kind: str = Query(""),
    status: str = Query(""),
):
    ranges = {"7d": 7, "30d": 30, "90d": 90}
    allowed_statuses = {"", "pending", "running", "done", "error", "canceled"}
    if time_range not in ranges:
        raise HTTPException(status_code=400, detail="Invalid dashboard range")
    if kind and kind not in MANUAL_BASELINE_MINUTES:
        raise HTTPException(status_code=400, detail="Invalid task kind")
    if status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Invalid task status")
    return build_dashboard_summary(
        _task_store.list_recent_states(limit=500),
        days=ranges[time_range],
        profile=profile,
        kind=kind,
        status=status,
    )
```

- [ ] **Step 4: Create the static directory, mount assets, and populate initial context**

Create the directory marker:

```text
src/asc/web/static/.gitkeep
```

In `server.py`, import and mount static files:

```python
from fastapi.staticfiles import StaticFiles
from asc.web.dashboard import build_dashboard_summary

_STATIC_DIR = Path(__file__).parent / "static"

# inside create_app(), after FastAPI construction
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
```

Update `index`:

```python
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    ctx = _get_profile_context(request)
    tasks = task_store.list_recent_states(limit=500)
    ctx["dashboard"] = build_dashboard_summary(
        tasks,
        days=30,
        profile=ctx["current_profile"],
    )
    return _render(request, "index.html", ctx)
```

- [ ] **Step 5: Add a temporary dashboard root to `index.html` and run tests**

Replace the opening wrapper with:

```html
<div id="dashboard-root" data-current-profile="{{ current_profile }}">
  <h1>仪表盘</h1>
</div>
```

Run: `pytest tests/test_web_server.py -k dashboard -v`  
Expected: all dashboard-focused tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/asc/web/routes_api.py src/asc/web/server.py src/asc/web/static/.gitkeep src/asc/web/templates/index.html tests/test_web_server.py
git commit -m "feat(web): expose dashboard summary data"
```

### Task 4: Build the Command Workspace Layout

**Files:**
- Create: `src/asc/web/static/dashboard.css`
- Replace: `src/asc/web/templates/index.html`
- Test: `tests/test_web_server.py`

- [ ] **Step 1: Add failing structural markup tests**

Append:

```python
def test_homepage_contains_command_workspace_regions(client):
    response = client.get("/")
    for marker in (
        'id="dashboard-summary"',
        'id="dashboard-task-list"',
        'id="dashboard-log-drawer"',
        'id="dashboard-log-output"',
        'data-dashboard-filter="range"',
        'data-quick-action="/metadata"',
    ):
        assert marker in response.text


def test_dashboard_styles_are_served(client):
    response = client.get("/static/dashboard.css")
    assert response.status_code == 200
    assert ".dashboard-shell" in response.text
    assert ".dashboard-log-drawer" in response.text
```

- [ ] **Step 2: Run structural tests and verify they fail**

Run: `pytest tests/test_web_server.py -k 'command_workspace or dashboard_styles' -v`  
Expected: FAIL because the production layout and stylesheet are missing.

- [ ] **Step 3: Create the dashboard stylesheet**

Create `src/asc/web/static/dashboard.css` with these complete layout contracts:

```css
.dashboard-shell { display:grid; grid-template-columns:minmax(0,1fr) 0; min-height:100%; transition:grid-template-columns .2s ease; }
.dashboard-shell.log-open { grid-template-columns:minmax(0,1fr) 390px; }
.dashboard-workspace { min-width:0; padding:24px; overflow-y:auto; }
.dashboard-toolbar { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:16px; }
.dashboard-filters { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.dashboard-summary { display:grid; grid-template-columns:1.25fr repeat(3,minmax(120px,.75fr)); gap:12px; margin-bottom:16px; }
.dashboard-stat { min-height:112px; padding:16px; border:1px solid var(--border-subtle); border-radius:8px; background:var(--bg-surface); }
.dashboard-stat-value { display:block; margin-top:8px; color:var(--text-primary); font-size:26px; font-variant-numeric:tabular-nums; }
.dashboard-stat-primary .dashboard-stat-value { color:var(--accent); font-family:'Instrument Serif',serif; font-size:40px; }
.dashboard-actions { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px; }
.dashboard-running { margin-bottom:16px; border:1px solid rgba(96,165,250,.3); border-radius:8px; background:rgba(96,165,250,.06); }
.dashboard-table { width:100%; border-collapse:collapse; table-layout:fixed; }
.dashboard-table th,.dashboard-table td { padding:11px 12px; border-bottom:1px solid var(--border-subtle); text-align:left; font-size:12px; }
.dashboard-table th { color:var(--text-muted); font-size:10px; font-weight:500; letter-spacing:.08em; text-transform:uppercase; }
.dashboard-log-drawer { width:390px; min-width:0; display:flex; flex-direction:column; overflow:hidden; border-left:1px solid var(--border-default); background:#0c0c10; box-shadow:-12px 0 32px rgba(0,0,0,.24); }
.dashboard-log-drawer[hidden] { display:none; }
.dashboard-log-output { flex:1; overflow:auto; padding:14px; background:#09090c; color:var(--text-secondary); font:12px/1.7 'Fira Code',monospace; white-space:pre-wrap; overflow-wrap:anywhere; }
.dashboard-log-follow { display:flex; align-items:center; justify-content:space-between; margin:10px 12px 12px; padding:9px 10px; border:1px solid var(--border-subtle); border-radius:7px; background:var(--bg-surface); }
.dashboard-log-follow [data-return-latest] { display:none; }
.dashboard-log-drawer.follow-paused [data-return-latest] { display:inline-flex; }
@media (max-width:900px) {
  .dashboard-summary { grid-template-columns:1fr 1fr; }
  .dashboard-shell.log-open { grid-template-columns:minmax(0,1fr); }
  .dashboard-log-drawer { position:fixed; z-index:50; inset:0 0 0 auto; width:min(100vw,420px); }
}
@media (prefers-reduced-motion:reduce) { .dashboard-shell { transition:none; } }
```

- [ ] **Step 4: Replace `index.html` with the approved regions**

The template must:

```html
{% extends "base.html" %}
{% block content %}
<link rel="stylesheet" href="/static/dashboard.css">
<div id="dashboard-root" class="dashboard-shell" data-current-profile="{{ current_profile }}">
  <section class="dashboard-workspace">
    <header class="dashboard-toolbar">
      <div><h1 class="text-xl font-semibold">工作台</h1><p class="text-xs text-obsidian-400">{{ current_profile or "未配置" }}</p></div>
      <div class="dashboard-filters">
        <select class="field-select" data-dashboard-filter="range"><option value="7d">7 天</option><option value="30d" selected>30 天</option><option value="90d">90 天</option></select>
        <select class="field-select" data-dashboard-filter="profile"><option value="">全部 Profile</option>{% for p in profiles %}<option value="{{ p }}" {% if p == current_profile %}selected{% endif %}>{{ p }}</option>{% endfor %}</select>
        <select class="field-select" data-dashboard-filter="status"><option value="">全部状态</option><option value="running">运行中</option><option value="done">成功</option><option value="error">失败</option><option value="canceled">已取消</option></select>
      </div>
    </header>
    <div id="dashboard-summary" class="dashboard-summary" aria-live="polite"></div>
    <nav class="dashboard-actions" aria-label="常用操作">
      <a class="btn-primary" href="/metadata" data-quick-action="/metadata">上传全部</a>
      <a class="btn-ghost" href="/metadata">更新元数据</a><a class="btn-ghost" href="/metadata">上传截图</a>
      <a class="btn-ghost" href="/build" data-quick-action="/build">构建并发布</a>
    </nav>
    <section id="dashboard-running" class="dashboard-running" aria-label="运行中任务"></section>
    <section class="card"><table class="dashboard-table"><thead><tr><th>任务</th><th>Profile</th><th>状态</th><th>用时</th><th>操作</th></tr></thead><tbody id="dashboard-task-list"></tbody></table></section>
  </section>
  <aside id="dashboard-log-drawer" class="dashboard-log-drawer" hidden aria-label="任务日志">
    <header class="card-header flex justify-between"><div><strong data-log-title></strong><div class="text-xs text-obsidian-400" data-log-connection></div></div><button class="btn-ghost" data-log-close aria-label="关闭日志">×</button></header>
    <div class="flex gap-2 p-3 border-b border-obsidian-700"><button class="btn-ghost" data-log-copy>复制</button><button class="btn-ghost" data-log-errors>仅错误</button></div>
    <div id="dashboard-log-output" class="dashboard-log-output" tabindex="0"></div>
    <footer class="dashboard-log-follow"><span data-log-follow-status>正在跟随最新日志</span><button class="btn-primary" data-return-latest>回到最新</button></footer>
  </aside>
</div>
<script>window.__ASC_DASHBOARD__ = {{ dashboard | tojson }};</script>
<script src="/static/dashboard.js" defer></script>
{% endblock %}
```

Render the initial summary and rows server-side or call the same renderer from `window.__ASC_DASHBOARD__`; do not show an empty flash. Use text labels and status badges already defined in `base.html`.

- [ ] **Step 5: Run structural tests**

Run: `pytest tests/test_web_server.py -k 'homepage or dashboard_styles or command_workspace' -v`  
Expected: all selected tests PASS. Update the old `openTaskLogs` assertion test to assert `/static/dashboard.js` instead, because the homepage no longer uses inline log panels.

- [ ] **Step 6: Commit**

```bash
git add src/asc/web/static/dashboard.css src/asc/web/templates/index.html tests/test_web_server.py
git commit -m "feat(web): build command workspace dashboard"
```

### Task 5: Implement Dashboard Refresh and Right Log Drawer

**Files:**
- Create: `src/asc/web/static/dashboard.js`
- Modify: `tests/test_web_server.py`

- [ ] **Step 1: Add failing asset contract tests**

Append:

```python
def test_dashboard_script_contains_log_follow_contract(client):
    response = client.get("/static/dashboard.js")
    assert response.status_code == 200
    for marker in ("EventSource", "lastSeq", "followPaused", "newLogCount", "returnToLatest", "selectionchange"):
        assert marker in response.text
```

- [ ] **Step 2: Run the test and verify the missing asset failure**

Run: `pytest tests/test_web_server.py::test_dashboard_script_contains_log_follow_contract -v`  
Expected: FAIL with HTTP 404.

- [ ] **Step 3: Create the dashboard controller**

Create `src/asc/web/static/dashboard.js` as an IIFE with this state and behavior:

```javascript
(() => {
  const root = document.getElementById('dashboard-root');
  if (!root) return;
  const drawer = document.getElementById('dashboard-log-drawer');
  const output = document.getElementById('dashboard-log-output');
  const statusText = drawer.querySelector('[data-log-follow-status]');
  let source = null;
  let activeTaskId = null;
  let lastSeq = 0;
  let followPaused = false;
  let newLogCount = 0;

  const nearBottom = () => output.scrollHeight - output.scrollTop - output.clientHeight <= 8;
  const returnToLatest = () => {
    followPaused = false; newLogCount = 0; drawer.classList.remove('follow-paused');
    output.scrollTop = output.scrollHeight; statusText.textContent = '正在跟随最新日志';
  };
  const pauseFollow = () => {
    if (nearBottom()) return;
    followPaused = true; drawer.classList.add('follow-paused');
    statusText.textContent = newLogCount ? `有 ${newLogCount} 条新日志` : '自动跟随已暂停';
  };
  const appendLog = (message) => {
    const line = document.createElement('div'); line.textContent = message; output.appendChild(line);
    if (followPaused) { newLogCount += 1; statusText.textContent = `有 ${newLogCount} 条新日志`; }
    else { output.scrollTop = output.scrollHeight; }
  };
  const closeLogs = () => {
    if (source) source.close(); source = null; activeTaskId = null;
    drawer.hidden = true; root.classList.remove('log-open');
  };
  const openLogs = (taskId, title) => {
    if (source) source.close();
    activeTaskId = taskId; lastSeq = 0; output.replaceChildren(); returnToLatest();
    drawer.hidden = false; root.classList.add('log-open');
    drawer.querySelector('[data-log-title]').textContent = title;
    source = new EventSource(`/api/task/${encodeURIComponent(taskId)}/stream?after=${lastSeq}`);
    source.addEventListener('log', (event) => {
      const seq = Number(event.lastEventId || 0); if (seq && seq <= lastSeq) return;
      lastSeq = Math.max(lastSeq, seq); appendLog(event.data);
    });
    source.addEventListener('progress', refreshDashboard);
    ['done', 'canceled', 'error_event'].forEach(name => source.addEventListener(name, () => {
      drawer.querySelector('[data-log-connection]').textContent = '任务已结束'; source.close(); refreshDashboard();
    }));
    source.onerror = () => { drawer.querySelector('[data-log-connection]').textContent = '连接中断，正在重连'; };
  };
  async function refreshDashboard() {
    const params = new URLSearchParams();
    root.querySelectorAll('[data-dashboard-filter]').forEach(el => params.set(el.dataset.dashboardFilter, el.value));
    params.set('profile', root.querySelector('[data-dashboard-filter="profile"]').value);
    const response = await fetch(`/api/dashboard/summary?${params}`);
    if (!response.ok) return;
    renderDashboard(await response.json());
  }
  const formatDuration = seconds => {
    const value = Math.max(0, Number(seconds || 0));
    if (value < 60) return `${value}s`;
    const minutes = Math.floor(value / 60);
    if (minutes < 60) return `${minutes}m`;
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  };
  const createStat = (label, value, primary = false) => {
    const card = document.createElement('article');
    card.className = `dashboard-stat${primary ? ' dashboard-stat-primary' : ''}`;
    const caption = document.createElement('span'); caption.textContent = label;
    const number = document.createElement('strong'); number.className = 'dashboard-stat-value'; number.textContent = value;
    card.append(caption, number); return card;
  };
  function renderDashboard(data) {
    const metrics = data.metrics;
    const summary = document.getElementById('dashboard-summary');
    summary.replaceChildren(
      createStat('预计节省时间', formatDuration(metrics.saved_seconds), true),
      createStat('成功率', metrics.success_rate === null ? '--' : `${metrics.success_rate}%`),
      createStat('失败任务投入', formatDuration(metrics.failed_seconds)),
      createStat('运行中', String(metrics.running_count)),
    );
    const running = document.getElementById('dashboard-running');
    const runningTasks = data.tasks.filter(task => ['pending', 'running'].includes(task.status));
    running.replaceChildren();
    running.hidden = runningTasks.length === 0;
    runningTasks.forEach(task => {
      const row = document.createElement('button'); row.type = 'button'; row.className = 'w-full p-3 text-left';
      row.textContent = `${task.title} · ${task.progress.pct}% · ${task.progress.msg || '运行中'}`;
      row.addEventListener('click', () => openLogs(task.id, task.title)); running.appendChild(row);
    });
    const body = document.getElementById('dashboard-task-list'); body.replaceChildren();
    data.tasks.forEach(task => {
      const row = document.createElement('tr');
      [task.title, task.profile || '--', task.status, task.duration_label].forEach(value => {
        const cell = document.createElement('td'); cell.textContent = value; row.appendChild(cell);
      });
      const actions = document.createElement('td');
      const logButton = document.createElement('button'); logButton.type = 'button'; logButton.className = 'btn-ghost'; logButton.textContent = '日志';
      logButton.addEventListener('click', () => openLogs(task.id, task.title)); actions.appendChild(logButton);
      if (task.status === 'error' && task.retry_path) {
        const retry = document.createElement('a'); retry.className = 'ml-2 text-amber-500'; retry.href = task.retry_path; retry.textContent = '重试'; actions.appendChild(retry);
      }
      row.appendChild(actions); body.appendChild(row);
    });
  }
  output.addEventListener('scroll', () => nearBottom() ? returnToLatest() : pauseFollow(), {passive:true});
  document.addEventListener('selectionchange', () => {
    const selection = document.getSelection();
    if (selection && !selection.isCollapsed && output.contains(selection.anchorNode)) pauseFollow();
  });
  drawer.querySelector('[data-return-latest]').addEventListener('click', returnToLatest);
  drawer.querySelector('[data-log-close]').addEventListener('click', closeLogs);
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !drawer.hidden) closeLogs(); });
  root.querySelectorAll('[data-dashboard-filter]').forEach(el => el.addEventListener('change', refreshDashboard));
  renderDashboard(window.__ASC_DASHBOARD__);
  window.setInterval(() => { if (document.visibilityState === 'visible') refreshDashboard(); }, 3000);
})();
```

Keep all task and log values on `textContent`; do not switch the renderer to `innerHTML`.

- [ ] **Step 4: Run API, asset, and SSE tests**

Run: `pytest tests/test_web_server.py -k 'dashboard or task_stream' -v`  
Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/static/dashboard.js tests/test_web_server.py
git commit -m "feat(web): add right-side live log drawer"
```

### Task 6: Verify Behavior and Polish Accessibility

**Files:**
- Modify as needed: `src/asc/web/templates/index.html`
- Modify as needed: `src/asc/web/static/dashboard.css`
- Modify as needed: `src/asc/web/static/dashboard.js`
- Test: `tests/test_web_dashboard.py`, `tests/test_web_tasks.py`, `tests/test_web_server.py`

- [ ] **Step 1: Run focused tests**

Run: `pytest tests/test_web_dashboard.py tests/test_web_tasks.py tests/test_web_server.py -v`  
Expected: all tests PASS.

- [ ] **Step 2: Run the full suite**

Run: `pytest`  
Expected: all tests PASS with no new warnings attributable to the dashboard.

- [ ] **Step 3: Start the local Web UI**

Run: `asc web --host 127.0.0.1 --port 8765`  
Expected: server reports `http://127.0.0.1:8765`; if occupied, use port 8766.

- [ ] **Step 4: Perform browser verification at desktop and mobile widths**

Verify at 1440x900 and 390x844:

1. Initial summary has no empty flash and matches current profile/30-day filters.
2. Filters update summary and history without reloading the page.
3. Opening logs expands the right drawer and keeps the selected task visible.
4. New logs follow the bottom while untouched.
5. Scrolling upward or selecting log text pauses follow and increments the new-log counter.
6. “回到最新” scrolls to the bottom, clears the counter, and resumes follow.
7. Switching tasks closes the previous EventSource and starts at sequence 0 for the selected task.
8. Closing or pressing Escape restores workspace width and preserves page/filter position.
9. On mobile, the drawer covers the workspace from the right and has a visible close control.
10. Keyboard focus is visible; reduced-motion mode does not animate layout changes.

- [ ] **Step 5: Inspect changed files and commit final polish**

Run: `git diff --check && git status --short`  
Expected: no whitespace errors; only intended dashboard files remain modified.

```bash
git add src/asc/web/templates/index.html src/asc/web/static/dashboard.css src/asc/web/static/dashboard.js tests/test_web_dashboard.py tests/test_web_tasks.py tests/test_web_server.py
git commit -m "test(web): verify dashboard workspace interactions"
```
