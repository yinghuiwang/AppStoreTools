"""Task log warning vs error classification for Web UI coloring."""

from __future__ import annotations

from pathlib import Path

from asc.reporting import classify_log_level
from asc.web.sse import format_task_log_sse

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"


def test_warning_text_is_not_classified_as_error():
    cases = [
        "⚠️  翻译失败: timeout",
        "WARNING: retry failed",
        "WARN: skip existing",
        "警告：配置格式错误，已跳过",
        "  ⚠️  locale=ja 配置格式错误，已跳过",
        "warning: polling failed",
    ]
    for message in cases:
        assert classify_log_level(message) == "warning", message
        assert classify_log_level(message, "error") == "warning", message


def test_error_text_stays_error():
    cases = [
        "❌ locale=ja metadata failed: denied",
        "ERROR: upload failed",
        "Error: missing key",
        "Traceback (most recent call last):",
        "上传失败",
        "RuntimeError: boom",
    ]
    for message in cases:
        assert classify_log_level(message) == "error", message


def test_structured_warning_wins_without_markers():
    assert classify_log_level("could not refresh marker", "warning") == "warning"
    assert classify_log_level("done", "info") == "info"
    assert classify_log_level("detail", "debug") == "info"


def test_reporter_log_promotes_warning_markers():
    from asc.reporting import TaskReporter

    class Sink:
        def __init__(self) -> None:
            self.events = []

        def on_event(self, event) -> None:
            self.events.append(event)

    sink = Sink()
    reporter = TaskReporter(sinks=[sink], task_kind="metadata")
    reporter.log("⚠️  预览模式，不实际更新")
    reporter.log("  ⚠️  locale=ja 配置格式错误，已跳过")
    assert sink.events[0].level == "warning"
    assert sink.events[1].level == "warning"
    assert sink.events[1].event_type != "error"


def test_sse_warning_payload_is_not_error_level():
    frame = format_task_log_sse("⚠️  Task log flush failed: disk full", event_id=2)
    assert '"level": "warning"' in frame
    assert '"level": "error"' not in frame
    assert "Task log flush failed" in frame


def test_task_log_panel_uses_warning_class_not_error_red():
    panel = (FRONTEND / "components" / "TaskLogPanel.vue").read_text(encoding="utf-8")
    util = (FRONTEND / "utils" / "logLevel.ts").read_text(encoding="utf-8")
    task_log = (FRONTEND / "composables" / "useTaskLog.ts").read_text(encoding="utf-8")

    assert "classifyLogLevel" in panel
    assert "parseLogEventData" in task_log
    assert "isErrorLine" not in panel
    assert "warn: lineLevel(line) === 'warning'" in panel
    assert "err: lineLevel(line) === 'error'" in panel
    assert ".line.warn" in panel
    assert "color: var(--warn)" in panel
    assert ".line.err" in panel
    assert "color: var(--err)" in panel
    assert "WARNING_RE" in util
    assert "textLevel === \"warning\"" in util
    assert "parseLogEventData" in util
    # errors-only must not treat warning lines as errors
    assert "lineLevel(line) === \"error\"" in panel or "lineLevel(line) === 'error'" in panel
