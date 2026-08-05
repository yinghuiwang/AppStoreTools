"""Unified task logging and progress reporting for CLI and Web."""

from __future__ import annotations

import sys
import time
from typing import Any, Protocol, Sequence


class ProgressSink(Protocol):
    def on_log(self, message: str, *, level: str) -> None: ...

    def on_progress(
        self,
        *,
        pct: int,
        msg: str,
        phase: str,
        phase_label: str,
        phase_index: int,
        phase_total: int,
    ) -> None: ...


class CliSink:
    """Print progress and log lines to stdout."""

    def on_log(self, message: str, *, level: str = "info") -> None:
        print(message)

    def on_progress(
        self,
        *,
        pct: int,
        msg: str,
        phase: str,
        phase_label: str,
        phase_index: int,
        phase_total: int,
    ) -> None:
        label = phase_label or phase
        if msg:
            print(f"[{pct}%] {label}: {msg}")
        else:
            print(f"[{pct}%] {label}")


class TaskStoreSink:
    """Fan-out progress/log events into a TaskStore (Task 2 extended signature)."""

    _LOG_BATCH_INTERVAL_SEC = 0.25
    _MAX_PENDING_LOGS = 100

    def __init__(self, store: Any, task_id: str) -> None:
        self._store = store
        self._task_id = task_id
        self._pending_logs: list[str] = []
        self._last_log_flush = time.monotonic()
        self._flush_failures = 0

    def on_log(self, message: str, *, level: str = "info") -> None:
        self._pending_logs.append(message)
        now = time.monotonic()
        if (
            len(self._pending_logs) >= self._MAX_PENDING_LOGS
            or now - self._last_log_flush >= self._LOG_BATCH_INTERVAL_SEC
        ):
            self.flush()

    def on_progress(
        self,
        *,
        pct: int,
        msg: str,
        phase: str,
        phase_label: str,
        phase_index: int,
        phase_total: int,
    ) -> None:
        # Never let a progress DB write abort a long-running job (e.g. pip update).
        try:
            self.flush()
            self._store.set_progress(
                self._task_id,
                pct,
                msg,
                phase=phase,
                phase_label=phase_label,
                phase_index=phase_index,
                phase_total=phase_total,
            )
        except Exception as exc:  # noqa: BLE001 — sink must not raise into workers
            self._flush_failures += 1
            print(f"⚠️  Task progress update failed: {exc}", file=sys.stderr)

    def flush(self) -> None:
        """Persist accumulated subprocess output in one database transaction."""
        if not self._pending_logs:
            return
        messages = self._pending_logs
        self._pending_logs = []
        self._last_log_flush = time.monotonic()
        try:
            append_logs = getattr(self._store, "append_logs", None)
            if callable(append_logs):
                ok = append_logs(self._task_id, messages)
                # Soft-fail stores return False; re-queue a bounded batch for retry.
                if ok is False:
                    self._requeue_logs(messages)
                    self._flush_failures += 1
                    print(
                        f"⚠️  Task log flush degraded for {self._task_id}",
                        file=sys.stderr,
                    )
            else:  # Compatibility with third-party TaskStore-like sinks.
                for message in messages:
                    self._store.append_log(self._task_id, message)
        except Exception as exc:  # noqa: BLE001 — keep install/update running
            self._requeue_logs(messages)
            self._flush_failures += 1
            print(f"⚠️  Task log flush failed: {exc}", file=sys.stderr)

    def _requeue_logs(self, messages: list[str]) -> None:
        # Prefer newest context; avoid unbounded growth if DB stays down.
        merged = messages + self._pending_logs
        self._pending_logs = merged[-self._MAX_PENDING_LOGS :]


class TaskReporter:
    """Map phased fine-grained progress to a monotonic global percentage."""

    def __init__(
        self,
        sinks: Sequence[ProgressSink] | None = None,
        *,
        verbose: bool = False,
    ) -> None:
        self._sinks: list[ProgressSink] = list(sinks or [])
        self.verbose = verbose
        self.failed: bool = False
        self._phases: list[tuple[str, float, str]] = []
        self._phase_id: str = ""
        self._phase_label: str = ""
        self._phase_index: int = 0  # 1-based when active
        self._phase_start: float = 0.0
        self._phase_weight: float = 0.0
        self._pct: int = 0

    def set_phases(self, phases: list[tuple[str, int, str]]) -> None:
        raw = [(pid, float(weight), label) for pid, weight, label in phases]
        total = sum(w for _, w, _ in raw)
        if total <= 0:
            self._phases = []
            return
        if abs(total - 100.0) > 1e-9:
            self._phases = [(pid, w * 100.0 / total, label) for pid, w, label in raw]
        else:
            self._phases = raw

    def phase(self, phase_id: str) -> None:
        if not self._phases:
            self._phase_id = phase_id
            self._phase_label = phase_id
            self._phase_index = 1
            self._phase_start = 0.0
            self._phase_weight = 100.0
            self._emit_progress(msg="")
            return

        idx = next((i for i, (pid, _, _) in enumerate(self._phases) if pid == phase_id), None)
        if idx is None:
            raise KeyError(f"unknown phase: {phase_id}")

        self._phase_id = phase_id
        self._phase_label = self._phases[idx][2]
        self._phase_index = idx + 1  # 1-based
        self._phase_start = sum(w for _, w, _ in self._phases[:idx])
        self._phase_weight = self._phases[idx][1]
        # Phase start: effective current=0
        self._apply_pct(self._phase_start)
        self._emit_progress(msg="")

    def progress(self, current: int, total: int, msg: str | None = None) -> None:
        if total <= 0:
            fraction = 0.0
        else:
            clamped = max(0, min(int(current), int(total)))
            fraction = clamped / float(total)
        candidate = self._phase_start + fraction * self._phase_weight
        self._apply_pct(candidate)
        self._emit_progress(msg=msg or "")

    def log(self, message: str, *, level: str = "info") -> None:
        for sink in self._sinks:
            sink.on_log(message, level=level)

    def debug(self, message: str) -> None:
        if not self.verbose:
            return
        self.log(message, level="debug")

    def done(self, summary: str | None = None) -> None:
        self._pct = 100
        self._emit_progress(msg=summary or "")
        if summary:
            self.log(summary)

    def fail(self, message: str, *, detail: str | None = None) -> None:
        self.failed = True
        self.log(message, level="error")
        if detail:
            self.log(detail, level="error")

    def flush(self) -> None:
        """Flush buffered sinks before a task reaches a terminal state."""
        for sink in self._sinks:
            flush = getattr(sink, "flush", None)
            if callable(flush):
                flush()

    def _apply_pct(self, candidate: float) -> None:
        value = int(candidate)
        if value < 0:
            value = 0
        if value > 100:
            value = 100
        self._pct = max(self._pct, value)

    def _emit_progress(self, *, msg: str) -> None:
        phase_total = len(self._phases) if self._phases else (1 if self._phase_id else 0)
        for sink in self._sinks:
            sink.on_progress(
                pct=self._pct,
                msg=msg,
                phase=self._phase_id,
                phase_label=self._phase_label,
                phase_index=self._phase_index,
                phase_total=phase_total,
            )


def make_cli_reporter(*, verbose: bool = False) -> TaskReporter:
    return TaskReporter(sinks=[CliSink()], verbose=verbose)


def make_web_reporter(task_store: Any, task_id: str, *, verbose: bool = False) -> TaskReporter:
    return TaskReporter(sinks=[TaskStoreSink(task_store, task_id)], verbose=verbose)
