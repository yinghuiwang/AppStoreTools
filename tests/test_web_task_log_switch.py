"""Right-rail task logs follow the focused task across concurrent jobs."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"


def _read(rel: str) -> str:
    return (FRONTEND / rel).read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    marker = f"function {name}"
    start = src.find(marker)
    assert start >= 0, f"missing function {name}"
    brace = src.find("{", start)
    assert brace >= 0, f"missing body for {name}"
    depth = 0
    for index, char in enumerate(src[brace:], brace):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return src[start : index + 1]
    raise AssertionError(f"unclosed function {name}")


def test_use_task_log_is_module_scoped_not_pinia() -> None:
    src = _read("composables/useTaskLog.ts")
    assert "pinia" not in src.lower()
    assert "defineStore" not in src
    assert "const activeTaskId = ref" in src
    assert "const channels = reactive" in src
    assert "function setActiveTask" in src
    assert "function subscribeIfNeeded" in src
    assert "function channelOf" in src
    assert "export function useTaskLog" in src


def test_subscribe_if_needed_keeps_background_streams() -> None:
    src = _read("composables/useTaskLog.ts")
    body = _fn(src, "subscribeIfNeeded")
    assert "activeTaskId.value =" not in body
    assert "ensureChannel" in body
    assert "openEventSource" in body
    # Reuse this task's live source; do not key off the global active id.
    assert "logTaskId.value === taskId" not in body
    assert "rt.source" in body or "ch.connection" in body


def test_set_active_task_switches_view_without_resetting_cache() -> None:
    src = _read("composables/useTaskLog.ts")
    body = _fn(src, "setActiveTask")
    assert "activeTaskId.value = taskId" in body
    assert "subscribeIfNeeded(taskId)" in body
    assert "lines.value = []" not in body
    assert "closeSource()" not in body.replace("closeSource(taskId)", "")


def test_sse_handlers_write_to_own_channel() -> None:
    src = _read("composables/useTaskLog.ts")
    body = _fn(src, "openEventSource")
    assert "closeSource(taskId)" in body
    assert "channels[taskId]" in body or "ensureChannel(taskId)" in body
    assert "ch.lines" in body
    assert "ch.progress" in body
    assert "ch.status" in body
    # Must not append onto a single module-level lines buffer.
    assert "lines.value =" not in body
    assert "lines.value.push" not in body


def test_disconnect_closes_every_channel() -> None:
    src = _read("composables/useTaskLog.ts")
    body = _fn(src, "disconnect")
    assert "Object.keys(channels)" in body or "runtime.keys()" in body
    assert "closeSource" in body


def test_open_logs_focuses_task_and_stays_on_logs_tab() -> None:
    src = _read("composables/useRightRail.ts")
    body = _fn(src, "openLogs")
    assert 'tab.value = "logs"' in body
    assert "open.value = true" in body
    assert "setActiveTask" in body
    assert "persistChrome" in body


def test_task_run_bar_focuses_visible_task() -> None:
    src = _read("components/TaskRunBar.vue")
    assert "onActivated" in src
    assert "setActiveTask" in src
    assert "subscribeIfNeeded" in src
    assert "channelOf" in src
    assert "cancel(props.taskId)" in src or "cancel(props.taskId as" in src


def test_task_log_panel_binds_active_task() -> None:
    src = _read("components/TaskLogPanel.vue")
    assert 'data-log-task-id' in src
    assert "logTaskId" in src
    assert "setActiveTask" in src or "subscribe(" in src


def test_dashboard_log_buttons_open_logs() -> None:
    src = _read("views/DashboardView.vue")
    assert "rail.openLogs(task.id)" in src
    assert "rail.openLogs(row.id)" in src
    assert "channels" in src


def test_diff_and_whats_new_watch_own_channel() -> None:
    diff = _read("views/listing/DiffTab.vue")
    whats = _read("views/WhatsNewView.vue")
    assert "channelOf" in diff
    assert "channelOf" in whats
    assert "watch([status, logTaskId]" not in diff
    assert "watch([status, logTaskId]" not in whats
