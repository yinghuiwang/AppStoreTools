"""SSE helpers: stdout capture and event formatting for Web UI log streaming."""
from __future__ import annotations

import io
import queue
import sys
from contextlib import contextmanager
from typing import Generator


def format_sse_data(data: str, event_id: int | str | None = None) -> str:
    """Format a data-only SSE frame (AG-UI / default TDesign Chat protocol)."""
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    normalized = str(data).replace("\r\n", "\n").replace("\r", "\n")
    data_block = "".join(f"data: {line}\n" for line in normalized.split("\n"))
    return f"{prefix}{data_block}\n"


def format_sse_event(event: str, data: str, event_id: int | str | None = None) -> str:
    """Format a single SSE message frame.

    Multiline ``data`` is emitted as multiple ``data:`` lines per the SSE spec so
    embedded newlines cannot prematurely terminate or corrupt the event stream.
    """
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    # Normalize newlines; each logical line becomes its own data: field.
    normalized = str(data).replace("\r\n", "\n").replace("\r", "\n")
    data_block = "".join(f"data: {line}\n" for line in normalized.split("\n"))
    return f"{prefix}event: {event}\n{data_block}\n"


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
