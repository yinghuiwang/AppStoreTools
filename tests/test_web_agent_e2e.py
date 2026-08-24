"""Browser E2E for the Web Failure Agent right rail (Chromium + local FastAPI).

Requires the ``playwright`` extra and a local Chromium install. Missing
browsers skip instead of failing CI:

    python -m pip install -e ".[dev]"
    python -m playwright install chromium
    pytest tests/test_web_agent_e2e.py
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Page, expect

from asc.web.agent_store import AgentStore
from asc.web.server import create_app
from asc.web.tasks import TaskStatus, TaskStore
from tests.test_web_agent import ScriptedLLM

pytestmark = [pytest.mark.e2e, pytest.mark.skip(reason="待 SPA e2e")]

TOKEN_STREAM = "E2E_TOKEN_STREAM_OK"
TOKEN_MD = "E2E_MD **bold** and `code`"
TOKEN_MUTATIONS = "E2E_TOKEN_CONFIRM_MUTATIONS"
TOKEN_EMPTY = "E2E_TOKEN_MANUAL_ONLY"
TOKEN_BLOCKING = "E2E_TOKEN_BLOCKING"
PLAN_MUTATIONS = "E2E_PLAN_WITH_MUTATIONS"
PLAN_EMPTY = "E2E_MANUAL_ONLY_PLAN"


@dataclass
class LLMHolder:
    """Process-local stand-in for ``LLMClient``; never talks to a vendor."""

    impl: object = field(default_factory=lambda: ScriptedLLM([[
        {"content": "ok", "finish_reason": "stop"},
    ]]))
    calls: int = 0

    def chat_stream(self, messages, tools, temperature=0.3):
        self.calls += 1
        yield from self.impl.chat_stream(messages, tools, temperature=temperature)


class HoldAfterContentLLM:
    """Split content and finish so the UI can be observed before ``done``."""

    def __init__(
        self,
        rounds,
        after_content: threading.Event,
        resume: threading.Event,
    ) -> None:
        self.rounds = list(rounds)
        self.after_content = after_content
        self.resume = resume

    def chat_stream(self, messages, tools, temperature=0.3):
        events = list(self.rounds.pop(0))
        for event in events:
            content = event.get("content")
            finish = event.get("finish_reason")
            rest = {
                key: value
                for key, value in event.items()
                if key not in {"content", "finish_reason"}
            }
            if content:
                yield {"content": content, **rest}
                rest = {}
                self.after_content.set()
                self.resume.wait(timeout=10)
            if finish or rest:
                out = dict(rest)
                if finish:
                    out["finish_reason"] = finish
                yield out


class BlockingLLM:
    """Hold the stream open after the first token until ``release`` is set."""

    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release

    def chat_stream(self, messages, tools, temperature=0.3):
        yield {"content": TOKEN_BLOCKING}
        self.started.set()
        self.release.wait(timeout=15)
        yield {"finish_reason": "stop"}


@dataclass
class AgentE2E:
    base_url: str
    page: Page
    tasks: TaskStore
    agents: AgentStore
    llm: LLMHolder
    tmp_path: Path
    csv_path: Path
    task_id: str
    spies: dict[str, list]
    page_errors: list[str]


def _csv_mutation(csv_rel: str) -> dict:
    return {
        "op": "csv_set_fields",
        "path": csv_rel,
        "locale": "zh-Hans",
        "fields": {"keywords": "new"},
        "before": {"keywords": "oldkeywords"},
    }


def _propose_rounds(
    task_id: str,
    csv_rel: str,
    *,
    mutations: list,
    summary: str,
    token: str,
    rerun: bool = True,
    manual_steps: list | None = None,
) -> list:
    args: dict = {
        "summary": summary,
        "mutations": mutations,
        "manual_steps": manual_steps or [],
    }
    if rerun and mutations:
        args["rerun"] = {"task_id": task_id, "kind": "metadata"}
    return [
        [
            {
                "tool_calls": [{
                    "index": 0,
                    "id": "c1",
                    "function": {
                        "name": "propose_fix",
                        "arguments": json.dumps(args),
                    },
                }]
            },
            {"finish_reason": "tool_calls"},
        ],
        [{"content": token, "finish_reason": "stop"}],
    ]


def _wait_http(url: str, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=0.5)
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(0.05)
    raise RuntimeError(f"uvicorn did not become ready at {url}: {last_error}")


def _isolate_stores(monkeypatch, store: TaskStore, agents: AgentStore) -> None:
    monkeypatch.setattr("asc.web.tasks.task_store", store)
    monkeypatch.setattr("asc.web.server.task_store", store)
    monkeypatch.setattr("asc.web.routes_api._task_store", store)
    monkeypatch.setattr("asc.web.routes_listing.task_store", store)
    monkeypatch.setattr("asc.web.agent_store.agent_store", agents)
    monkeypatch.setattr("asc.web.routes_agent.agent_store", agents)
    monkeypatch.setattr("asc.web.server.agent_store", agents)


def _goto_ready(page: Page, path: str = "/") -> None:
    page.goto(path, wait_until="domcontentloaded")
    page.wait_for_function("() => window.TaskLogDrawer && window.AscAgentDock && window.t")


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


def _confirm_apply(page: Page, card) -> None:
    card.get_by_role("button", name="应用", exact=True).click()
    page.get_by_role("button", name="确认应用", exact=True).click()


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


@pytest.fixture(scope="module")
def chromium_browser():
    from playwright.sync_api import sync_playwright

    try:
        playwright = sync_playwright().start()
    except Exception as exc:  # pragma: no cover - environment
        pytest.skip(f"Playwright failed to start: {exc}")
    try:
        browser = playwright.chromium.launch(headless=True)
    except Exception as exc:
        playwright.stop()
        pytest.skip(
            "Playwright Chromium is not installed "
            f"({exc}). Run: python -m playwright install chromium"
        )
    yield browser
    browser.close()
    playwright.stop()


@pytest.fixture
def agent_ui(chromium_browser, tmp_path, monkeypatch):
    import uvicorn
    from asc.web.agent import WebAgent

    monkeypatch.setenv("ASC_GUARD_DISABLE", "1")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    csv_path = tmp_path / "app.csv"
    csv_path.write_text("locale,keywords\nzh-Hans,oldkeywords\n", encoding="utf-8")
    replay = {
        "kind": "metadata",
        "profile": "myapp",
        "verbose": False,
        "params": {"csv_path": "app.csv"},
    }
    store = TaskStore(tmp_path / "tasks.db")
    agents = AgentStore(tmp_path / "agent.db")
    task_id = store.create("metadata", profile="myapp", replay=replay)
    store.append_log(task_id, "ERROR: keywords exceed 100 bytes")
    store.set_status(task_id, TaskStatus.ERROR)

    llm = LLMHolder()
    _isolate_stores(monkeypatch, store, agents)
    monkeypatch.setattr(
        "asc.web.routes_agent._llm_client_or_none",
        lambda: llm,
    )
    monkeypatch.setattr(
        "asc.web.routes_agent._web_agent",
        lambda: WebAgent(agent_store=agents, task_store=store, project_root=tmp_path),
    )

    def fake_rerun(original_task_id, *, task_store):
        return task_store.create("metadata", profile="myapp")

    monkeypatch.setattr("asc.web.agent_rerun.rerun_task", fake_rerun)

    app = create_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        log_level="error",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        pytest.fail("uvicorn did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    _wait_http(base_url + "/")

    context = chromium_browser.new_context(
        base_url=base_url,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
        extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9"},
    )
    context.add_cookies([{
        "name": "asc_lang",
        "value": "zh",
        "url": base_url,
    }])
    page = context.new_page()
    spies = {"stream": [], "apply": [], "stop": [], "reject": []}
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    def on_request(request):
        if request.method != "POST":
            return
        url = request.url
        body = request.post_data or ""
        if "/api/agent/agui" in url or "/api/agent/stream" in url:
            spies["stream"].append(body)
        elif "/api/agent/apply" in url:
            spies["apply"].append(body)
        elif "/api/agent/stop" in url:
            spies["stop"].append(body)
        elif "/api/agent/reject" in url:
            spies["reject"].append(body)

    page.on("request", on_request)
    env = AgentE2E(
        base_url=base_url,
        page=page,
        tasks=store,
        agents=agents,
        llm=llm,
        tmp_path=tmp_path,
        csv_path=csv_path,
        task_id=task_id,
        spies=spies,
        page_errors=page_errors,
    )
    try:
        yield env
    finally:
        context.close()
        server.should_exit = True
        thread.join(timeout=8)
        store.close()
        agents.close()


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


def test_composer_plus_menu_and_header_have_no_top_search(agent_ui: AgentE2E):
    page = agent_ui.page
    _goto_ready(page)
    page.locator("[data-agent-toggle]").click()
    _expect_agent_open(page)
    expect(page.locator(".agent-dock-toolbar [data-agent-task-search]")).to_have_count(0)
    expect(page.locator("[data-agent-title]")).to_be_visible()
    expect(page.locator("[data-agent-attach]")).to_be_visible()
    expect(page.locator("[data-agent-attach-menu]")).to_be_hidden()
    page.locator("[data-agent-attach]").click()
    expect(page.locator("[data-agent-attach-menu]")).to_be_visible()
    expect(page.locator("[data-agent-attach-menu] [data-agent-task-search]")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("[data-agent-attach-menu]")).to_be_hidden()
    page.locator("[data-agent-attach]").click()
    expect(page.locator("[data-agent-attach-menu]")).to_be_visible()
    page.locator("main").click(position={"x": 24, "y": 24}, force=True)
    expect(page.locator("[data-agent-attach-menu]")).to_be_hidden()
    page.locator("[data-agent-close]").click()
    _expect_agent_closed(page)


def test_free_chat_streams_without_binding_a_task(agent_ui: AgentE2E):
    agent_ui.llm.impl = ScriptedLLM([[
        {"content": TOKEN_STREAM, "finish_reason": "stop"},
    ]])
    page = agent_ui.page
    _goto_ready(page)
    page.locator("[data-agent-toggle]").click()
    _expect_agent_open(page)
    page.locator("[data-agent-stream] [name=message]").fill("hello free chat")
    page.locator("[data-agent-stream]").evaluate("form => form.requestSubmit()")
    expect(page.locator(".agent-msg--user")).to_contain_text("hello free chat")
    expect(page.locator(".agent-msg--assistant")).to_contain_text(TOKEN_STREAM)
    assert agent_ui.spies["stream"]
    body = json.loads(agent_ui.spies["stream"][0])
    assert not body.get("task_id")
    assert body.get("auto_analyze") is False
    assert body["message"] == "hello free chat"
    state = page.evaluate("() => window.AscAgentDock.getState()")
    assert state["sessionId"]
    assert not state["boundTaskId"]
    agent_ui.llm.impl = ScriptedLLM([[
        {"content": "follow-up-ok", "finish_reason": "stop"},
    ]])
    page.locator("[data-agent-stream] [name=message]").fill("second")
    page.locator("[data-agent-stream]").evaluate("form => form.requestSubmit()")
    expect(page.locator(".agent-msg--assistant").nth(1)).to_contain_text("follow-up-ok")
    body2 = json.loads(agent_ui.spies["stream"][1])
    assert body2.get("session_id") == state["sessionId"]
    assert not body2.get("task_id")
    assert body2.get("auto_analyze") is False


def test_plus_menu_can_bind_failed_task(agent_ui: AgentE2E):
    agent_ui.llm.impl = ScriptedLLM([[
        {"content": TOKEN_STREAM, "finish_reason": "stop"},
    ]])
    page = agent_ui.page
    _goto_ready(page)
    page.locator("[data-agent-toggle]").click()
    _expect_agent_open(page)
    page.locator("[data-agent-attach]").click()
    results = page.locator("[data-agent-search-results] button")
    expect(results.first).to_be_visible()
    results.first.click()
    expect(page.locator("[data-agent-attach-menu]")).to_be_hidden()
    expect(page.locator("[data-agent-bound]")).to_contain_text(agent_ui.task_id[:8])
    expect(page.locator(".agent-msg--assistant")).to_contain_text(TOKEN_STREAM)
    body = json.loads(agent_ui.spies["stream"][0])
    assert body.get("task_id") == agent_ui.task_id
    assert body.get("auto_analyze") is True


def test_agent_panel_drag_resizes_and_persists(agent_ui: AgentE2E):
    page = agent_ui.page
    _goto_ready(page)
    page.locator("[data-agent-toggle]").click()
    _expect_agent_open(page)
    panel = page.locator("[data-agent-panel]")
    handle = page.locator("[data-agent-resize]")
    expect(handle).to_be_visible()
    grip = handle.locator(".agent-panel__resize-grip")
    expect(grip).to_be_visible()
    before = panel.evaluate("el => el.getBoundingClientRect().width")
    handle.hover()
    box = handle.bounding_box()
    assert box
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + min(40, box["height"] / 2))
    page.mouse.down()
    page.mouse.move(box["x"] - 80, box["y"] + min(40, box["height"] / 2), steps=12)
    page.mouse.up()
    after = panel.evaluate("el => el.getBoundingClientRect().width")
    assert after >= before + 50
    stored = page.evaluate("() => localStorage.getItem('asc.agentPanel.width')")
    assert stored
    assert abs(float(stored) - after) < 2
    log_width = page.evaluate("() => localStorage.getItem('asc.taskLogDrawer.width')")
    assert log_width in (None, "")


def test_log_overlay_drag_resizes_without_changing_agent_width(agent_ui: AgentE2E):
    page = agent_ui.page
    _goto_ready(page)
    page.locator(f'[data-dashboard-log-task="{agent_ui.task_id}"]').first.click()
    expect(page.locator("#task-log-drawer.is-open")).to_be_visible()
    drawer = page.locator("#task-log-drawer")
    handle = page.locator("[data-task-log-resize]")
    expect(handle).to_be_visible()
    grip = handle.locator(".task-log-drawer__resize-grip")
    expect(grip).to_be_visible()
    agent_before = page.evaluate("() => localStorage.getItem('asc.agentPanel.width')")
    before = drawer.evaluate("el => el.getBoundingClientRect().width")
    handle.hover()
    box = handle.bounding_box()
    assert box
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + min(40, box["height"] / 2))
    page.mouse.down()
    page.mouse.move(box["x"] - 80, box["y"] + min(40, box["height"] / 2), steps=12)
    page.mouse.up()
    after = drawer.evaluate("el => el.getBoundingClientRect().width")
    assert after >= before + 50
    stored = page.evaluate("() => localStorage.getItem('asc.taskLogDrawer.width')")
    assert stored
    assert abs(float(stored) - after) < 2
    agent_after = page.evaluate("() => localStorage.getItem('asc.agentPanel.width')")
    assert agent_after == agent_before


def test_assistant_markdown_renders_inline(agent_ui: AgentE2E):
    agent_ui.llm.impl = ScriptedLLM([[
        {"content": TOKEN_MD, "finish_reason": "stop"},
    ]])
    page = agent_ui.page
    _goto_ready(page)
    _open_dashboard_explain(page, agent_ui.task_id)
    msg = page.locator(".agent-msg--assistant")
    expect(msg).to_have_class(re.compile(r"agent-msg--md"))
    expect(msg.locator("strong")).to_contain_text("bold")
    expect(msg.locator("code")).to_contain_text("code")
    expect(msg).not_to_contain_text("**bold**")


def test_assistant_markdown_renders_without_dompurify(agent_ui: AgentE2E):
    page = agent_ui.page
    _goto_ready(page)
    page.locator("[data-agent-toggle]").click()
    _expect_agent_open(page)
    result = page.evaluate(
        """() => {
          window.DOMPurify = undefined;
          const el = document.createElement("div");
          window.AscAgentDock.setAssistantMarkdown(el, "hello **bold** and `code`");
          return { html: el.innerHTML, cls: el.className };
        }"""
    )
    assert "<strong>" in result["html"]
    assert "<code>" in result["html"]
    assert "agent-msg--md" in result["cls"]
    assert "**bold**" not in result["html"]


def test_explain_failed_task_streams_mocked_tokens(agent_ui: AgentE2E):
    agent_ui.llm.impl = ScriptedLLM([[
        {"content": TOKEN_STREAM, "finish_reason": "stop"},
    ]])
    page = agent_ui.page
    _goto_ready(page)
    _open_dashboard_explain(page, agent_ui.task_id)
    expect(page.locator(".agent-msg--assistant")).to_contain_text(TOKEN_STREAM)
    assert agent_ui.spies["stream"], "expected POST /api/agent/stream"
    body = json.loads(agent_ui.spies["stream"][0])
    assert body.get("auto_analyze") is True
    assert body.get("task_id") == agent_ui.task_id


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
    _confirm_apply(page, card)
    expect(page.locator("#task-log-drawer.is-open")).to_be_visible()
    after = page.evaluate("() => window.AscAgentDock.getState()")
    assert after["sessionId"] == before["sessionId"]
    assert after["boundTaskId"] == before["boundTaskId"]
    assert after["open"] is True
    assert "new" in agent_ui.csv_path.read_text(encoding="utf-8")


def test_plan_card_apply_visible_only_after_done_with_mutations(agent_ui: AgentE2E):
    rounds = _propose_rounds(
        agent_ui.task_id,
        "app.csv",
        mutations=[_csv_mutation("app.csv")],
        summary=PLAN_MUTATIONS,
        token=TOKEN_MUTATIONS,
    )
    after_content = threading.Event()
    resume = threading.Event()
    agent_ui.llm.impl = HoldAfterContentLLM(rounds, after_content, resume)
    page = agent_ui.page
    try:
        _goto_ready(page)
        _open_drawer_explain(page, agent_ui.task_id)
        assert after_content.wait(timeout=8)
        expect(page.locator(".agent-msg--assistant")).to_contain_text(TOKEN_MUTATIONS)
        expect(page.locator(".agent-plan-card")).to_have_count(0)
    finally:
        resume.set()
    card = page.locator(".agent-plan-card")
    expect(card).to_be_visible()
    expect(card).to_contain_text(PLAN_MUTATIONS)
    expect(card.get_by_role("button", name="应用", exact=True)).to_be_visible()
    assert "oldkeywords" in agent_ui.csv_path.read_text(encoding="utf-8")


def test_plan_card_hides_apply_when_mutations_empty(agent_ui: AgentE2E):
    rounds = _propose_rounds(
        agent_ui.task_id,
        "app.csv",
        mutations=[],
        summary=PLAN_EMPTY,
        token=TOKEN_EMPTY,
        rerun=False,
        manual_steps=["在 App Store Connect 控制台手动改"],
    )
    agent_ui.llm.impl = ScriptedLLM(rounds)
    page = agent_ui.page
    _goto_ready(page)
    _open_drawer_explain(page, agent_ui.task_id)
    expect(page.locator(".agent-msg--assistant")).to_contain_text(TOKEN_EMPTY)
    card = page.locator(".agent-plan-card")
    expect(card).to_be_visible()
    expect(card).to_contain_text(PLAN_EMPTY)
    expect(card.get_by_role("button", name="应用", exact=True)).to_have_count(0)
    expect(card.get_by_role("button", name="忽略", exact=True)).to_be_visible()


def test_apply_does_not_throw_and_opens_logs_on_rerun(agent_ui: AgentE2E):
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
    _open_drawer_explain(page, agent_ui.task_id)
    card = page.locator(".agent-plan-card")
    expect(card.get_by_role("button", name="应用", exact=True)).to_be_visible()
    with page.expect_response(lambda response: "/api/agent/apply" in response.url) as apply_resp:
        _confirm_apply(page, card)
    assert apply_resp.value.ok
    expect(page.locator("#task-log-drawer.is-open")).to_be_visible()
    expect(page.locator("#task-log-panel-logs")).to_be_visible()
    assert agent_ui.spies["apply"], "expected POST /api/agent/apply"
    payload = json.loads(agent_ui.spies["apply"][0])
    assert payload.get("plan_id")
    assert payload.get("rerun") is True
    assert payload.get("confirm") is True
    assert "new" in agent_ui.csv_path.read_text(encoding="utf-8")
    assert agent_ui.page_errors == []


@pytest.mark.parametrize("how", ["x", "escape", "overlay"])
def test_closing_log_overlay_does_not_apply(agent_ui: AgentE2E, how: str):
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
    _open_drawer_explain(page, agent_ui.task_id)
    expect(page.locator(".agent-plan-card").get_by_role("button", name="应用", exact=True)).to_be_visible()
    session = agent_ui.agents.get_or_create_session(agent_ui.task_id, "myapp")
    messages_before = agent_ui.agents.list_messages(session["id"])
    assert messages_before
    before = agent_ui.csv_path.read_bytes()
    _close_log_overlay(page, how)
    assert page.evaluate("() => window.AscAgentDock.getState().open") is True
    assert agent_ui.spies["apply"] == []
    assert agent_ui.csv_path.read_bytes() == before
    assert agent_ui.agents.get_session(session["id"]) is not None
    assert agent_ui.agents.list_messages(session["id"]) == messages_before


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
