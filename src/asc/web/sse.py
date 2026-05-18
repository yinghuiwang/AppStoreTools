"""SSE helpers: stdout capture and event formatting for Web UI log streaming."""
from __future__ import annotations

import io
import queue
import sys
from contextlib import contextmanager
from typing import Generator


def format_sse_event(event: str, data: str) -> str:
    """Format a single SSE message frame."""
    return f"event: {event}\ndata: {data}\n\n"


class _QueueWriter(io.TextIOBase):
    """A file-like object that puts each written line into a queue."""

    def __init__(self, q: "queue.Queue[str]") -> None:
        self._q = q
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._q.put(line)
        return len(s)

    def flush(self) -> None:
        if self._buf:
            self._q.put(self._buf)
            self._buf = ""


@contextmanager
def capture_stdout_to_queue(q: "queue.Queue[str]") -> Generator[None, None, None]:
    """Context manager: redirect sys.stdout lines into q, restore on exit."""
    original = sys.stdout
    sys.stdout = _QueueWriter(q)
    try:
        yield
    finally:
        # Flush any remaining buffer
        if hasattr(sys.stdout, "flush"):
            sys.stdout.flush()
        sys.stdout = original
