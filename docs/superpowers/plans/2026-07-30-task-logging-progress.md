# Task Logging & Progress Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify CLI and Web task logging/progress behind `TaskReporter` so every long-running task reports accurate phase + fine-grained progress with switchable verbosity.

**Architecture:** Add `TaskReporter` with `CliSink` / `TaskStoreSink`. Commands call `set_phases` / `phase` / `progress` / `log` / `debug` instead of `print("[PROGRESS:…]")`. Web tasks inject `TaskStoreSink` and stop relying on stdout scraping as the primary path. Extend TaskStore/SSE progress with phase fields; move What's New LLM translation into background tasks.

**Tech Stack:** Python 3.9+, Typer CLI, FastAPI SSE, SQLite TaskStore, pytest + unittest.mock, vanilla JS (`TaskLogDrawer`).

**Spec:** `docs/superpowers/specs/2026-07-30-task-logging-progress-design.md`

## Global Constraints

- Keep public CLI command names and primary option semantics unchanged.
- Do not introduce WebSocket, `rich`, or a full Python `logging` user-facing stack.
- Do not redesign the task-log drawer chrome; only extend progress payload consumption and optional verbose fold.
- `pct` must be monotonic non-decreasing within a task run; skipped work still advances `current`.
- No real ASC / LLM network calls in tests; mock APIs and translators.
- `docs/superpowers/` is gitignored — use `git add -f` when committing plans/specs under that tree.

## File map

| Path | Responsibility |
|------|----------------|
| Create `src/asc/reporting.py` | `TaskReporter`, `CliSink`, `TaskStoreSink`, `make_cli_reporter`, `make_web_reporter` |
| Create `tests/test_reporting.py` | Reporter pct mapping, verbose filter, sink fan-out |
| Modify `src/asc/web/tasks.py` | Persist phase fields; extend `set_progress` |
| Modify `tests/test_web_tasks.py` | Phase persistence / schema migration |
| Create `src/asc/web/task_runner.py` | Shared background-task runner that injects reporter |
| Modify `src/asc/web/routes_api.py` | Use task_runner; whats-new translate tasks; SSE timeout |
| Modify `src/asc/web/static/task-log-drawer.js` | Pass full progress object (incl. phase) to `onProgress` |
| Modify feature templates / dashboard JS | build phase from `phase_index` |
| Modify command modules under `src/asc/commands/` | Reporter-based progress for all task kinds |
| Modify `src/asc/progress.py` | Spinner/line callbacks into reporter |
| Modify related tests under `tests/` | Assert reporter calls; no leftover `[PROGRESS:` |

---

### Task 1: `TaskReporter` core + sinks

**Files:**
- Create: `src/asc/reporting.py`
- Create: `tests/test_reporting.py`

**Interfaces:**
- Produces:
  - `class TaskReporter`
  - `set_phases(self, phases: list[tuple[str, int, str]]) -> None` — `(phase_id, weight_pct, label)`
  - `phase(self, phase_id: str) -> None`
  - `progress(self, current: int, total: int, msg: str | None = None) -> None`
  - `log(self, message: str, *, level: str = "info") -> None`
  - `debug(self, message: str) -> None`
  - `done(self, summary: str | None = None) -> None`
  - `fail(self, message: str, *, detail: str | None = None) -> None`
  - `class CliSink`, `class TaskStoreSink`
  - `make_cli_reporter(*, verbose: bool = False) -> TaskReporter`
  - `make_web_reporter(task_store, task_id: str, *, verbose: bool = False) -> TaskReporter`
- Sink protocol:

```python
class ProgressSink(Protocol):
    def on_log(self, message: str, *, level: str) -> None: ...
    def on_progress(
        self, *, pct: int, msg: str, phase: str, phase_label: str,
        phase_index: int, phase_total: int,
    ) -> None: ...
```

- [ ] **Step 1: Write failing tests**

Create `tests/test_reporting.py`:

```python
from asc.reporting import TaskReporter, CliSink


class RecordingSink:
    def __init__(self):
        self.logs = []
        self.progress_events = []

    def on_log(self, message, *, level="info"):
        self.logs.append((level, message))

    def on_progress(self, *, pct, msg, phase, phase_label, phase_index, phase_total):
        self.progress_events.append({
            "pct": pct,
            "msg": msg,
            "phase": phase,
            "phase_label": phase_label,
            "phase_index": phase_index,
            "phase_total": phase_total,
        })


def test_phase_and_progress_map_to_global_pct():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.set_phases([("check", 5, "校验"), ("locales", 95, "上传")])
    r.phase("check")
    r.progress(1, 1, msg="ok")
    assert sink.progress_events[-1]["pct"] == 5
    r.phase("locales")
    r.progress(1, 2, msg="en-US")
    assert sink.progress_events[-1]["pct"] == 5 + int(0.5 * 95)
    assert sink.progress_events[-1]["phase"] == "locales"
    assert sink.progress_events[-1]["phase_index"] == 2
    assert sink.progress_events[-1]["phase_total"] == 2


def test_pct_is_monotonic_when_current_regresses():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.set_phases([("upload", 100, "上传")])
    r.phase("upload")
    r.progress(2, 4)
    mid = sink.progress_events[-1]["pct"]
    r.progress(1, 4)
    assert sink.progress_events[-1]["pct"] >= mid


def test_debug_hidden_unless_verbose():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.log("visible")
    r.debug("hidden")
    assert ("info", "visible") in sink.logs
    assert all(msg != "hidden" for _, msg in sink.logs)

    sink2 = RecordingSink()
    r2 = TaskReporter(sinks=[sink2], verbose=True)
    r2.debug("shown")
    assert ("debug", "shown") in sink2.logs


def test_cli_sink_writes_to_stdout(capsys):
    r = TaskReporter(sinks=[CliSink()], verbose=False)
    r.set_phases([("upload", 100, "上传")])
    r.phase("upload")
    r.progress(1, 2, msg="a")
    r.log("done item")
    out = capsys.readouterr().out
    assert "done item" in out
    assert "50" in out or "1/2" in out or "上传" in out or "a" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reporting.py -v`

Expected: FAIL with `ModuleNotFoundError: asc.reporting`

- [ ] **Step 3: Implement minimal `src/asc/reporting.py`**

Behavior:
- Track phases, current phase index, `_pct` starting at 0.
- `set_phases`: store `(id, weight, label)`; if weights do not sum to 100, normalize by total weight.
- `phase(id)`: select phase; emit progress at phase start (`current` effective 0); `phase_index` is 1-based.
- `progress(current, total, msg)`: clamp; `candidate = phase_start + (current/total) * weight`; `_pct = max(_pct, int(candidate))`; fan-out.
- `log` / `debug`: fan-out; `debug` skipped when `not verbose`.
- `done`: force `_pct = 100`; optional summary log.
- `fail`: log message at error; log `detail` when provided (always on fail path as second line, or when verbose — implement: always append detail when non-empty).
- `CliSink`: print `[pct%] label: msg` on progress; print message on log.
- `TaskStoreSink`: call `store.append_log` and extended `set_progress` (Task 2 signature). Land Task 2 before using web sink in production paths.

```python
def make_cli_reporter(*, verbose: bool = False) -> TaskReporter:
    return TaskReporter(sinks=[CliSink()], verbose=verbose)


def make_web_reporter(task_store, task_id: str, *, verbose: bool = False) -> TaskReporter:
    return TaskReporter(sinks=[TaskStoreSink(task_store, task_id)], verbose=verbose)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reporting.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/reporting.py tests/test_reporting.py
git commit -m "feat(reporting): add TaskReporter with CLI and store sinks"
```

---

### Task 2: TaskStore phase fields + schema migration

**Files:**
- Modify: `src/asc/web/tasks.py`
- Modify: `tests/test_web_tasks.py`

**Interfaces:**
- Produces: `set_progress(task_id, pct, msg, *, phase="", phase_label="", phase_index=0, phase_total=0)`
- Public `progress` dict always includes `pct`, `msg`, `phase`, `phase_label`, `phase_index`, `phase_total`
- SQLite columns: `progress_phase`, `progress_phase_label`, `phase_index`, `phase_total` with ALTER migration for old DBs

- [ ] **Step 1: Write failing tests**

Append to `tests/test_web_tasks.py`:

```python
def test_set_progress_persists_phase_fields(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata", profile="demo")
    store.set_progress(
        task_id, 52, "en-US",
        phase="locales", phase_label="上传本地化",
        phase_index=2, phase_total=2,
    )
    task = store.get(task_id)
    assert task["progress"]["pct"] == 52
    assert task["progress"]["phase"] == "locales"
    assert task["progress"]["phase_label"] == "上传本地化"
    assert task["progress"]["phase_index"] == 2
    assert task["progress"]["phase_total"] == 2
    restored = TaskStore(tmp_path / "tasks.db")
    assert restored.get(task_id)["progress"]["phase"] == "locales"


def test_legacy_progress_defaults_phase_fields(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("build", profile="demo")
    store.set_progress(task_id, 10, "old")
    task = store.get(task_id)
    assert task["progress"]["phase"] == ""
    assert task["progress"]["phase_index"] == 0
    assert task["progress"]["phase_total"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_tasks.py::test_set_progress_persists_phase_fields tests/test_web_tasks.py::test_legacy_progress_defaults_phase_fields -v`

Expected: FAIL (unexpected keyword / missing keys)

- [ ] **Step 3: Implement**

1. Add columns via `_init_db` migration (`ALTER TABLE` if missing).
2. Extend `set_progress` with optional kwargs; update CREATE TABLE for fresh DBs.
3. Update `_task_from_row` and in-memory branch so progress always has six keys.
4. Keep `(task_id, pct, msg)` callers working.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_web_tasks.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/tasks.py tests/test_web_tasks.py
git commit -m "feat(web): persist task progress phase fields"
```

---

### Task 3: Shared web task runner + SSE lifetime

**Files:**
- Create: `src/asc/web/task_runner.py`
- Create: `tests/test_web_task_runner.py`
- Modify: `src/asc/web/routes_api.py` (SSE loop)

**Interfaces:**
- Produces:

```python
SSE_ABSOLUTE_TIMEOUT_SEC = 7200

def start_background_task(
    store: TaskStore,
    *,
    kind: str,
    profile: str,
    verbose: bool,
    run: Callable[[TaskReporter, Event], Any],
) -> str:
    ...
```

- `run(reporter, cancel_event)` body uses reporter only (no PROGRESS prints).
- Success: if return is `dict`, `store.set_result`; status DONE.
- `ProcessCanceled` → CANCELED; other Exception → `reporter.fail` + ERROR.
- SSE: poll while status not terminal AND elapsed < 7200s; keep heartbeats.

- [ ] **Step 1: Write failing test**

```python
# tests/test_web_task_runner.py
import time
from threading import Event

from asc.web.task_runner import start_background_task, SSE_ABSOLUTE_TIMEOUT_SEC
from asc.web.tasks import TaskStore, TaskStatus


def test_sse_absolute_timeout_constant():
    assert SSE_ABSOLUTE_TIMEOUT_SEC == 7200


def test_start_background_task_reports_progress(tmp_path):
    store = TaskStore(tmp_path / "t.db")

    def run(reporter, cancel_event: Event):
        reporter.set_phases([("upload", 100, "上传")])
        reporter.phase("upload")
        reporter.progress(1, 1, msg="done")
        reporter.log("finished")
        return {"success": True}

    task_id = start_background_task(
        store, kind="urls", profile="demo", verbose=False, run=run
    )
    for _ in range(100):
        task = store.get(task_id)
        if task["status"] in {TaskStatus.DONE, TaskStatus.ERROR, TaskStatus.CANCELED}:
            break
        time.sleep(0.05)
    task = store.get(task_id)
    assert task["status"] == TaskStatus.DONE
    assert task["progress"]["pct"] == 100
    assert any("finished" in line for line in task["logs"])
```

- [ ] **Step 2: Run — expect fail**

Run: `pytest tests/test_web_task_runner.py -v`

- [ ] **Step 3: Implement runner; update SSE in `routes_api.py`**

Replace `max_polls = 1500` logic with terminal-status + absolute timeout. Do not migrate all command endpoints yet (Tasks 5–10); this task only lands infrastructure.

- [ ] **Step 4: Tests pass**

Run: `pytest tests/test_web_task_runner.py tests/test_web_tasks.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/task_runner.py tests/test_web_task_runner.py src/asc/web/routes_api.py
git commit -m "feat(web): add reporter-based task runner and SSE lifetime fix"
```

---

### Task 4: Frontend progress payload (`phase_index`)

**Files:**
- Modify: `src/asc/web/static/task-log-drawer.js`
- Modify: `src/asc/web/static/dashboard.js`
- Modify: `src/asc/web/templates/build.html` (remove log-keyword phase heuristics)
- Modify: other feature templates that use `onProgress`
- Modify: `tests/test_web_server.py`

**Interfaces:**
- `TaskLogDrawer.open(..., { onProgress(progress) })` where `progress` is the full SSE object.
- Build page: `d.phase = Number(progress.phase_index) || d.phase`

- [ ] **Step 1: Failing contract test**

```python
def test_task_log_drawer_forwards_phase_fields(client):
    body = client.get("/static/task-log-drawer.js").text
    assert "onProgress" in body
    assert "phase_index" in body
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement JS + template updates**

Parse SSE progress JSON and pass object through. Update build `onProgress` / `onLog` so phase no longer depends on `line.includes('归档')`.

- [ ] **Step 4: Run**

Run: `pytest tests/test_web_server.py::test_task_log_drawer_forwards_phase_fields -v`

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/static/task-log-drawer.js src/asc/web/static/dashboard.js src/asc/web/templates/build.html src/asc/web/templates/*.html tests/test_web_server.py
git commit -m "feat(web): drive UI progress from structured phase payload"
```

---

### Task 5: Migrate metadata

**Files:**
- Modify: `src/asc/commands/metadata.py`
- Modify: metadata task start in `src/asc/web/routes_api.py`
- Modify/create tests under `tests/` for reporter usage

**Interfaces:**
- `_upload_metadata_core(..., reporter: TaskReporter | None = None)`
- Default: `reporter = make_cli_reporter(verbose=verbose)` when None
- Phases: `check` 5, `locales` 95
- Delete `print("[PROGRESS:...")`

- [ ] **Step 1: Failing test** — core invokes reporter progress per locale; source has no `[PROGRESS:` for metadata path after change (assert via mock RecordingSink)

- [ ] **Step 2: Implement core + CLI verbose option if missing + web `start_background_task`**

- [ ] **Step 3: `pytest` targeted**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(metadata): report progress via TaskReporter"
```

---

### Task 6: Migrate screenshots (per-file)

**Files:**
- Modify: `src/asc/commands/screenshots.py`
- Modify: screenshots web starter in `routes_api.py`
- Tests: screenshot tests with file-count progress

**Rules:** `scan` 5% + `upload` 95%; `total` = image file count; increment per file.

- [ ] **Step 1: Failing test** — 2 locales × 3 files → final `progress(6, 6)` (or last current/total == 6)

- [ ] **Step 2: Implement + remove locale-only PROGRESS**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(screenshots): per-file TaskReporter progress"
```

---

### Task 7: Migrate IAP, subscriptions, review screenshots

**Files:**
- Modify: `src/asc/commands/iap.py`
- Modify: `src/asc/commands/subscriptions.py`
- Modify: `src/asc/commands/iap_review_screenshots.py`
- Modify: IAP web starters in `routes_api.py`
- Tests: skip-path advances progress

**Rules:** `parse` 5 / `iap_items` 40 / `subscriptions` 55; no subscriptions → fold into `iap_items`; review screenshots `upload` 100% by file.

- [ ] **Step 1: Failing test** — existing-item `continue` still calls `reporter.progress`

- [ ] **Step 2: Implement three modules + web wiring**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(iap): TaskReporter progress including skip paths"
```

---

### Task 8: What's New — translate in-task + preview task

**Files:**
- Modify: `src/asc/commands/whats_new.py`
- Modify: `src/asc/web/routes_api.py` (`/whats-new/translate`, `/whats-new/run`)
- Modify: `src/asc/web/templates/whats_new.html`
- Tests: translate endpoint returns `task_id`; 60/40 phase mapping

**Interfaces:**
- Preview: response `{ "task_id": "..." }`; result on task `result.translations` (+ `errors`)
- `translate=true` run: translation happens inside worker, not in request thread
- Pre-supplied translations: upload-only

- [ ] **Step 1: Failing tests** for task_id response and 60/40 pct

- [ ] **Step 2: Implement CLI/Web/frontend**

Frontend preview: open drawer / poll status; on done read `result.translations`.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(whats-new): move LLM translate into task progress"
```

---

### Task 9: URLs + update

**Files:**
- Modify: URL update paths in `metadata.py` / urls web handlers
- Modify: `src/asc/commands/update_cmd.py`
- Modify: `routes_api.py` starters
- Tests: reporter recording

**Rules:** URLs phase `update` 100%, total = locales × fields written; update `download` 70 / `install` 30.

- [ ] **Step 1: Failing tests**

- [ ] **Step 2: Implement**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(urls,update): TaskReporter progress phases"
```

---

### Task 10: Build / deploy / release + Spinner bridge

**Files:**
- Modify: `src/asc/commands/build.py`
- Modify: `src/asc/progress.py` — optional `on_log_line: Callable[[str], None] | None = None`; on failure send last 20 lines through callback
- Modify: build web starter
- Tests: byte progress maps into upload weight window

**Rules:** archive 35 / export 15 / upload 50; deploy-only upload 100%; build-only renormalize archive+export; altool bytes → `reporter.progress` within upload phase.

- [ ] **Step 1: Failing test**

```python
def test_upload_phase_maps_bytes_into_global_pct():
    sink = RecordingSink()
    r = TaskReporter(sinks=[sink], verbose=False)
    r.set_phases([
        ("archive", 35, "归档"),
        ("export", 15, "导出"),
        ("upload", 50, "上传"),
    ])
    r.phase("archive"); r.progress(1, 1)
    r.phase("export"); r.progress(1, 1)
    r.phase("upload"); r.progress(50, 100, msg="50%")
    assert sink.progress_events[-1]["pct"] == 35 + 15 + 25
```

- [ ] **Step 2: Wire build_core/deploy_core to reporter; Spinner failure tails → `reporter.log`**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(build): structured phase progress via TaskReporter"
```

---

### Task 11: Remove legacy PROGRESS protocol

**Files:**
- Modify: `src/asc/web/routes_api.py` — remove all `_PROGRESS_RE` drain loops; every task uses `start_background_task`
- Grep clean: no `[PROGRESS:` under `src/asc/`
- Add: `tests/test_no_progress_protocol.py`

```python
from pathlib import Path

def test_no_progress_protocol_markers_in_src():
    root = Path("src/asc")
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "[PROGRESS:" in text:
            offenders.append(str(path))
    assert offenders == []
```

- [ ] **Step 1: Add test; run fail if markers remain**

- [ ] **Step 2: Delete markers and drains; migrate any remaining starters**

- [ ] **Step 3: Full suite**

Run: `pytest -v`

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(web): remove PROGRESS stdout scraping protocol"
```

---

### Task 12: Verbose plumbing + final verification

**Files:**
- CLI command modules: add `--verbose / -v` where missing; pass to `make_cli_reporter`
- Web run endpoints: accept `verbose` bool → `start_background_task(..., verbose=)`
- Prefer YAGNI: only persist `debug` lines when verbose (no drawer filter required)
- i18n only if new user-visible strings appear

- [ ] **Step 1: Tests for verbose flag on at least metadata CLI and one web endpoint**

- [ ] **Step 2: Implement**

- [ ] **Step 3: `pytest -v` full suite**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: plumb verbose flag through TaskReporter for CLI and Web"
```

---

## Spec coverage

| Spec requirement | Task |
|------------------|------|
| Unified TaskReporter + sinks | 1 |
| TaskStore phase fields | 2 |
| Web runner; end stdout scrape | 3, 11 |
| SSE lifetime while running | 3 |
| Frontend phase_index | 4 |
| Metadata 5/95 | 5 |
| Screenshots per-file | 6 |
| IAP skip advances; subscription weights | 7 |
| What's New translate 60/40 + preview task | 8 |
| URLs + update 70/30 | 9 |
| Build 35/15/50 + bytes | 10 |
| Remove `[PROGRESS:` | 11 |
| Verbose CLI/Web | 12 |
| Subprocess failure tails in web logs | 10 |

## Self-review

- Placeholder scan: no TBD/TODO left in interfaces.
- Type consistency: `set_phases` / `phase` / `progress` / `make_web_reporter` names match across tasks.
- Preview translate response becomes `{task_id}` — Task 8 updates frontend explicitly.
- Task 1 `TaskStoreSink` needs Task 2 signature; implement Task 2 before web integration (Task 3+).
