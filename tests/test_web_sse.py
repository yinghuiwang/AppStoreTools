# tests/test_web_sse.py
from __future__ import annotations
import io
import sys
from unittest.mock import MagicMock
from asc.web.sse import capture_stdout_to_queue, format_sse_event


def test_format_sse_event_log():
    result = format_sse_event("log", "hello world")
    assert result == "event: log\ndata: hello world\n\n"


def test_format_sse_event_progress():
    result = format_sse_event("progress", "50")
    assert result == "event: progress\ndata: 50\n\n"


def test_format_sse_event_done():
    result = format_sse_event("done", "")
    assert result == "event: done\ndata: \n\n"


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
