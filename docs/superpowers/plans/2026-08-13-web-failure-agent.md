# Web Failure Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dock-tab conversational agent that explains failed Web background tasks, proposes gated local fixes, and reruns only after the user confirms.

**Architecture:** Keep `LLMClient.chat()` unchanged for What's New translation. Add `chat_stream()` plus a Web-only orchestrator (`WebAgent`) that runs six model-visible tools, stores sessions in `agent_sessions.db`, and applies mutations only through `POST /api/agent/apply`. Replay snapshots on `task_runs` enable one-click rerun of new tasks; the existing task-log SSE path is untouched.

**Tech Stack:** Python 3.9+, FastAPI `StreamingResponse` SSE, `requests` streaming, SQLite WAL, Jinja2, vanilla JS (`fetch` + `ReadableStream`), pytest + `unittest.mock` (no live LLM).

**Spec:** `docs/superpowers/specs/2026-08-13-web-failure-agent-design.md`

## Global Constraints

- No CLI `asc agent` (or any Agent subcommand). CLI `--help` must not list Agent.
- Do not add the Anthropic SDK. Settings remain OpenAI-compatible `base_url` + API key. If a vendor cannot do `stream` + `tools`, treat it as a configuration error pointing at `/settings`.
- Do not add login, accounts, or multi-tenant remote hosting. Web stays a local service.
- Agent must not call App Store Connect create/update/delete APIs. ASC writes happen only if the user confirms apply+rerun of an existing Web task starter.
- Agent is not a general shell or arbitrary filesystem assistant.
- No auto-apply. No "remember and auto-apply" switch.
- Do not convert the translator to streaming or tool calling. `LLMClient.chat()` keeps `stream: false`, `response_format: {"type": "json_object"}`, no `tools`.
- Do not generate or redraw screenshot pixels. Screenshot mutations are rename / delete / reorder via existing `listing.local` helpers.
- Do not fabricate replay snapshots for historical rows (`replay_json` NULL). Those tasks can be explained, not one-click rerun.
- Model `tools` list is exactly: `get_task`, `list_failed_tasks`, `get_task_log`, `get_profile_context`, `inspect_local`, `propose_fix`. Never `apply_fix` or `rerun_task`.
- Business-file writes and new TaskStore tasks have one entry point: user-confirmed `POST /api/agent/apply` while `plans.status == pending`.
- Stop, timeout, missing LLM config, vendor errors: no `done`, promote no drafts to pending, write no business files, create no tasks.
- Tests must not hit a real model vendor. Mock `chat_stream` / orchestrator HTTP.
- Allow-list and apply path checks use the **bound task's profile**, not the sidebar cookie. Cookie only sorts failed-task search.
- UI copy is bilingual in `src/asc/web/locales/{zh,en}.json`. Answers use `request.state.lang`.
- `docs/superpowers/` is gitignored; commit plans/specs with `git add -f`.
- Follow Conventional Commits (`feat(web):`, `feat(llm):`, `test:`, `docs:`).

---

## File structure

```text
src/asc/llm.py                         # keep chat(); add chat_stream() + LLMHTTPError
src/asc/listing/local.py               # add rename_screenshot() using existing path guards
src/asc/web/agent_redact.py            # redact .p8 / issuer / key_id / PEM blocks on top of notifications
src/asc/web/agent_store.py             # SQLite sessions / messages / plans (not tasks.db)
src/asc/web/agent_tools.py             # six model tools + apply_fix mutations (server-only)
src/asc/web/agent.py                   # WebAgent: prompt, tool loop, stop flag, draft/pending/abandoned
src/asc/web/agent_rerun.py             # rerun_task from replay → start_background_task
src/asc/web/routes_agent.py            # /api/agent/* mounted from server.py
src/asc/web/tasks.py                   # replay_json column; has_replay in public JSON; list_failed
src/asc/web/task_runner.py             # start_background_task(..., replay=); sanitize_replay()
src/asc/web/routes_api.py              # pass replay at every _start_*_task create
src/asc/web/routes_listing.py          # listing-pull-screenshots replay
src/asc/web/server.py                  # include routes_agent; close AgentStore on shutdown
src/asc/web/templates/_task_log_drawer.html
src/asc/web/templates/base.html        # sidebar Agent button; agent-dock.js
src/asc/web/static/task-log-drawer.js  # tabs; open({tab}); pause follow; explain button
src/asc/web/static/task-log-drawer.css # tab + agent panel layout (keep 390px dock)
src/asc/web/static/agent-dock.js       # POST stream parser, cards, stop, apply/reject
src/asc/web/static/dashboard.js        # failed-row 「去 Agent 解释」
src/asc/web/locales/zh.json
src/asc/web/locales/en.json

tests/test_agent_redact.py
tests/test_llm.py                      # extend; chat() payload must stay json_object
tests/test_agent_store.py
tests/test_web_tasks.py                # replay column / has_replay / list_failed
tests/test_web_task_replay.py          # starters persist sanitized replay
tests/test_listing_local.py            # rename_screenshot
tests/test_agent_tools.py              # inspect_local allow-list + propose_fix
tests/test_agent_apply.py              # apply_fix + rerun gating
tests/test_web_agent.py                # orchestrator: tools, stop, drafts, no writes
tests/test_web_agent_routes.py         # HTTP SSE / apply / reject / failed-tasks
tests/test_web_server.py               # drawer/nav markup contracts
tests/test_cli_no_agent.py             # asc --help has no agent
```

Do not put Agent code in `src/asc/cli.py` or `src/asc/commands/`.

---

### Task 1: Secret redaction helper

**Files:**
- Create: `src/asc/web/agent_redact.py`
- Modify: `src/asc/web/notifications.py` (optional import only if you re-export; prefer calling `_sanitize_message_text` from agent_redact)
- Test: `tests/test_agent_redact.py`

**Interfaces:**
- Consumes: `asc.web.notifications._sanitize_message_text`
- Produces:
  - `def redact_text(value: Any) -> str`
  - `def redact_obj(value: Any, *, max_chars: int | None = None) -> Any` (strings redacted; dict/list walked; optional total JSON size cap)
  - Extra patterns beyond notifications: `.p8` paths, `issuer_id` / `key_id` assignments, `-----BEGIN PRIVATE KEY-----` ... `-----END PRIVATE KEY-----` blocks, PEM `BEGIN RSA PRIVATE KEY`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_redact.py
from __future__ import annotations

from asc.web.agent_redact import redact_obj, redact_text


def test_redact_text_strips_pem_p8_and_key_ids():
    raw = (
        "key_file=/Users/me/AuthKey_ABC123.p8 "
        "issuer_id=11223344-aaaa-bbbb-cccc-ddddeeeeffff "
        "key_id=AB12CD34 "
        "api_key=sk-secret "
        "-----BEGIN PRIVATE KEY-----\nMIIHideMe\n-----END PRIVATE KEY-----"
    )
    out = redact_text(raw)
    assert "MIIHideMe" not in out
    assert "sk-secret" not in out
    assert "AuthKey_ABC123.p8" not in out or ".p8" not in out
    assert "BEGIN PRIVATE KEY" not in out
    assert "11223344-aaaa-bbbb-cccc-ddddeeeeffff" not in out
    assert "AB12CD34" not in out


def test_redact_obj_walks_nested_and_caps():
    payload = {"result": {"error": "Bearer tok_live_abc failed"}, "nested": ["api_key=xyz"]}
    out = redact_obj(payload, max_chars=4096)
    blob = str(out)
    assert "tok_live_abc" not in blob
    assert "xyz" not in blob
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_redact.py -v`

Expected: FAIL with `ModuleNotFoundError: asc.web.agent_redact`

- [ ] **Step 3: Write minimal implementation**

```python
# src/asc/web/agent_redact.py
from __future__ import annotations

import json
import re
from typing import Any

from asc.web.notifications import _sanitize_message_text

P8_PATH_RE = re.compile(r"(?i)(?:[^\s'\"]+)?AuthKey_[A-Za-z0-9]+\.p8|[^\s'\"]+\.p8")
ISSUER_RE = re.compile(r"(?i)\b(issuer_id)\s*[=:]\s*([A-Za-z0-9-]+)")
KEY_ID_RE = re.compile(r"(?i)\b(key_id)\s*[=:]\s*([A-Za-z0-9]+)")
PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)


def redact_text(value: Any) -> str:
    text = _sanitize_message_text(value)
    text = PEM_BLOCK_RE.sub("[redacted-pem]", text)
    text = P8_PATH_RE.sub("[redacted-p8]", text)
    text = ISSUER_RE.sub(r"\1=[redacted]", text)
    text = KEY_ID_RE.sub(r"\1=[redacted]", text)
    return text


def redact_obj(value: Any, *, max_chars: int | None = None) -> Any:
    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return redact_text(node)
        if isinstance(node, dict):
            return {str(k): walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    walked = walk(value)
    if max_chars is None:
        return walked
    encoded = json.dumps(walked, ensure_ascii=False)
    if len(encoded) <= max_chars:
        return walked
    return {"truncated": True, "preview": redact_text(encoded[:max_chars])}
```

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_agent_redact.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_redact.py src/asc/web/agent_redact.py
git commit -m "feat(web): redact PEM, .p8, and key ids for agent text"
```

---

### Task 2: `LLMClient.chat_stream`

**Files:**
- Modify: `src/asc/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: existing `LLMClient.__init__`, `_chat_completions_url`
- Produces:
  - `class LLMHTTPError(Exception)` with `status_code: int` and `retry_after: float | None`
  - `def chat_stream(self, messages: list[dict], tools: list[dict], temperature: float = 0.3) -> Iterator[dict[str, Any]]`
  - Each yielded dict may contain any of: `role: str`, `content: str`, `tool_calls: list[dict]`, `finish_reason: str`
  - Request body MUST set `stream: true`, MUST send `tools`, MUST NOT set `response_format`
  - HTTP timeout is `self.timeout` (default 60). This method does **not** retry 429/5xx; it raises `LLMHTTPError` so the orchestrator retries (spec §12)
  - `chat()` payload unchanged: `stream: false`, `response_format: {"type": "json_object"}`, no `tools`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm.py`:

```python
def test_chat_stream_yields_content_and_tool_call_deltas():
    from src.asc.llm import LLMClient

    sse = (
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"get_task","arguments":"{"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"}"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )
    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            text=sse,
            headers={"Content-Type": "text/event-stream"},
        )
        client = LLMClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
        )
        events = list(
            client.chat_stream(
                [{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "get_task"}}],
            )
        )
    body = json.loads(m.last_request.text)
    assert body["stream"] is True
    assert "response_format" not in body
    assert body["tools"][0]["function"]["name"] == "get_task"
    contents = "".join(e.get("content", "") for e in events)
    assert "Hello" in contents
    assert any(e.get("finish_reason") == "tool_calls" for e in events)
    assert any("tool_calls" in e for e in events)


def test_chat_stream_raises_llm_http_error_on_429():
    from src.asc.llm import LLMClient, LLMHTTPError

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            status_code=429,
            headers={"Retry-After": "2"},
            json={"error": "rate limited"},
        )
        client = LLMClient(api_key="k", base_url="https://api.openai.com/v1", model="gpt-4o")
        with pytest.raises(LLMHTTPError) as exc:
            list(client.chat_stream([], tools=[]))
        assert exc.value.status_code == 429
        assert exc.value.retry_after == 2.0


def test_chat_still_sends_json_object_without_tools():
    from src.asc.llm import LLMClient

    with rm.Mocker() as m:
        m.post(
            "https://api.openai.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "{}"}}]},
        )
        LLMClient(api_key="k", base_url="https://api.openai.com/v1", model="gpt-4o").chat(
            [{"role": "user", "content": "x"}]
        )
        body = json.loads(m.last_request.text)
        assert body["stream"] is False
        assert body["response_format"] == {"type": "json_object"}
        assert "tools" not in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm.py::test_chat_stream_yields_content_and_tool_call_deltas tests/test_llm.py::test_chat_stream_raises_llm_http_error_on_429 tests/test_llm.py::test_chat_still_sends_json_object_without_tools -v`

Expected: FAIL (`chat_stream` / `LLMHTTPError` not defined)

- [ ] **Step 3: Write minimal implementation**

Add to `src/asc/llm.py`:

```python
from collections.abc import Iterator

class LLMHTTPError(Exception):
    def __init__(self, status_code: int, retry_after: float | None = None) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"LLM HTTP {status_code}")


class LLMClient:
    # ... existing chat() unchanged ...

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.3,
    ) -> Iterator[dict[str, Any]]:
        url = self._chat_completions_url()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        response = requests.post(
            url, json=payload, headers=headers, timeout=self.timeout, stream=True,
        )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "1")
            try:
                wait = float(retry_after)
            except ValueError:
                wait = 1.0
            response.close()
            raise LLMHTTPError(429, retry_after=wait)
        if response.status_code >= 500:
            response.close()
            raise LLMHTTPError(response.status_code, retry_after=1.0)
        if response.status_code >= 400:
            response.close()
            raise LLMHTTPError(response.status_code)
        try:
            for raw in response.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                line = raw.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for choice in obj.get("choices") or []:
                    delta = choice.get("delta") or {}
                    event: dict[str, Any] = {}
                    if delta.get("role"):
                        event["role"] = delta["role"]
                    if delta.get("content"):
                        event["content"] = delta["content"]
                    if delta.get("tool_calls"):
                        event["tool_calls"] = delta["tool_calls"]
                    finish = choice.get("finish_reason")
                    if finish:
                        event["finish_reason"] = finish
                    if event:
                        yield event
        finally:
            response.close()
```

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_llm.py -v`

Expected: PASS (including all existing `chat()` tests)

- [ ] **Step 5: Commit**

```bash
git add src/asc/llm.py tests/test_llm.py
git commit -m "feat(llm): add chat_stream with tools and no response_format"
```

---

### Task 3: AgentStore SQLite

**Files:**
- Create: `src/asc/web/agent_store.py`
- Modify: `src/asc/web/server.py` lifespan to `close()` the store
- Test: `tests/test_agent_store.py`

**Interfaces:**
- Consumes: none
- Produces:
  - Path: `os.getenv("ASC_WEB_AGENT_PATH")` or `~/.config/asc/agent_sessions.db`
  - WAL, explicit close, new connection per operation (same discipline as `TaskStore._connection`)
  - `PLAN_STATUSES = ("draft", "pending", "applying", "applied", "rejected", "abandoned", "apply_failed")`
  - `class AgentStore`
    - `get_or_create_session(task_id: str | None, profile: str) -> dict` — reuse session for same `task_id`
    - `get_session(session_id: str) -> dict | None`
    - `list_messages(session_id: str, limit: int = 20) -> list[dict]`
    - `append_message(session_id: str, role: str, content: str, *, tool_name: str | None = None, tool_call_id: str | None = None) -> int`  # returns seq
    - `list_plans(session_id: str, *, statuses: tuple[str, ...] | None = None) -> list[dict]`
    - `insert_plan_draft(session_id: str, turn_seq: int, summary: str, mutations: list, rerun: dict | None, manual_steps: list) -> str`  # server UUID
    - `promote_drafts(session_id: str, turn_seq: int) -> list[str]`  # draft→pending, return plan ids
    - `abandon_drafts(session_id: str, turn_seq: int) -> int`
    - `get_plan(plan_id: str) -> dict | None`  # always includes `status`
    - `claim_pending(plan_id: str) -> dict | None`  # pending→applying atomically; None if lost race
    - `set_plan_status(plan_id: str, status: str, *, error: str | None = None, new_task_id: str | None = None) -> None`
    - `reject_pending(plan_id: str) -> bool`  # pending→rejected
    - `close() -> None`
  - Tables exactly:
    - `sessions(id, task_id, profile, created_at, updated_at)`
    - `messages(session_id, seq, role, content, tool_name, tool_call_id, created_at)`
    - `plans(id, session_id, turn_seq, status, summary, mutations_json, rerun_json, manual_steps_json, error, new_task_id, created_at, settled_at)`
  - Module singleton `agent_store = AgentStore()` like `task_store`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_store.py
from __future__ import annotations

from pathlib import Path

from asc.web.agent_store import AgentStore


def test_reuse_session_per_task_and_plan_lifecycle(tmp_path: Path):
    store = AgentStore(tmp_path / "agent.db")
    try:
        a = store.get_or_create_session("task-1", "myapp")
        b = store.get_or_create_session("task-1", "myapp")
        assert a["id"] == b["id"]
        seq = store.append_message(a["id"], "user", "explain")
        assert seq == 1
        plan_id = store.insert_plan_draft(
            a["id"], turn_seq=1, summary="fix csv", mutations=[{"op": "csv_set_fields"}],
            rerun={"task_id": "task-1", "kind": "metadata"}, manual_steps=[],
        )
        plan = store.get_plan(plan_id)
        assert plan["status"] == "draft"
        ids = store.promote_drafts(a["id"], 1)
        assert ids == [plan_id]
        assert store.get_plan(plan_id)["status"] == "pending"
        claimed = store.claim_pending(plan_id)
        assert claimed is not None
        assert store.claim_pending(plan_id) is None
        store.set_plan_status(plan_id, "applied", new_task_id="new-1")
        assert store.get_plan(plan_id)["new_task_id"] == "new-1"
        listed = store.list_plans(a["id"])
        assert listed[0]["id"] == plan_id
        assert listed[0]["status"] == "applied"
    finally:
        store.close()


def test_abandon_drafts_blocks_claim(tmp_path: Path):
    store = AgentStore(tmp_path / "agent.db")
    try:
        session = store.get_or_create_session("t2", "p")
        plan_id = store.insert_plan_draft(
            session["id"], 1, "x", [{"op": "toml_set"}], None, [],
        )
        store.abandon_drafts(session["id"], 1)
        assert store.get_plan(plan_id)["status"] == "abandoned"
        assert store.claim_pending(plan_id) is None
        assert store.reject_pending(plan_id) is False
    finally:
        store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_store.py -v`

Expected: FAIL with import error

- [ ] **Step 3: Write minimal implementation**

Implement `AgentStore` with `CREATE TABLE IF NOT EXISTS` as specified. `claim_pending` must be `UPDATE plans SET status='applying' WHERE id=? AND status='pending'` and return the row only if `rowcount == 1`. `get_or_create_session` looks up `task_id` when it is not None; empty/None `task_id` always inserts a new session.

In `src/asc/web/server.py` lifespan `finally`, call `agent_store.close()` beside `task_store.close()`. Honor `ASC_WEB_AGENT_PATH` in the constructor used by the module singleton.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_agent_store.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/agent_store.py src/asc/web/server.py tests/test_agent_store.py
git commit -m "feat(web): add agent session SQLite store"
```

---

### Task 4: TaskStore replay column and failed-task listing

**Files:**
- Modify: `src/asc/web/tasks.py` (`create`, `_init_db`, `_apply_op` create, `_save` INSERT, `_task_from_row`, `_public_task`)
- Modify: `src/asc/web/task_runner.py` (`sanitize_replay`, `start_background_task` replay kwarg)
- Test: `tests/test_web_tasks.py` (append)

**Interfaces:**
- Consumes: existing `TaskStore.create(kind, profile="")`
- Produces:
  - `task_runs.replay_json TEXT` (NULL for legacy rows)
  - `TaskStore.create(self, kind: str, *, profile: str = "", replay: dict | None = None) -> str`
  - `TaskStore.get_replay(self, task_id: str) -> dict | None`
  - `TaskStore.list_failed(self, *, limit: int = 20, kind: str | None = None, profile: str | None = None, prefer_profile: str | None = None) -> list[dict]`
    - only `status=error`; default 20, cap 50; `prefer_profile` rows first, then `updated_at` desc; other profiles remain searchable
  - Public task JSON (`get` / `list_recent_states` / dashboard) includes `has_replay: bool` and MUST NOT include `replay` or `params`
  - `FORBIDDEN_REPLAY_KEYS = {"issuer_id", "key_id", "key_file", "api_key", "authorization", "certificate", "provisioning_profile"}`
  - `def sanitize_replay(kind: str, profile: str, verbose: bool, params: dict) -> dict` in `task_runner.py`
    - drops forbidden keys (case-insensitive)
    - if `params["text"]` is a str, truncate to 8192 chars
    - if `signing` present, only allow `"auto"` or `"manual"` (else omit)
    - returns `{"kind", "profile", "verbose", "params"}`
  - `start_background_task(..., replay: dict | None = None)`: when `task_id is None`, `store.create(..., replay=replay)`; when caller already created the row, call a new `store.set_replay(task_id, replay)` if replay is not None
  - Add missing labels (used by Agent UI and dashboard titles):
    - `TASK_KIND_LABELS["whats-new-translate"] = "更新说明翻译"`
    - `TASK_KIND_LABELS["listing-pull-screenshots"] = "拉取截图"`
    - `TASK_KIND_RETRY_PATHS["whats-new-translate"] = "/whats-new"`
    - `TASK_KIND_RETRY_PATHS["listing-pull-screenshots"] = "/metadata"`

Critical: `_save` `INSERT OR REPLACE` currently lists columns without `replay_json`. You MUST add `replay_json` there or a later save will wipe snapshots.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_tasks.py`:

```python
def test_create_stores_replay_but_public_json_only_has_flag(tmp_path):
    from asc.web.task_runner import sanitize_replay
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    try:
        replay = sanitize_replay(
            "metadata",
            "myapp",
            False,
            {
                "csv_path": "data/appstore_info.csv",
                "issuer_id": "SECRET-ISSUER",
                "key_file": "/tmp/AuthKey_X.p8",
                "api_key": "sk-live",
            },
        )
        assert "issuer_id" not in replay["params"]
        assert "key_file" not in replay["params"]
        assert "api_key" not in replay["params"]
        task_id = store.create("metadata", profile="myapp", replay=replay)
        public = store.get_state(task_id)
        assert public["has_replay"] is True
        assert "replay" not in public
        assert "params" not in public
        stored = store.get_replay(task_id)
        assert stored["params"]["csv_path"] == "data/appstore_info.csv"
        assert "SECRET-ISSUER" not in str(stored)
    finally:
        store.close()


def test_list_failed_only_errors_and_prefers_cookie_profile(tmp_path):
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    try:
        a = store.create("metadata", profile="keep")
        b = store.create("build", profile="other")
        c = store.create("iap", profile="keep")
        store.set_status(a, TaskStatus.ERROR)
        store.set_status(b, TaskStatus.ERROR)
        store.set_status(c, TaskStatus.DONE)
        rows = store.list_failed(limit=50, prefer_profile="keep")
        assert [row["id"] for row in rows][0] == a
        assert all(row["status"] == TaskStatus.ERROR or row["status"] == "error" for row in rows)
        assert c not in [row["id"] for row in rows]
        assert all("params" not in row for row in rows)
    finally:
        store.close()


def test_legacy_row_without_replay_has_replay_false(tmp_path):
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    try:
        task_id = store.create("update", profile="system")
        assert store.get_state(task_id)["has_replay"] is False
        assert store.get_replay(task_id) is None
    finally:
        store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_tasks.py::test_create_stores_replay_but_public_json_only_has_flag tests/test_web_tasks.py::test_list_failed_only_errors_and_prefers_cookie_profile tests/test_web_tasks.py::test_legacy_row_without_replay_has_replay_false -v`

Expected: FAIL (`create()` unexpected kwarg / missing `list_failed`)

- [ ] **Step 3: Write minimal implementation**

1. `_init_db`: `ALTER TABLE task_runs ADD COLUMN replay_json TEXT` if missing.
2. create INSERT includes `replay_json`.
3. `_public_task`: `has_replay = bool(task.get("replay"))`; pop `replay` from the returned dict.
4. `list_failed`: SQL `WHERE status='error'` plus optional `kind`/`profile`; Python sort if `prefer_profile`.
5. Implement `sanitize_replay` / `set_replay` / `start_background_task` replay kwarg.
6. Extend `_save` column list.

In-memory JSON `TaskStore` (no db path) should still store `task["replay"]` so unit tests without SQLite keep working.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_web_tasks.py tests/test_web_task_runner.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/tasks.py src/asc/web/task_runner.py tests/test_web_tasks.py
git commit -m "feat(web): persist sanitized task replay snapshots"
```

---

### Task 5: Write replay at every Web task starter

**Files:**
- Modify: `src/asc/web/routes_api.py` (every `_start_*_task` / `create` site)
- Modify: `src/asc/web/routes_listing.py` (`_start_listing_pull_screenshots_task`)
- Test: `tests/test_web_task_replay.py`

**Interfaces:**
- Consumes: `sanitize_replay`, `TaskStore.create(..., replay=)`
- Produces: replay `params` per kind (no secrets):

| kind | params keys |
|------|-------------|
| `metadata` | `csv_path`, `screenshots_dir`, `include_metadata`, `include_screenshots`, `dry_run`, `locales`, `fields_by_locale`, `screenshot_scopes` |
| `build` | `mode`, `project`, `scheme`, `destination`, `ipa_path`, `signing` (`auto`/`manual` only), `dry_run`, `reuse_archive` |
| `whats-new` | `dry_run`, `text` (cap 8KiB), `locales`, `translate`, `source_locale`, `translations` (object ok), `source_file` if a file path exists (Web today is paste-only → omit `source_file`) |
| `whats-new-translate` | `text` (cap 8KiB), `source_locale` |
| `iap` | `iap_file`, `dry_run`, `update_existing` |
| `iap-review-screenshots` | `dry_run`, `items` as `{kind,id,productId,path}` (local paths, not bytes) |
| `urls` | `field`, `url`, `locales`, `dry_run` |
| `update` | `version`, `branch` |
| `listing-pull-screenshots` | `screenshots_dir`, `scopes` |

Pass `replay=sanitize_replay(...)` into `create(...)`. Do not put `issuer_id` / `key_id` / `key_file` / certificate names in params.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_task_replay.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

from asc.web.tasks import TaskStore


def test_metadata_starter_writes_replay(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr("asc.web.routes_api._task_store", store)
    monkeypatch.setattr("asc.web.task_runner.start_background_task", lambda *a, **k: k.get("task_id") or "x")
    from asc.web.routes_api import _start_metadata_task

    task_id = _start_metadata_task(
        profile="myapp",
        csv_path="data/appstore_info.csv",
        screenshots_dir="data/screenshots",
        include_metadata=True,
        include_screenshots=False,
        dry_run=True,
        verbose=False,
        locales=["zh-Hans"],
        fields_by_locale=None,
        screenshot_scopes=None,
    )
    replay = store.get_replay(task_id)
    assert replay["kind"] == "metadata"
    assert replay["params"]["csv_path"] == "data/appstore_info.csv"
    assert replay["params"]["include_screenshots"] is False
    assert "issuer_id" not in replay["params"]
    store.close()


def test_build_starter_omits_certificate_fields(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr("asc.web.routes_api._task_store", store)
    monkeypatch.setattr("asc.web.task_runner.start_background_task", lambda *a, **k: k.get("task_id") or "x")
    from asc.web.routes_api import _start_build_task

    task_id = _start_build_task(
        profile="myapp",
        mode="build",
        project="App.xcodeproj",
        scheme="App",
        destination="testflight",
        ipa_path="",
        verbose=False,
        signing="manual",
        certificate="iPhone Distribution: Secret",
        provisioning_profile="secret-profile",
        dry_run=True,
    )
    params = store.get_replay(task_id)["params"]
    assert params["signing"] == "manual"
    assert params["project"] == "App.xcodeproj"
    assert "certificate" not in params
    assert "provisioning_profile" not in params
    store.close()


def test_remaining_starters_write_kind_specific_replay(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr("asc.web.routes_api._task_store", store)
    monkeypatch.setattr("asc.web.routes_listing.task_store", store)
    monkeypatch.setattr("asc.web.task_runner.start_background_task", lambda *a, **k: k.get("task_id") or "x")
    from asc.web.routes_api import (
        _start_iap_task,
        _start_urls_task,
        _start_update_task,
        _start_whats_new_task,
        _start_whats_new_translate_task,
    )
    from asc.web.routes_listing import _start_listing_pull_screenshots_task

    iap_id = _start_iap_task("myapp", "data/iap_packages.json", True, False, False)
    assert store.get_replay(iap_id)["params"]["iap_file"] == "data/iap_packages.json"
    url_id = _start_urls_task(
        profile="myapp",
        field="supportUrl",
        url="https://example.com/s",
        locales=["en-US"],
        dry_run=True,
        verbose=False,
    )
    assert store.get_replay(url_id)["params"]["field"] == "supportUrl"
    upd_id = _start_update_task(version="0.1.26", branch=None, verbose=False)
    assert store.get_replay(upd_id)["params"]["version"] == "0.1.26"
    wn_id = _start_whats_new_task("myapp", True, text="hello", locales=["en-US"], verbose=False)
    assert store.get_replay(wn_id)["params"]["text"] == "hello"
    assert "source_file" not in store.get_replay(wn_id)["params"]
    tr_id = _start_whats_new_translate_task("myapp", "hello", "en-US", False)
    assert store.get_replay(tr_id)["kind"] == "whats-new-translate"
    pull_id = _start_listing_pull_screenshots_task("myapp", "data/screenshots", [{"locale": "en-US", "display_type": "APP_IPHONE_67"}])
    assert store.get_replay(pull_id)["params"]["screenshots_dir"] == "data/screenshots"
    store.close()
```

If a starter signature differs, adapt the call to the current function (do not change its user-facing behavior except adding `replay=`). Confirm `_start_urls_task` argument order in `routes_api.py` before copying.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_task_replay.py -v`

Expected: FAIL (`get_replay` None)

- [ ] **Step 3: Write minimal implementation**

At each `task_id = _task_store.create(...)` site, pass `replay=sanitize_replay(kind, profile, verbose, params)`. Same for listing pull. Import `sanitize_replay` from `task_runner`.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_web_task_replay.py tests/test_web_whats_new.py tests/test_iap_review_screenshots.py tests/test_web_listing.py -v`

Expected: PASS (existing starters still return `task_id`)

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/routes_api.py src/asc/web/routes_listing.py tests/test_web_task_replay.py
git commit -m "feat(web): snapshot replay params when starting tasks"
```

---

### Task 6: Model-visible read tools and `inspect_local`

**Files:**
- Create: `src/asc/web/agent_tools.py` (read tools + allow-list; `propose_fix` stub that raises until Task 7 is fine — implement reads here)
- Modify: `src/asc/listing/local.py` (optional: none yet)
- Test: `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: `TaskStore.get` / `get_replay` / `list_failed` / `get_logs_after` or log query; `Config(app_name=)`; `listing.local._assert_under_root`; `redact_text` / `redact_obj`
- Produces:
  - `MODEL_TOOL_NAMES = ("get_task", "list_failed_tasks", "get_task_log", "get_profile_context", "inspect_local", "propose_fix")`
  - `OPENAI_TOOLS: list[dict]` — OpenAI function schemas for those six names only
  - `class AgentToolContext`: `task_store`, `agent_store`, `bound_task_id: str | None`, `project_root: Path` (`Path.cwd()` at Web start), `turn_seq: int`, `session_id: str = ""`
  - `def execute_model_tool(ctx: AgentToolContext, name: str, arguments: dict) -> dict`
    - unknown name or `apply_fix` / `rerun_task` → `{"ok": False, "error": "writes are gated; use propose_fix"}` and **do not** touch disk or `TaskStore.create`
  - `get_task(task_id)` → kind, title, profile, status, redacted result, timestamps, `retry_path`, `has_replay`, redacted replay `params` (only this tool returns params). Combined result+params strings ≤ 4KiB. No full logs.
  - `list_failed_tasks(kind=None, profile=None, limit=20)` cap 50, no log bodies
  - `get_task_log(task_id, tail=400)`: each line redacted; if error/traceback lines exist, include all of them (cap 200) then fill with tail context to **total 400 lines**; whole payload ≤ 80KiB
  - Error-line detector (Python, match drawer JS): `re.search(r"\b(error|failed|failure|fatal|exception|traceback)\b|错误|失败|异常", message, re.I)` plus `"traceback" in message.lower()`
  - `get_profile_context(profile=None)`: use bound task profile if present. Return name, csv/screenshots/iap paths, `.asc/config.toml` `[defaults]` and `[build]` only. Strip `issuer_id`, `key_id`, `key_file`, `.p8` paths, `api_key`.
  - `inspect_local(path, max_bytes=65536)`:
    - resolve; `_assert_under_root` against allow-list roots:
      1. bound profile `csv_path` file
      2. `screenshots_path` directory (dirs: names, optional size, mtime; never PNG/JPG bytes)
      3. IAP JSON path
      4. `project_root / ".asc" / "config.toml"` with `[credentials]` stripped before return
      5. `build.log` / `export.log` / `upload.log` under replay `[build].output` or `project_root / "build"`
      6. What's New `source_file` from replay if present
    - reject `~/.config/asc/keys/**`, `llm.toml`, `guard.json`, `profiles/*.toml`, any `.p8`, home/system paths outside roots
    - binary → `{"ok": True, "binary": True, "size": int, "suffix": str}`
    - default/cap `max_bytes=64KiB`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agent_tools.py
from __future__ import annotations

from pathlib import Path

from asc.web.agent_tools import AgentToolContext, execute_model_tool, OPENAI_TOOLS, MODEL_TOOL_NAMES
from asc.web.tasks import TaskStatus, TaskStore


def _ctx(tmp_path, store, task_id=None, agent_store=None, session_id=""):
    return AgentToolContext(
        task_store=store,
        agent_store=agent_store,
        bound_task_id=task_id,
        project_root=tmp_path,
        turn_seq=1,
        session_id=session_id,
    )


def test_openai_tools_are_exactly_six_readonly_or_propose():
    names = {t["function"]["name"] for t in OPENAI_TOOLS}
    assert names == set(MODEL_TOOL_NAMES)
    assert "apply_fix" not in names
    assert "rerun_task" not in names


def test_hallucinated_apply_fix_does_not_write(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,old\n", encoding="utf-8")
    before = csv_path.read_bytes()
    out = execute_model_tool(_ctx(tmp_path, store), "apply_fix", {"plan_id": "x"})
    assert out["ok"] is False
    assert "gated" in out["error"]
    assert csv_path.read_bytes() == before
    assert store.list_recent_states(limit=10) == []
    store.close()


def test_get_task_log_redacts_pem_and_caps_error_lines(tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata", profile="myapp")
    store.append_log(task_id, "-----BEGIN PRIVATE KEY-----\\nMIISECRET\\n-----END PRIVATE KEY-----")
    store.append_log(task_id, "Traceback (most recent call last):")
    store.append_log(task_id, "ok line")
    store.set_status(task_id, TaskStatus.ERROR)
    result = execute_model_tool(_ctx(tmp_path, store, task_id), "get_task_log", {"task_id": task_id})
    blob = str(result)
    assert "MIISECRET" not in blob
    assert "BEGIN PRIVATE KEY" not in blob
    assert result["ok"] is True
    store.close()


def test_inspect_local_rejects_key_file_and_allows_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "appstore_info.csv"
    csv_path.write_text("locale,name\nen-US,App\n", encoding="utf-8")
    keys = tmp_path / "keys"
    keys.mkdir()
    p8 = keys / "AuthKey_X.p8"
    p8.write_text("-----BEGIN PRIVATE KEY-----\\nNOPE\\n-----END PRIVATE KEY-----", encoding="utf-8")
    store = TaskStore(tmp_path / "tasks.db")
    replay = {"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}}
    task_id = store.create("metadata", profile="myapp", replay=replay)
    monkeypatch.chdir(tmp_path)
    ctx = _ctx(tmp_path, store, task_id)
    denied = execute_model_tool(ctx, "inspect_local", {"path": str(p8)})
    assert denied["ok"] is False
    allowed = execute_model_tool(ctx, "inspect_local", {"path": str(csv_path)})
    assert allowed["ok"] is True
    assert "App" in str(allowed)
    store.close()
```

For `inspect_local` CSV allow-list, resolve the bound task profile's csv via `Config` **or** (in tests) via replay `params.csv_path` plus `project_root`. Prefer: roots come from `Config(app_name=task.profile)` when the profile exists; tests should monkeypatch `Config.csv_path` / `screenshots_path` / `iap_path` onto a simple namespace if loading real profiles is heavy. Using replay paths as additional roots when present is required for tmp_path tests.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_tools.py -v`

Expected: FAIL with import error

- [ ] **Step 3: Write minimal implementation**

Implement `execute_model_tool` switch. `propose_fix` may return `{"ok": False, "error": "not implemented"}` until Task 7 — do **not** write files. Hallucinated write tools always take the gated branch before any other logic.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_agent_tools.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/agent_tools.py tests/test_agent_tools.py
git commit -m "feat(web): add agent read tools with path allow-list"
```

---

### Task 7: `propose_fix` validation (draft only)

**Files:**
- Modify: `src/asc/web/agent_tools.py`
- Test: `tests/test_agent_tools.py` (append)

**Interfaces:**
- Consumes: `AgentStore.insert_plan_draft`, `AgentToolContext`, allow-list from Task 6, `FIELD_NAMES` from `asc.listing.models`
- Produces:
  - `propose_fix(arguments) -> {"ok": True, "plan_id": str, "status": "draft"}` or field-level `{"ok": False, "error": ...}`
  - Server generates `plan_id`; ignore any model-supplied id
  - Allowed `op` only: `csv_set_fields`, `json_patch`, `toml_set`, `text_replace`, `screenshot_fs`
  - `csv_set_fields`: `path` must be the profile CSV; `fields` keys ⊆ `FIELD_NAMES`; `locale` required
  - `json_patch`: RFC 6902 `replace`/`add`/`remove` only; pointer terminal keys limited to `name`, `description`, `reviewNote`, `displayName`, `baseAmount`, `price`, localization `name`/`description`, review-screenshot path fields (`reviewScreenshot`, `reviewScreenshotPath`, `screenshot`, `screenshotPath`); path must be profile IAP JSON
  - `toml_set`: path must be `project_root/.asc/config.toml`; dotted keys only `defaults.csv`, `defaults.screenshots`, `build.project`, `build.scheme`, `build.output`, `build.signing`; `build.signing` ∈ {`auto`,`manual`}; reject `credentials.*`
  - `text_replace`: only if replay `params.source_file` exists and `path` equals that file; require `before`, `after`, `count` (int)
  - `screenshot_fs`: `action` ∈ {`rename`,`delete`,`reorder`}; path under `screenshots_path`
  - `rerun` optional; if present must include `task_id` + `kind`; **illegal** when `mutations` is empty
  - empty `mutations` + non-empty `manual_steps` is valid (no apply button later)
  - On success insert status `draft` only. Do not change CSV/JSON/TOML/screenshots/`tasks.db`

- [ ] **Step 1: Write the failing tests**

```python
def test_propose_fix_inserts_draft_without_touching_csv(tmp_path, monkeypatch):
    from asc.web.agent_store import AgentStore
    from asc.web.agent_tools import AgentToolContext, execute_model_tool
    from asc.web.tasks import TaskStore

    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    before = csv_path.read_bytes()
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}}
    task_id = tasks.create("metadata", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    monkeypatch.chdir(tmp_path)
    result = execute_model_tool(ctx, "propose_fix", {
        "summary": "truncate keywords",
        "mutations": [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "zh-Hans",
            "fields": {"keywords": "new"},
            "before": {"keywords": "oldkeywords"},
        }],
        "rerun": {"task_id": task_id, "kind": "metadata"},
        "manual_steps": [],
    })
    assert result["ok"] is True
    plan = agents.get_plan(result["plan_id"])
    assert plan["status"] == "draft"
    assert csv_path.read_bytes() == before
    tasks.close()
    agents.close()


def test_propose_fix_rejects_credentials_toml_and_empty_rerun(tmp_path):
    from asc.web.agent_store import AgentStore
    from asc.web.agent_tools import AgentToolContext, execute_model_tool
    from asc.web.tasks import TaskStore

    cfg_dir = tmp_path / ".asc"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "config.toml"
    cfg_path.write_text("[credentials]\nissuer_id = \"keep-me\"\n[build]\nscheme = \"App\"\n", encoding="utf-8")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {"kind": "build", "profile": "myapp", "verbose": False, "params": {}}
    task_id = tasks.create("build", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    cred = execute_model_tool(ctx, "propose_fix", {
        "summary": "steal creds",
        "mutations": [{
            "op": "toml_set",
            "path": str(cfg_path),
            "key": "credentials.issuer_id",
            "value": "hacked",
        }],
        "manual_steps": [],
    })
    assert cred["ok"] is False
    empty_rerun = execute_model_tool(ctx, "propose_fix", {
        "summary": "manual only",
        "mutations": [],
        "rerun": {"task_id": task_id, "kind": "build"},
        "manual_steps": ["fix in Xcode"],
    })
    assert empty_rerun["ok"] is False
    unknown = execute_model_tool(ctx, "propose_fix", {
        "summary": "nope",
        "mutations": [{"op": "shell", "path": "/tmp/x"}],
        "manual_steps": [],
    })
    assert unknown["ok"] is False
    assert agents.list_plans(session["id"]) == []
    assert "keep-me" in cfg_path.read_text(encoding="utf-8")
    tasks.close()
    agents.close()
```

`AgentToolContext.session_id` is required for `insert_plan_draft`. Task 6 tests already pass `session_id=""` via `_ctx`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_tools.py::test_propose_fix_inserts_draft_without_touching_csv -v`

Expected: FAIL (`not implemented` or missing status draft)

- [ ] **Step 3: Write minimal implementation**

Validate, then `agent_store.insert_plan_draft(...)`. Never call `save_local_csv` here.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_agent_tools.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/agent_tools.py tests/test_agent_tools.py
git commit -m "feat(web): validate propose_fix into draft plans"
```

---

### Task 8: `apply_fix` mutations (server-only)

**Files:**
- Modify: `src/asc/web/agent_tools.py` (server functions, not in `OPENAI_TOOLS`)
- Modify: `src/asc/listing/local.py` — add `rename_screenshot`
- Test: `tests/test_agent_apply.py`, `tests/test_listing_local.py`

**Interfaces:**
- Consumes: `claim_pending`, listing helpers, `save_local_csv` / `FileChangedError`, `load_local_text_snapshot`
- Produces:
  - `def apply_fix(ctx, plan_id: str) -> dict`  # `{ok, status, error?, failed_step?}`
    1. `claim_pending`; if None → treat as conflict (`ok=False`, `code=conflict`) — do not write
    2. Run mutations in order against **task profile** allow-list
    3. On first failure: `status=apply_failed`, no rollback, return failed step index/op
    4. All success: `status=applied`
  - `csv_set_fields`: re-read disk; `before` must match current locale fields; then `save_local_csv` (mtime check if you capture mtime before write)
  - `json_patch`: implement RFC 6902 `add`/`remove`/`replace` locally (do **not** add a `jsonpatch` dependency); re-check pointer allow-list
  - `toml_set`: read/write with `tomllib`+`toml`; never write `[credentials]`
  - `text_replace`: `path.read_text().count(before) == count` else fail; then replace
  - `screenshot_fs`:
    - `rename` → new `rename_screenshot(path, new_name, root=screenshots_path)`
    - `delete` → `_assert_under_root` then `delete_screenshot`
    - `reorder` → `apply_screenshot_order`
  - `def rename_screenshot(path: Path, new_name: str, *, root: Path | str) -> Path` using `_assert_under_root` + `_safe_basename` + `Path.rename`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_listing_local.py — append
def test_rename_screenshot_stays_under_root(tmp_path):
    from asc.listing.local import rename_screenshot, PathTraversalError

    root = tmp_path / "shots"
    root.mkdir()
    src = root / "01_a.png"
    src.write_bytes(b"png")
    out = rename_screenshot(src, "02_b.png", root=root)
    assert out.name == "02_b.png"
    assert not src.exists()
    try:
        rename_screenshot(out, "../escape.png", root=root)
        assert False, "should reject"
    except PathTraversalError:
        pass


# tests/test_agent_apply.py
from __future__ import annotations

from asc.web.agent_store import AgentStore
from asc.web.agent_tools import AgentToolContext, apply_fix, execute_model_tool
from asc.web.tasks import TaskStore


def _pending_csv_plan(tmp_path):
    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    replay = {"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}}
    task_id = tasks.create("metadata", profile="myapp", replay=replay)
    session = agents.get_or_create_session(task_id, "myapp")
    ctx = AgentToolContext(tasks, agents, task_id, tmp_path, turn_seq=1, session_id=session["id"])
    proposed = execute_model_tool(ctx, "propose_fix", {
        "summary": "truncate keywords",
        "mutations": [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "zh-Hans",
            "fields": {"keywords": "new"},
            "before": {"keywords": "oldkeywords"},
        }],
        "rerun": {"task_id": task_id, "kind": "metadata"},
        "manual_steps": [],
    })
    return csv_path, tasks, agents, ctx, proposed["plan_id"]


def test_apply_fix_updates_csv_when_pending(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    csv_path, tasks, agents, ctx, plan_id = _pending_csv_plan(tmp_path)
    agents.promote_drafts(ctx.session_id, 1)
    result = apply_fix(ctx, plan_id)
    assert result["ok"] is True
    assert agents.get_plan(plan_id)["status"] == "applied"
    assert "new" in csv_path.read_text(encoding="utf-8")
    tasks.close()
    agents.close()


def test_apply_fix_draft_is_conflict(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    csv_path, tasks, agents, ctx, plan_id = _pending_csv_plan(tmp_path)
    before = csv_path.read_bytes()
    result = apply_fix(ctx, plan_id)
    assert result["ok"] is False
    assert result.get("code") == "conflict"
    assert csv_path.read_bytes() == before
    assert agents.get_plan(plan_id)["status"] == "draft"
    tasks.close()
    agents.close()


def test_apply_fix_before_mismatch_sets_apply_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    csv_path, tasks, agents, ctx, plan_id = _pending_csv_plan(tmp_path)
    agents.promote_drafts(ctx.session_id, 1)
    csv_path.write_text("locale,keywords\nzh-Hans,hand-edited\n", encoding="utf-8")
    result = apply_fix(ctx, plan_id)
    assert result["ok"] is False
    assert agents.get_plan(plan_id)["status"] == "apply_failed"
    assert "hand-edited" in csv_path.read_text(encoding="utf-8")
    tasks.close()
    agents.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_listing_local.py::test_rename_screenshot_stays_under_root tests/test_agent_apply.py -v`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Implement `rename_screenshot` and `apply_fix`. `apply_fix` must not call `rerun_task` (Task 9).

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_listing_local.py tests/test_agent_apply.py tests/test_agent_tools.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/listing/local.py src/asc/web/agent_tools.py tests/test_listing_local.py tests/test_agent_apply.py
git commit -m "feat(web): apply pending agent mutations with before-checks"
```

---

### Task 9: `rerun_task` from replay

**Files:**
- Create: `src/asc/web/agent_rerun.py`
- Modify: `src/asc/web/agent_tools.py` or keep rerun imported by routes only
- Test: `tests/test_agent_apply.py` (append)

**Interfaces:**
- Consumes: `TaskStore.get_replay`, existing `_start_*_task` functions / `start_background_task`
- Produces:
  - `def rerun_task(original_task_id: str, *, task_store: TaskStore) -> str`
    - missing replay → raise `RerunError("no_replay")` (or return `{"ok": False, "code": "no_replay"}`); **do not** create a task
    - dispatch on `replay["kind"]` to the same starter used by the original form (`_start_metadata_task`, `_start_build_task`, `_start_iap_task`, `_start_iap_review_screenshots_task`, `_start_whats_new_task`, `_start_whats_new_translate_task`, `_start_urls_task`, `_start_update_task`, `_start_listing_pull_screenshots_task`)
    - credentials always from `Config(app_name=replay["profile"])` at rerun time, never from replay
    - original task remains `error`
    - returns **new** task id
  - Unknown kind → `no_replay`-style error, no create

- [ ] **Step 1: Write the failing tests**

```python
def test_rerun_task_creates_new_id_and_keeps_old_error(tmp_path, monkeypatch):
    from asc.web.agent_rerun import rerun_task
    from asc.web.task_runner import sanitize_replay
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    replay = sanitize_replay("update", "system", False, {"version": "0.1.26", "branch": ""})
    old = store.create("update", profile="system", replay=replay)
    store.set_status(old, TaskStatus.ERROR)
    created = []

    def fake_start(store_arg, *, kind, profile, verbose, run, task_id=None, **kwargs):
        created.append((kind, profile, task_id))
        return task_id

    monkeypatch.setattr("asc.web.task_runner.start_background_task", fake_start)
    monkeypatch.setattr("asc.web.routes_api.start_background_task", fake_start)
    new_id = rerun_task(old, task_store=store)
    assert new_id != old
    assert store.get_state(old)["status"] in (TaskStatus.ERROR, "error")
    assert store.get_state(new_id) is not None
    store.close()


def test_rerun_without_replay_does_not_create(tmp_path):
    from asc.web.agent_rerun import RerunError, rerun_task
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    old = store.create("metadata", profile="myapp")  # no replay
    try:
        rerun_task(old, task_store=store)
        assert False, "expected RerunError"
    except RerunError as exc:
        assert "no_replay" in str(exc)
    assert len(store.list_recent_states(limit=10)) == 1
    store.close()
```

If wiring `_start_update_task` is awkward because it always calls `start_background_task`, patch that import in `agent_rerun` to observe a second `create`. The important assertions: new id, old stays error, no_replay creates nothing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_apply.py::test_rerun_task_creates_new_id_and_keeps_old_error tests/test_agent_apply.py::test_rerun_without_replay_does_not_create -v`

Expected: FAIL import error

- [ ] **Step 3: Write minimal implementation**

Map kind → starter. Reconstruct kwargs from `replay["params"]` + `replay["profile"]` + `replay["verbose"]`. Guard still runs inside starters (`enforce_config_guard`) — do not bypass.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_agent_apply.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/agent_rerun.py tests/test_agent_apply.py
git commit -m "feat(web): rerun failed tasks from sanitized replay"
```

---

### Task 10: WebAgent orchestrator (stream, tools, stop, drafts)

**Files:**
- Create: `src/asc/web/agent.py`
- Test: `tests/test_web_agent.py`

**Interfaces:**
- Consumes: `LLMClient.chat_stream`, `LLMHTTPError`, `execute_model_tool`, `OPENAI_TOOLS`, `AgentStore`, `redact_text`, `format_sse_event` (or yield `(event, data)` and let routes format)
- Produces:
  - `AGENT_TOOL_LOOP_MAX = 8`
  - `AGENT_TURN_TIMEOUT_SEC = 600`
  - `class WebAgent`
    - `request_stop(session_id: str) -> None`  # set threading.Event
    - `run_turn(*, session_id, task_id, message, auto_analyze, lang, llm_client) -> Iterator[tuple[str, str]]`
      - yields `(event_name, data_str)` where event_name ∈ {`session`, `token`, `tool_start`, `tool_result`, `error`, `stopped`, `done`}
      - `token` data is a **plain text fragment**, not JSON
      - `session` data JSON `{"session_id","task_id"}`
      - `tool_start` JSON `{"id","name"}`
      - `tool_result` JSON `{"id","name","ok","summary"}` (short redacted summary, not raw JSON dump)
      - `error` JSON `{"code","message"}` with i18n message
      - `done` JSON `{"session_id","plan_ids":[...]}` after `promote_drafts`
      - `stopped` JSON `{"session_id"}`
  - System prompt (fixed): answer in `lang`; explain this failure first; call `propose_fix` if locally fixable; otherwise manual steps only; never claim files were already changed or a task was rerun; never ask for or repeat secrets
  - Model messages: system + last 20 stored messages (tool results truncated to 2KiB) + this turn. Auto-analyze injects user content labeled with i18n `agent.auto_analyze_label` (zh: `请解释这次失败`) instructing `get_task` + `get_task_log` first
  - Persist user/assistant/tool messages **after redaction**
  - Tool loop: on `finish_reason=tool_calls`, stop forwarding tokens, execute **only** the six tools (accumulate streamed `tool_calls` by index), append tool JSON, continue. Cap 8 loops then finish with assistant text about tool limit; still `done` with any completed `propose_fix` plan ids
  - Hallucinated write tool: tool error string `writes are gated; use propose_fix`; continue; may `done`
  - Missing `llm_client` / no api_key: event `error` `code=llm_not_configured`; abandon drafts; no vendor HTTP
  - Retry `LLMHTTPError` 429 using `retry_after` or 1s, 5xx/timeout/disconnect wait 1s, max 3 attempts; then `llm_rate_limited` or `llm_unavailable`; abandon drafts; no `done`
  - Stop / generator exit / timeout: `stopped` or `error code=timeout`; abandon this turn's drafts; never apply/rerun
  - `propose_fix` inserts `draft`; only `done` calls `promote_drafts`. Incomplete tool (stop mid-call) is not inserted
  - `run_turn` without `task_id` and without existing `session_id` must not start (caller returns 400)

Helper for tests: a fake `llm_client` with `chat_stream` as a generator you control. Never construct a real `LLMClient` in these tests.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_agent.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from asc.web.agent_store import AgentStore
from asc.web.tasks import TaskStatus, TaskStore


class ScriptedLLM:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = 0
        self.messages_seen = []

    def chat_stream(self, messages, tools, temperature=0.3):
        self.calls += 1
        self.messages_seen.append(messages)
        for event in self.rounds.pop(0):
            yield event


def test_tool_call_pauses_then_forwards_tokens(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    task_id = tasks.create("metadata", profile="myapp")
    tasks.set_status(task_id, TaskStatus.ERROR)
    llm = ScriptedLLM([
        [
            {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "get_task", "arguments": "{\"task_id\":\"" + task_id + "\"}"}}]},
            {"finish_reason": "tool_calls"},
        ],
        [
            {"content": "failed at metadata"},
            {"finish_reason": "stop"},
        ],
    ])
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(agent.run_turn(
        session_id=None, task_id=task_id, message="", auto_analyze=True,
        lang="zh", llm_client=llm,
    ))
    names = [e[0] for e in events]
    assert names[0] == "session"
    assert "tool_start" in names
    assert "tool_result" in names
    assert "token" in names
    assert names[-1] == "done"
    assert llm.calls == 2
    tasks.close()
    agents.close()


def test_hallucinated_apply_does_not_create_task_or_write(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    csv_path = tmp_path / "a.csv"
    csv_path.write_text("locale,name\nen-US,A\n", encoding="utf-8")
    before = csv_path.read_bytes()
    task_id = tasks.create("metadata", profile="myapp")
    tasks.set_status(task_id, TaskStatus.ERROR)
    llm = ScriptedLLM([
        [
            {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "apply_fix", "arguments": "{}"}}]},
            {"finish_reason": "tool_calls"},
        ],
        [{"content": "cannot apply directly", "finish_reason": "stop"}],
    ])
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    list(agent.run_turn(session_id=None, task_id=task_id, message="fix", auto_analyze=False, lang="en", llm_client=llm))
    assert csv_path.read_bytes() == before
    assert len(tasks.list_recent_states(limit=20)) == 1
    tasks.close()
    agents.close()


def test_stop_abandons_draft_and_skips_done(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    replay = {
        "kind": "metadata",
        "profile": "myapp",
        "verbose": False,
        "params": {"csv_path": str(csv_path)},
    }
    task_id = tasks.create("metadata", profile="myapp", replay=replay)
    tasks.set_status(task_id, TaskStatus.ERROR)
    session = agents.get_or_create_session(task_id, "myapp")
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    args = {
        "summary": "truncate keywords",
        "mutations": [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "zh-Hans",
            "fields": {"keywords": "new"},
            "before": {"keywords": "oldkeywords"},
        }],
        "manual_steps": [],
    }

    class StopAfterPropose:
        def __init__(self) -> None:
            self.round = 0

        def chat_stream(self, messages, tools, temperature=0.3):
            self.round += 1
            if self.round == 1:
                yield {
                    "tool_calls": [{
                        "index": 0,
                        "id": "c1",
                        "function": {
                            "name": "propose_fix",
                            "arguments": __import__("json").dumps(args),
                        },
                    }]
                }
                yield {"finish_reason": "tool_calls"}
                return
            agent.request_stop(session["id"])
            yield {"content": "should not promote"}
            yield {"finish_reason": "stop"}

    events = list(agent.run_turn(
        session_id=session["id"],
        task_id=task_id,
        message="hi",
        auto_analyze=False,
        lang="zh",
        llm_client=StopAfterPropose(),
    ))
    assert any(name == "stopped" for name, _ in events)
    assert all(name != "done" for name, _ in events)
    plans = agents.list_plans(session["id"])
    assert plans
    assert all(plan["status"] == "abandoned" for plan in plans)
    assert csv_path.read_text(encoding="utf-8") == "locale,keywords\nzh-Hans,oldkeywords\n"
    assert agents.claim_pending(plans[0]["id"]) is None
    tasks.close()
    agents.close()


def test_missing_llm_does_not_construct_http_client(tmp_path):
    from asc.web.agent import WebAgent

    tasks = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    task_id = tasks.create("iap", profile="myapp")
    tasks.set_status(task_id, TaskStatus.ERROR)
    agent = WebAgent(agent_store=agents, task_store=tasks, project_root=tmp_path)
    events = list(agent.run_turn(
        session_id=None, task_id=task_id, message="", auto_analyze=True,
        lang="zh", llm_client=None,
    ))
    assert events[-1][0] == "error"
    assert "llm_not_configured" in events[-1][1]
    tasks.close()
    agents.close()
```

Also add `test_redacted_logs_never_reach_llm_messages` that appends a PEM log line, scripts `get_task_log` then a stop round, and asserts `"BEGIN PRIVATE KEY"` / key material not in `llm.messages_seen`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_agent.py -v`

Expected: FAIL import error

- [ ] **Step 3: Write minimal implementation**

Implement `WebAgent.run_turn` as a sync generator. Check the stop Event between chunks and before each tool. On any non-`done` exit path call `abandon_drafts(session_id, turn_seq)`.

Accumulate tool_calls:

```python
buckets: dict[int, dict] = {}
for delta in tool_calls_delta:
    idx = int(delta.get("index") or 0)
    slot = buckets.setdefault(idx, {"id": "", "name": "", "arguments": ""})
    if delta.get("id"):
        slot["id"] = delta["id"]
    fn = delta.get("function") or {}
    if fn.get("name"):
        slot["name"] = fn["name"]
    if fn.get("arguments"):
        slot["arguments"] += fn["arguments"]
```

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_web_agent.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/agent.py tests/test_web_agent.py
git commit -m "feat(web): stream agent turns with gated tool loop"
```

---

### Task 11: HTTP routes

**Files:**
- Create: `src/asc/web/routes_agent.py`
- Modify: `src/asc/web/server.py` — `app.include_router(routes_agent.router, prefix="/api/agent")`
- Modify: `src/asc/web/locales/zh.json`, `src/asc/web/locales/en.json` (error strings used by routes)
- Test: `tests/test_web_agent_routes.py`

**Interfaces:**
- Consumes: `WebAgent`, `AgentStore`, `apply_fix`, `rerun_task`, `format_sse_event`
- Produces (all under `/api/agent`):

| method | path | behavior |
|--------|------|----------|
| POST | `/stream` | body `{session_id?, task_id?, message?, auto_analyze}` → `text/event-stream`; heartbeat `: heartbeat\n\n` ~3s; 10 min absolute timeout; no `task_id` and no `session_id` → 400; `task_id` present does not require cookie profile |
| POST | `/stop` | `{session_id}` → `request_stop`; 200 |
| GET | `/failed-tasks` | query `q`, `kind`; cookie profile only for sort; **only** `status=error`; limit 50 |
| GET | `/sessions?task_id=` | existing session + messages + pending plans |
| GET | `/plans/{plan_id}` | JSON always includes `status` |
| POST | `/apply` | `{plan_id, rerun: bool}` — only `pending`; then `apply_fix`; `rerun=true` only if plan has `rerun` **and** apply succeeded; empty mutations → 400; draft/abandoned/applied/rejected/apply_failed → 409; concurrent second apply → 409 |
| POST | `/reject` | `{plan_id}` pending→rejected else 409 |

SSE event names allowed: `session`, `token`, `tool_start`, `tool_result`, `error`, `stopped`, `done` only.

Do not change `GET /api/task/{task_id}/stream`.

Resolve LLM via `Config().get_active_llm_config()`. If missing/`api_key` empty, pass `llm_client=None` (do not instantiate `LLMClient`).

Apply response success: `{ok: true, status, new_task_id?}`. Rerun failure after successful mutations: `{ok: true, status: "applied", rerun_error: "..."}` — plan stays `applied`.

Heartbeat implementation: producer thread puts frames on `queue.Queue`; generator `get(timeout=3)` yields `: heartbeat\n\n` on empty; stop on sentinel; 600s deadline yields `error` timeout then abandon.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_agent_routes.py
from __future__ import annotations

from fastapi.testclient import TestClient
from unittest.mock import patch

from asc.web.server import create_app
from asc.web.tasks import TaskStatus, TaskStore


def test_agent_stream_is_sse_and_task_stream_still_exists(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr("asc.web.tasks.task_store", store)
    monkeypatch.setattr("asc.web.routes_api._task_store", store)
    monkeypatch.setattr("asc.web.server.task_store", store)
    task_id = store.create("metadata", profile="myapp")
    store.set_status(task_id, TaskStatus.ERROR)

    def fake_turn(**kwargs):
        yield ("session", '{"session_id":"s1","task_id":"%s"}' % task_id)
        yield ("token", "hello")
        yield ("done", '{"session_id":"s1","plan_ids":[]}')

    monkeypatch.setattr("asc.web.agent.WebAgent.run_turn", lambda self, **k: fake_turn())
    monkeypatch.setattr("asc.config.Config.get_active_llm_config", lambda self: {"api_key": "k", "base_url": "http://x", "model": "m"})
    client = TestClient(create_app())
    resp = client.post("/api/agent/stream", json={"task_id": task_id, "auto_analyze": True, "message": ""})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    for name in ("session", "token", "done"):
        assert f"event: {name}" in body
    assert "event: log" not in body
    task_stream = client.get(f"/api/task/{task_id}/stream")
    assert task_stream.status_code == 200
    store.close()


def test_failed_tasks_excludes_canceled_and_done(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr("asc.web.tasks.task_store", store)
    monkeypatch.setattr("asc.web.server.task_store", store)
    e = store.create("iap", profile="a")
    store.set_status(e, TaskStatus.ERROR)
    d = store.create("iap", profile="a")
    store.set_status(d, TaskStatus.DONE)
    c = store.create("iap", profile="a")
    store.set_status(c, TaskStatus.CANCELED)
    client = TestClient(create_app())
    rows = client.get("/api/agent/failed-tasks").json()["tasks"]
    ids = [row["id"] for row in rows]
    assert e in ids
    assert d not in ids
    assert c not in ids
    store.close()


def test_apply_draft_conflict_and_pending_success(tmp_path, monkeypatch):
    from asc.web.agent_store import AgentStore
    from asc.web.server import create_app

    store = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    monkeypatch.setattr("asc.web.tasks.task_store", store)
    monkeypatch.setattr("asc.web.server.task_store", store)
    monkeypatch.setattr("asc.web.agent_store.agent_store", agents)
    monkeypatch.setattr("asc.web.routes_agent.agent_store", agents)
    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    task_id = store.create(
        "metadata",
        profile="myapp",
        replay={"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}},
    )
    session = agents.get_or_create_session(task_id, "myapp")
    plan_id = agents.insert_plan_draft(
        session["id"],
        1,
        "fix",
        [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "zh-Hans",
            "fields": {"keywords": "new"},
            "before": {"keywords": "oldkeywords"},
        }],
        {"task_id": task_id, "kind": "metadata"},
        [],
    )
    client = TestClient(create_app())
    shown = client.get(f"/api/agent/plans/{plan_id}").json()
    assert shown["status"] == "draft"
    assert client.post("/api/agent/apply", json={"plan_id": plan_id, "rerun": False}).status_code == 409
    empty_id = agents.insert_plan_draft(session["id"], 1, "manual", [], None, ["do it yourself"])
    agents.promote_drafts(session["id"], 1)
    assert client.post("/api/agent/apply", json={"plan_id": empty_id, "rerun": False}).status_code == 400
    ok = client.post("/api/agent/apply", json={"plan_id": plan_id, "rerun": False})
    assert ok.status_code == 200
    assert "new" in csv_path.read_text(encoding="utf-8")
    store.close()
    agents.close()


def test_concurrent_apply_one_409(tmp_path, monkeypatch):
    import threading
    from asc.web.agent_store import AgentStore
    from asc.web.server import create_app

    store = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    monkeypatch.setattr("asc.web.tasks.task_store", store)
    monkeypatch.setattr("asc.web.server.task_store", store)
    monkeypatch.setattr("asc.web.agent_store.agent_store", agents)
    monkeypatch.setattr("asc.web.routes_agent.agent_store", agents)
    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    task_id = store.create(
        "metadata",
        profile="myapp",
        replay={"kind": "metadata", "profile": "myapp", "verbose": False, "params": {"csv_path": str(csv_path)}},
    )
    session = agents.get_or_create_session(task_id, "myapp")
    plan_id = agents.insert_plan_draft(
        session["id"],
        1,
        "fix",
        [{
            "op": "csv_set_fields",
            "path": str(csv_path),
            "locale": "zh-Hans",
            "fields": {"keywords": "new"},
            "before": {"keywords": "oldkeywords"},
        }],
        None,
        [],
    )
    agents.promote_drafts(session["id"], 1)
    client = TestClient(create_app())
    codes: list[int] = []

    def _post():
        codes.append(client.post("/api/agent/apply", json={"plan_id": plan_id, "rerun": False}).status_code)

    t1 = threading.Thread(target=_post)
    t2 = threading.Thread(target=_post)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert sorted(codes) == [200, 409]
    store.close()
    agents.close()
```

Also: `POST /stream` `{}` → 400; `GET /plans/{id}` includes `status`; reject non-pending → 409.

Also: `POST /stream` `{}` → 400; `GET /plans/{id}` includes `status`; reject non-pending → 409.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_agent_routes.py -v`

Expected: FAIL 404 on `/api/agent/stream`

- [ ] **Step 3: Write minimal implementation**

`APIRouter()` in `routes_agent.py`. Include from `create_app()`. Use `format_sse_event` for frames (multiline token text must split `data:` lines — already handled).

i18n keys (add both catalogs):

```json
"agent.error.llm_not_configured": "未配置 LLM，请到设置页添加 API Key",
"agent.error.llm_rate_limited": "LLM 请求过于频繁，请稍后重试",
"agent.error.llm_unavailable": "LLM 服务暂不可用，请稍后重试",
"agent.error.timeout": "本轮分析超时，未写入任何文件",
"agent.error.tool_limit": "本轮工具次数已用尽，请再问一次",
"agent.auto_analyze_label": "请解释这次失败"
```

English catalog must have the same keys.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_web_agent_routes.py tests/test_web_sse.py tests/test_web_server.py::test_homepage_returns_200 -v`

Expected: PASS; task log SSE tests still pass

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/routes_agent.py src/asc/web/server.py src/asc/web/locales/zh.json src/asc/web/locales/en.json tests/test_web_agent_routes.py
git commit -m "feat(web): add /api/agent SSE and gated apply routes"
```

---

### Task 12: Dock tabs, sidebar Agent, i18n markup

**Files:**
- Modify: `src/asc/web/templates/_task_log_drawer.html`
- Modify: `src/asc/web/templates/base.html`
- Modify: `src/asc/web/static/task-log-drawer.css`
- Modify: `src/asc/web/locales/zh.json`, `src/asc/web/locales/en.json`
- Modify: `src/asc/web/static/task-log-drawer.js` (tab switching only; stream UI in Task 13 may already hook data attributes)
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: existing `#task-log-drawer` / `#task-log-dock` (width ~390px, overlay unchanged)
- Produces markup contracts:
  - Tabs: `data-task-log-tab="logs"` and `data-task-log-tab="agent"`
  - Sidebar: `<button type="button" data-open-agent-dock>` between dashboard and metadata; **no** `href="/agent"` in primary nav
  - Explain buttons: `data-open-agent-task` plus `data-task-id` (logs toolbar + dashboard later)
  - Agent panel: `data-agent-stream`, `data-agent-stop`, `data-agent-messages`, `data-agent-task-search`
  - Logs EventSource is not destroyed on tab switch (pause follow only)
  - Default tab: logs when opened from log buttons; agent when opened from sidebar / explain
  - Closing dock (X, Escape, overlay outside click) does not delete sessions or apply plans
  - Pressed style on sidebar Agent when dock is open on the Agent tab (`aria-pressed` / class `active` without treating it as a route)

Locale keys (both files):

```json
"nav.agent": "Agent",
"drawer.tab_logs": "日志",
"drawer.tab_agent": "Agent",
"drawer.explain_with_agent": "去 Agent 解释",
"agent.search_placeholder": "搜索失败任务（kind 或 id）",
"agent.empty": "选择一个失败任务开始分析",
"agent.stop": "停止",
"agent.send": "发送",
"agent.apply": "应用",
"agent.ignore": "忽略",
"agent.rerun_after_apply": "应用后重跑",
"agent.tool_running": "正在读取任务日志",
"agent.applying": "正在应用",
"agent.applied": "已应用",
"agent.apply_failed": "应用失败",
"agent.rejected": "已忽略"
```

English: `Logs` / `Agent` / `Explain with Agent` / matching strings.

Drawer HTML sketch (keep existing log controls inside the logs panel):

```html
<header>
  ...
  <div class="task-log-tabs" role="tablist">
    <button type="button" role="tab" data-task-log-tab="logs">{{ t("drawer.tab_logs") }}</button>
    <button type="button" role="tab" data-task-log-tab="agent">{{ t("drawer.tab_agent") }}</button>
  </div>
  <button data-task-log-close>...</button>
</header>
<section data-task-log-panel="logs">
  <!-- existing tools + pre + footer -->
  <button type="button" data-open-agent-task hidden>{{ t("drawer.explain_with_agent") }}</button>
</section>
<section data-task-log-panel="agent" hidden>
  <input data-agent-task-search>
  <div data-agent-messages></div>
  <button type="button" data-agent-stop hidden>{{ t("agent.stop") }}</button>
  <form data-agent-stream>...</form>
</section>
```

`TaskLogDrawer.open(taskId, { tab: "logs"|"agent" })`. Sidebar does not require a taskId: open dock + agent tab + empty state (no `/api/agent/stream`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_server.py`:

```python
def test_task_log_drawer_exposes_logs_and_agent_tabs(client):
    resp = client.get("/")
    assert 'data-task-log-tab="logs"' in resp.text
    assert 'data-task-log-tab="agent"' in resp.text
    assert "data-agent-stream" in resp.text
    assert "data-agent-stop" in resp.text
    assert "data-agent-messages" in resp.text
    assert "data-agent-task-search" in resp.text
    assert "data-open-agent-task" in resp.text


def test_sidebar_agent_is_button_not_route(client):
    resp = client.get("/")
    assert "data-open-agent-dock" in resp.text
    assert 'href="/agent"' not in resp.text


def test_no_standalone_agent_page(client):
    assert client.get("/agent").status_code in {404, 405}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_server.py::test_task_log_drawer_exposes_logs_and_agent_tabs tests/test_web_server.py::test_sidebar_agent_is_button_not_route tests/test_web_server.py::test_no_standalone_agent_page -v`

Expected: FAIL missing attributes

- [ ] **Step 3: Write minimal implementation**

Update templates, locales, CSS (`grid-template-rows` must include the agent section; hide inactive panel with `[hidden]`). JS: tab buttons, `open` options.tab, show explain button when current task `status===error` (status already streamed as `error_event`). Do not load `agent-dock.js` logic yet beyond data attributes if Task 13 owns streaming — but include the script tag in `base.html` now pointing at a stub file that Task 13 fills, **or** create an empty IIFE in Task 13 only. Prefer adding the empty `agent-dock.js` here so the script tag can be asserted:

```javascript
(function () { window.AscAgentDock = { start: function () {} }; })();
```

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_web_server.py -v`

Expected: PASS (existing drawer contracts still hold: `id="task-log-drawer"`, EventSource in `task-log-drawer.js`, not in `dashboard.js`)

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/templates/_task_log_drawer.html src/asc/web/templates/base.html src/asc/web/static/task-log-drawer.css src/asc/web/static/task-log-drawer.js src/asc/web/static/agent-dock.js src/asc/web/locales/zh.json src/asc/web/locales/en.json tests/test_web_server.py
git commit -m "feat(web): add Agent tab and sidebar dock entry"
```

---

### Task 13: Agent dock JS, dashboard explain, apply cards

**Files:**
- Modify: `src/asc/web/static/agent-dock.js`
- Modify: `src/asc/web/static/task-log-drawer.js`
- Modify: `src/asc/web/static/dashboard.js`
- Test: `tests/test_web_server.py` (string contracts; no browser E2E)

**Interfaces:**
- Consumes: `/api/agent/stream|stop|apply|reject|failed-tasks|sessions|plans/{id}`
- Produces JS behavior (assert via source strings):
  - `fetch("/api/agent/stream"` with POST JSON (not `EventSource` for agent)
  - Parse `event:` / `data:` frames from `ReadableStream`
  - Append `token` to the current assistant bubble
  - On `tool_start` show a short status row (no raw tool JSON)
  - Show Stop while generating; Stop calls `POST /api/agent/stop` and aborts fetch
  - Render apply/ignore **only after** `done` and `plan_ids.length`; then `GET /api/agent/plans/{id}`; skip cards for `draft`/`abandoned`; hide Apply when `mutations` empty
  - Apply → `POST /api/agent/apply` `{plan_id, rerun}`; checkbox `应用后重跑` default checked when plan has `rerun`
  - Success + new_task_id → `TaskLogDrawer.open(newTaskId, {tab: "logs"})`
  - Ignore → `POST /api/agent/reject`
  - Aborting fetch (close dock / navigation) treated as stop
  - Sidebar `data-open-agent-dock`: open dock, agent tab, **no** auto stream
  - `data-open-agent-task`: bind task, load session; if no user/assistant messages, POST `auto_analyze: true`
  - Failed-task search hits `GET /api/agent/failed-tasks`
  - Dashboard: `makeExplainButton(task)` only when `task.status === "error"`; `dataset.openAgentTask` / `data-open-agent-task` and `data-task-id`
  - Closing dock does not call apply

- [ ] **Step 1: Write the failing tests**

```python
def test_agent_dock_javascript_uses_post_stream_not_event_source(client):
    js = client.get("/static/agent-dock.js").text
    assert 'fetch("/api/agent/stream"' in js or "fetch('/api/agent/stream'" in js
    assert "/api/agent/stop" in js
    assert "/api/agent/apply" in js
    assert "/api/agent/reject" in js
    assert "/api/agent/failed-tasks" in js
    assert "/api/agent/plans/" in js
    assert "auto_analyze" in js
    assert "plan_ids" in js
    assert "TaskLogDrawer.open" in js
    assert "ReadableStream" in js or "getReader" in js
    assert "EventSource" not in js


def test_dashboard_javascript_adds_explain_on_error_rows(client):
    js = client.get("/static/dashboard.js").text
    assert "data-open-agent-task" in js or "openAgentTask" in js
    assert 'task.status === "error"' in js or 'task.status==="error"' in js
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_server.py::test_agent_dock_javascript_uses_post_stream_not_event_source tests/test_web_server.py::test_dashboard_javascript_adds_explain_on_error_rows -v`

Expected: FAIL missing strings

- [ ] **Step 3: Write minimal implementation**

Implement `agent-dock.js` as an IIFE. Parse SSE:

```javascript
function parseSseChunk(buffer) {
  var parts = buffer.split("\n\n");
  var rest = parts.pop();
  var events = [];
  parts.forEach(function (block) {
    var name = "message";
    var data = [];
    block.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) name = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) data.push(line.slice(5).replace(/^ /, ""));
    });
    events.push({ event: name, data: data.join("\n") });
  });
  return { events: events, rest: rest };
}
```

Do not create Apply buttons in the `token` handler.

Dashboard `renderHistory`: after `makeLogButton`, if error, append explain button. Include it in `captureTaskFocus` / restore with action `"explain"`.

- [ ] **Step 4: Run tests and make sure they pass**

Run: `pytest tests/test_web_server.py tests/test_web_i18n.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/asc/web/static/agent-dock.js src/asc/web/static/task-log-drawer.js src/asc/web/static/dashboard.js tests/test_web_server.py
git commit -m "feat(web): stream agent replies and confirm fix cards"
```

---

### Task 14: Success-criteria regressions

**Files:**
- Create: `tests/test_cli_no_agent.py`
- Modify: `tests/test_whats_new_translate.py` or `tests/test_translator.py` only if needed to lock `chat()` (prefer a small assertion in `tests/test_llm.py` already added in Task 2)
- Test: `tests/test_cli_no_agent.py`, `tests/test_llm.py`, `tests/test_web_agent.py`, `tests/test_web_agent_routes.py`

**Interfaces:**
- Consumes: finished feature
- Produces: locks spec §14

- [ ] **Step 1: Write the failing tests if missing**

```python
# tests/test_cli_no_agent.py
from typer.testing import CliRunner
from asc.cli import app

def test_help_has_no_agent_command():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "agent" not in result.output.lower().split()
    # also ensure no `asc agent` typer group
    listed = result.output.lower()
    assert "  agent " not in listed
```

Keep `test_chat_still_sends_json_object_without_tools` from Task 2.

Add `tests/test_web_agent.py::test_done_promotes_draft_then_apply_writes_csv` if not already covered: script LLM to call `propose_fix`, assert file unchanged until `apply_fix` after promote.

- [ ] **Step 2: Run the regression set**

Run: `pytest tests/test_cli_no_agent.py tests/test_llm.py tests/test_web_agent.py tests/test_web_agent_routes.py tests/test_agent_apply.py tests/test_agent_tools.py tests/test_agent_redact.py tests/test_web_task_replay.py tests/test_web_server.py -v`

Expected: PASS with no real network (requests_mock / ScriptedLLM only)

- [ ] **Step 3: Fix any gaps from the self-check below, then commit**

```bash
git add tests/test_cli_no_agent.py
git commit -m "test: lock agent gating, CLI surface, and translator chat()"
```

---

## Self-review

### Spec coverage

| Spec section | Task |
|--------------|------|
| §3 goals / non-goals (no CLI agent, no Anthropic, no auto-apply, translator unchanged) | 2, 11, 14 |
| §5 all Web kinds + screenshot-vs-metadata via logs | 5, 6, 10 |
| §6 UI dock tabs, sidebar button, explain entries, search, cards after `done` | 12, 13 |
| §7 `chat_stream` vs `chat()` | 2 |
| §8 SSE events, tool loop, stop, heartbeat, 10 min | 10, 11 |
| §9 tools, allow-list, propose_fix ops, apply/rerun, replay | 4–9 |
| §9.5 write gating | 6, 7, 8, 10, 11 |
| §10 modules / AgentStore path / auto first turn | 3, 10, 11, 13 |
| §12 errors | 10, 11 |
| §13 tests (mock LLM, markup) | all test files |
| §14 success criteria | 14 |

### Placeholder scan

No TBD / "handle edge cases" / "similar to Task N" leftovers. Types named in later tasks (`sanitize_replay`, `claim_pending`, `run_turn`, `apply_fix`, `rerun_task`, `LLMHTTPError`) are defined in earlier **Produces** blocks.

### Type consistency

- `chat_stream(messages, tools, temperature=0.3) -> Iterator[dict]`
- Plan statuses: `draft|pending|applying|applied|rejected|abandoned|apply_failed`
- Public task: `has_replay: bool` only
- SSE agent events: `session|token|tool_start|tool_result|error|stopped|done`
- Apply body: `{plan_id, rerun: bool}`
