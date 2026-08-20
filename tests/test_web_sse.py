# tests/test_web_sse.py
from __future__ import annotations
import io
import sys
from unittest.mock import MagicMock
from asc.web.sse import capture_stdout_to_queue, format_sse_event, format_task_log_sse


def test_format_sse_event_log():
    result = format_sse_event("log", "hello world")
    assert result == "event: log\ndata: hello world\n\n"


def test_format_sse_event_progress():
    result = format_sse_event("progress", "50")
    assert result == "event: progress\ndata: 50\n\n"


def test_format_sse_event_done():
    result = format_sse_event("done", "")
    assert result == "event: done\ndata: \n\n"


def test_format_sse_event_includes_optional_id():
    result = format_sse_event("log", "hello", event_id=3)
    assert result == "id: 3\nevent: log\ndata: hello\n\n"


def test_format_sse_event_escapes_multiline_data():
    """Embedded newlines must not terminate the SSE event early."""
    result = format_sse_event("log", "line1\nline2\n\nline4", event_id=7)
    assert result == (
        "id: 7\n"
        "event: log\n"
        "data: line1\n"
        "data: line2\n"
        "data: \n"
        "data: line4\n"
        "\n"
    )
    # Following event stays intact after a multiline payload.
    follow = format_sse_event("log", "next", event_id=8)
    assert follow.startswith("id: 8\nevent: log\ndata: next\n")


def test_format_sse_event_normalizes_crlf():
    result = format_sse_event("log", "a\r\nb\rc")
    assert result == "event: log\ndata: a\ndata: b\ndata: c\n\n"


def test_capture_stdout_to_queue():
    import queue
    q = queue.Queue()
    with capture_stdout_to_queue(q):
        print("line one")
        print("line two")
    lines = []
    while not q.empty():
        lines.append(q.get_nowait())
    assert "line one" in lines
    assert "line two" in lines


def test_capture_stdout_restores_on_exit():
    import queue
    original = sys.stdout
    q = queue.Queue()
    with capture_stdout_to_queue(q):
        pass
    assert sys.stdout is original


def test_format_task_log_sse_includes_structured_level():
    result = format_task_log_sse("hello world", event_id=3)
    assert result == (
        'id: 3\nevent: log\ndata: {"message": "hello world", "level": "info"}\n\n'
    )


def test_format_task_log_sse_keeps_warning_out_of_error():
    warning = format_task_log_sse("⚠️  翻译失败: timeout")
    error = format_task_log_sse("❌ locale=ja metadata failed: denied")
    assert '"level": "warning"' in warning
    assert '"level": "error"' not in warning
    assert "翻译失败" in warning
    assert '"level": "error"' in error
    assert '"level": "warning"' not in error
