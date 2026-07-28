# Task State SQLite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace JSON task persistence with SQLite and add resumable SSE log cursors without changing the Web UI's HTTP + SSE contract.

**Architecture:** Keep `TaskStore` as the compatibility boundary. Store task rows and sequenced log rows in SQLite with WAL mode and migrate existing JSON on first open. The SSE endpoint reads the store incrementally from a cursor and emits event IDs.

**Tech Stack:** Python `sqlite3`, FastAPI `StreamingResponse`, pytest.

---

### Task 1: Add SQLite TaskStore tests

**Files:**
- Modify: `tests/test_web_tasks.py`

- [ ] Add tests that create a temporary SQLite-backed `TaskStore`, persist/reload task status, progress, result, and logs, and assert log order.
- [ ] Add a test that seeds the current JSON format and asserts first SQLite initialization imports it and marks pending/running tasks interrupted.
- [ ] Add a test that appends logs and verifies per-task sequence numbers are exposed by the store.
- [ ] Run `pytest tests/test_web_tasks.py -q` and confirm the new tests fail because SQLite persistence and sequence APIs are absent.

### Task 2: Implement SQLite persistence behind TaskStore

**Files:**
- Modify: `src/asc/web/tasks.py`
- Test: `tests/test_web_tasks.py`

- [ ] Add a SQLite connection initializer with WAL mode, schema creation, and a process lock.
- [ ] Preserve `ASC_WEB_TASKS_PATH`; interpret `.json` paths as legacy input and use a sibling `.db` path for the new store.
- [ ] Implement task CRUD, progress, cancellation, and recent-list queries using transactions.
- [ ] Implement one-time legacy JSON migration and preserve restart interruption behavior.
- [ ] Return logs with stable `seq` values and add a method to fetch logs after a cursor.
- [ ] Run `pytest tests/test_web_tasks.py -q` and then `pytest tests/test_web_sse.py -q`.

### Task 3: Add SSE cursor replay and event IDs

**Files:**
- Modify: `src/asc/web/routes_api.py`
- Modify: `src/asc/web/sse.py`
- Modify: `tests/test_web_sse.py`

- [ ] Add a failing test for `Last-Event-ID`/`after` replay and stable `id:` fields.
- [ ] Update SSE formatting to optionally include an event ID.
- [ ] Update `/api/task/{task_id}/stream` to replay only logs after the requested cursor, send progress changes, emit heartbeats, and terminate on terminal status.
- [ ] Keep existing event names (`log`, `progress`, `done`, `canceled`, `error_event`) unchanged.
- [ ] Run focused SSE tests and the full suite.

### Task 4: Document and verify migration behavior

**Files:**
- Modify: `README.md` or `README.zh-CN.md`
- Modify: `ARCHITECTURE.md`

- [ ] Document `~/.config/asc/tasks.db`, `ASC_WEB_TASKS_PATH`, JSON migration, and the retained HTTP + SSE model.
- [ ] Run `pytest` and inspect `git diff --check`.
- [ ] Commit the implementation with a Conventional Commit message.
