"""Unified task logging and progress reporting for CLI and Web."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import logging
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Literal, Protocol, Sequence


_LOGGER = logging.getLogger("asc.web")
_ERROR_RAW_LOG_RE = re.compile(
    r"\b(?:fail|failed|failure|error|fatal|exception|traceback)\b"
    r"|\b(?-i:[A-Z][A-Za-z0-9_]*Error)\b"
    r"|错误|失败|异常",
    re.IGNORECASE,
)
_WARNING_RAW_LOG_RE = re.compile(r"\bwarning\b|警告", re.IGNORECASE)
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_WARNING_PREFIX_RE = re.compile(r"^\s*(?:warning|警告)\s*[:：-]?\s*", re.IGNORECASE)
_XCODE_CATEGORY_PATTERNS = (
    ("CompileSwift", re.compile(r"^\s*CompileSwift\b")),
    ("CompileC", re.compile(r"^\s*CompileC\b")),
    ("Ld", re.compile(r"^\s*Ld\b")),
    ("CodeSign", re.compile(r"^\s*CodeSign\b")),
    ("Copy", re.compile(r"^\s*(?:Copy|CpResource)\b")),
)
_PIP_CATEGORY_PATTERNS = (
    ("Collecting", re.compile(r"^\s*Collecting\b", re.IGNORECASE)),
    ("Using cached", re.compile(r"^\s*Using cached\b", re.IGNORECASE)),
    (
        "Requirement already satisfied",
        re.compile(r"^\s*Requirement already satisfied\b", re.IGNORECASE),
    ),
    (
        "download",
        re.compile(r"^\s*(?:Downloading|Cloning|Fetching)\b", re.IGNORECASE),
    ),
    (
        "install files",
        re.compile(
            r"^\s*(?:Installing|Building wheel|Attempting uninstall)\b",
            re.IGNORECASE,
        ),
    ),
)

TaskEventType = Literal[
    "operation",
    "phase",
    "milestone",
    "success",
    "failure",
    "canceled",
    "warning",
    "error",
    "context",
    "summary",
    "raw",
]
TaskLogLevel = Literal["debug", "info", "warning", "error"]


@dataclass(frozen=True)
class TaskLogEvent:
    event_type: TaskEventType
    message: str
    level: TaskLogLevel
    task_kind: str
    phase: str = ""
    source: str = "application"
    dedupe_key: str | None = None
    raw_line_no: int | None = None


class RawLogPolicy(Protocol):
    def consume(self, event: TaskLogEvent) -> list[TaskLogEvent]: ...

    def flush_phase(
        self,
        phase: str,
        *,
        closing: bool = False,
    ) -> list[TaskLogEvent]: ...

    def finish(self, *, failed: bool) -> list[TaskLogEvent]: ...


class RawLogCallback(Protocol):
    def __call__(self, message: str) -> None: ...

    def application(self, message: str, *, level: str = "info") -> None: ...

    def set_phase(self, phase: str) -> None: ...

    def finish(self, *, failed: bool) -> None: ...

    def flush(self) -> None: ...


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


class _PassthroughPolicy:
    def consume(self, event: TaskLogEvent) -> list[TaskLogEvent]:
        return [event]

    def flush_phase(self, phase: str, *, closing: bool = False) -> list[TaskLogEvent]:
        return []

    def finish(self, *, failed: bool) -> list[TaskLogEvent]:
        return []


_GENERIC_INFRA_PATTERNS = (
    ("poll", re.compile(r"\b(?:poll|polling)\b", re.IGNORECASE)),
    ("pagination", re.compile(r"\b(?:page|pagination)\b", re.IGNORECASE)),
    ("retry", re.compile(r"\b(?:retry|rate[ -]?limit|429)\b", re.IGNORECASE)),
    ("progress", re.compile(r"\b(?:progress|percent)\b", re.IGNORECASE)),
    ("note", re.compile(r"\b(?:note|debug)\b", re.IGNORECASE)),
)
_GENERIC_ENDPOINT_RE = re.compile(r"\bendpoint\s*[=:]\s*([^\s,;]+)", re.IGNORECASE)
_GENERIC_IDENTITY_RE = re.compile(
    r"\b(locale|product(?:_id)?|subscription|file|screenshot|commit|asset)"
    r"\s*[=:]\s*([^\s,;]+)",
    re.IGNORECASE,
)


class _GenericRawLogPolicy:
    """Collapse recognized infrastructure chatter without losing object identity."""

    _GROUP_LIMIT = 256

    def __init__(self, task_kind: str) -> None:
        self._task_kind = task_kind
        self._groups: dict[
            tuple[str, str, str, str, tuple[tuple[str, str], ...]],
            tuple[TaskLogEvent, int],
        ] = {}
        self._phase_order: list[str] = []
        self._overflow_count = 0
        self._overflow_event: TaskLogEvent | None = None
        self._before: deque[TaskLogEvent] = deque(maxlen=5)
        self._tail: deque[TaskLogEvent] = deque(maxlen=20)
        self._pending_after = 0
        self._visible_ids: set[tuple[str, int]] = set()
        self._visible_order: deque[tuple[str, int]] = deque()

    def consume(self, event: TaskLogEvent) -> list[TaskLogEvent]:
        prior = list(self._before)
        self._tail.append(event)
        emitted: list[TaskLogEvent] = []
        normalized = _ANSI_RE.sub("", event.message)
        category = self._category(normalized)
        if _ERROR_RAW_LOG_RE.search(normalized):
            for previous in prior:
                self._append_visible(
                    emitted,
                    replace(previous, event_type="context", level="info"),
                )
            self._append_visible(
                emitted,
                replace(event, event_type="error", level="error"),
            )
            self._pending_after = 10
        elif _WARNING_RAW_LOG_RE.search(normalized):
            self._append_visible(emitted, event)
        elif self._pending_after:
            self._pending_after -= 1
            self._append_visible(
                emitted,
                replace(event, event_type="context", level="info"),
            )
        elif category is None:
            self._append_visible(emitted, event)
        else:
            # Group on the ANSI-free text so colored output cannot split a group.
            endpoint_match = _GENERIC_ENDPOINT_RE.search(normalized)
            endpoint = endpoint_match.group(1) if endpoint_match else "-"
            identities = tuple(
                (key.lower(), value)
                for key, value in _GENERIC_IDENTITY_RE.findall(normalized)
            )
            key = (
                event.phase,
                event.source,
                category,
                endpoint,
                identities,
            )
            track_phase = False
            if key in self._groups:
                first, count = self._groups[key]
                self._groups[key] = (first, count + 1)
                track_phase = True
            elif len(self._groups) < self._GROUP_LIMIT:
                self._groups[key] = (event, 1)
                track_phase = True
            else:
                self._overflow_count += 1
                if self._overflow_event is None:
                    self._overflow_event = event
                    track_phase = True
            if track_phase and event.phase not in self._phase_order:
                self._phase_order.append(event.phase)
        self._before.append(event)
        return emitted

    def flush_phase(self, phase: str, *, closing: bool = False) -> list[TaskLogEvent]:
        del closing  # generic grouping always resets its context per phase flush
        emitted: list[TaskLogEvent] = []
        for key, (event, count) in list(self._groups.items()):
            if key[0] != phase:
                continue
            message = event.message
            if count > 1:
                message = f"{message}（重复 {count - 1} 次）"
            emitted.append(
                replace(
                    event,
                    event_type="summary",
                    message=message,
                    level="info",
                    dedupe_key="|".join(
                        (
                            self._task_kind,
                            key[0],
                            key[1],
                            key[2],
                            key[3],
                            repr(key[4]),
                        )
                    ),
                    raw_line_no=None,
                )
            )
            del self._groups[key]
        if (
            self._overflow_count
            and self._overflow_event is not None
            and self._overflow_event.phase == phase
        ):
            emitted.append(
                replace(
                    self._overflow_event,
                    event_type="summary",
                    message=(
                        "generic infrastructure overflow: "
                        f"{self._overflow_count} high-cardinality lines omitted"
                    ),
                    level="info",
                    raw_line_no=None,
                )
            )
            self._overflow_count = 0
            self._overflow_event = None
        if phase in self._phase_order:
            self._phase_order.remove(phase)
        self._before.clear()
        self._tail.clear()
        self._pending_after = 0
        self._visible_ids.clear()
        self._visible_order.clear()
        return emitted

    def finish(self, *, failed: bool) -> list[TaskLogEvent]:
        emitted: list[TaskLogEvent] = []
        if failed:
            for event in self._tail:
                self._append_visible(
                    emitted,
                    replace(event, event_type="context", level="info"),
                )
        for phase in list(self._phase_order):
            emitted.extend(self.flush_phase(phase, closing=True))
        self._groups.clear()
        self._phase_order.clear()
        self._overflow_count = 0
        self._overflow_event = None
        self._before.clear()
        self._tail.clear()
        self._pending_after = 0
        self._visible_ids.clear()
        self._visible_order.clear()
        return emitted

    def _append_visible(
        self,
        output: list[TaskLogEvent],
        event: TaskLogEvent,
    ) -> bool:
        if event.raw_line_no is None:
            output.append(event)
            return True
        identity = (event.source, event.raw_line_no)
        if identity in self._visible_ids:
            return False
        self._visible_ids.add(identity)
        self._visible_order.append(identity)
        while len(self._visible_order) > 64:
            expired = self._visible_order.popleft()
            self._visible_ids.discard(expired)
        output.append(event)
        return True

    @staticmethod
    def _category(message: str) -> str | None:
        for category, pattern in _GENERIC_INFRA_PATTERNS:
            if pattern.search(message):
                return category
        return None


def _canonical_warning(message: str) -> str:
    without_ansi = _ANSI_RE.sub("", message)
    without_prefix = _WARNING_PREFIX_RE.sub("", without_ansi)
    return " ".join(without_prefix.split())


def _classify_xcode_line(message: str) -> str:
    for category, pattern in _XCODE_CATEGORY_PATTERNS:
        if pattern.search(message):
            return category
    return "other"


def _classify_pip_line(message: str) -> str:
    for category, pattern in _PIP_CATEGORY_PATTERNS:
        if pattern.search(message):
            return category
    return "other"


@dataclass
class _PhaseStats:
    errors: int = 0
    warnings: int = 0
    context: int = 0
    unclassified: int = 0


class _RawContextPolicy:
    """Keep diagnostics and bounded context while summarizing noisy raw output."""

    _WARNING_LIMIT = 50

    def __init__(self, raw_log_path: str | Path | None = None) -> None:
        self._raw_log_path = Path(raw_log_path) if raw_log_path is not None else None
        self._before: deque[TaskLogEvent] = deque(maxlen=5)
        self._tail: deque[TaskLogEvent] = deque(maxlen=20)
        self._pending_after = 0
        self._emitted_raw_ids: set[tuple[str, int]] = set()
        self._emitted_raw_order: deque[tuple[str, int]] = deque()
        self._unclassified_ids: dict[tuple[str, int], str] = {}
        self._warning_first: dict[str, dict[str, TaskLogEvent]] = {}
        self._warning_duplicates: dict[str, dict[str, int]] = {}
        self._warning_overflow: dict[str, int] = {}
        self._stats: dict[str, _PhaseStats] = {}
        self._dirty_phases: list[str] = []
        self._finished = False
        self._task_kind = ""
        self._source = "policy"

    def consume(self, event: TaskLogEvent) -> list[TaskLogEvent]:
        self._finished = False
        self._task_kind = event.task_kind
        self._source = event.source
        self._mark_dirty(event.phase)
        self._stats.setdefault(event.phase, _PhaseStats())
        prior = list(self._before)
        self._tail.append(event)
        emitted: list[TaskLogEvent] = []
        normalized = _ANSI_RE.sub("", event.message)

        if _ERROR_RAW_LOG_RE.search(normalized):
            self._stats[event.phase].errors += 1
            for previous in prior:
                context = replace(previous, event_type="context", level="info")
                if self._append_once(emitted, context):
                    self._mark_context(previous)
            self._append_once(
                emitted,
                replace(event, event_type="error", level="error"),
            )
            self._pending_after = 10
        elif _WARNING_RAW_LOG_RE.search(normalized):
            self._stats[event.phase].warnings += 1
            warning = self._record_warning(event)
            if self._pending_after:
                self._pending_after -= 1
                if warning is not None:
                    self._append_once(emitted, warning)
                elif self._append_once(
                    emitted,
                    replace(event, event_type="context", level="info"),
                ):
                    self._mark_context(event)
            elif warning is not None:
                self._append_once(emitted, warning)
        elif self._pending_after:
            self._pending_after -= 1
            if self._append_once(
                emitted,
                replace(event, event_type="context", level="info"),
            ):
                self._mark_context(event)
        else:
            self._record_plain(event)

        self._before.append(event)
        self._prune_unclassified_ids()
        return emitted

    def flush_phase(self, phase: str, *, closing: bool = False) -> list[TaskLogEvent]:
        summaries = self._phase_summaries(phase)
        self._before.clear()
        self._pending_after = 0
        if closing:
            # A phase boundary ends its diagnostics: the next phase must not
            # report this phase's lines as its own failure tail.
            self._tail.clear()
        self._clear_phase_state(phase)
        return summaries

    def finish(self, *, failed: bool) -> list[TaskLogEvent]:
        if self._finished:
            return []
        emitted: list[TaskLogEvent] = []
        if failed:
            for event in self._tail:
                if self._append_once(
                    emitted,
                    replace(event, event_type="context", level="info"),
                ):
                    self._mark_context(event)
        for phase in list(self._dirty_phases):
            emitted.extend(self.flush_phase(phase, closing=True))
        self._finished = True
        return emitted

    def note_unclassified(self, event: TaskLogEvent) -> None:
        self._mark_dirty(event.phase)
        self._stats.setdefault(event.phase, _PhaseStats()).unclassified += 1

    def _record_plain(self, event: TaskLogEvent) -> None:
        self._stats[event.phase].unclassified += 1
        if event.raw_line_no is not None:
            self._unclassified_ids[(event.source, event.raw_line_no)] = event.phase

    def _record_warning(self, event: TaskLogEvent) -> TaskLogEvent | None:
        phase = event.phase
        key = _canonical_warning(event.message)
        first = self._warning_first.setdefault(phase, {})
        duplicates = self._warning_duplicates.setdefault(phase, {})
        if key in first:
            duplicates[key] = duplicates.get(key, 0) + 1
            return None
        if len(first) >= self._WARNING_LIMIT:
            self._warning_overflow[phase] = self._warning_overflow.get(phase, 0) + 1
            return None
        warning = replace(
            event,
            event_type="warning",
            level="warning",
            dedupe_key=key,
        )
        first[key] = warning
        return warning

    def _phase_summaries(self, phase: str) -> list[TaskLogEvent]:
        emitted = self._warning_summaries(phase)
        stats = self._stats.get(phase)
        if stats is not None:
            path_hint = f"；完整日志：{self._raw_log_path}" if self._raw_log_path else ""
            emitted.append(
                self._summary_event(
                    phase,
                    (
                        f"阶段 {phase or '-'} 分类摘要：error {stats.errors} 行，"
                        f"warning {stats.warnings} 行，context {stats.context} 行，"
                        f"未分类 raw {stats.unclassified} 行{path_hint}"
                    ),
                )
            )
        return emitted

    def _warning_summaries(self, phase: str) -> list[TaskLogEvent]:
        emitted: list[TaskLogEvent] = []
        first = self._warning_first.get(phase, {})
        for key, count in self._warning_duplicates.get(phase, {}).items():
            event = first[key]
            emitted.append(
                replace(
                    event,
                    event_type="summary",
                    message=f"{event.message}（重复 {count} 次）",
                    level="info",
                    raw_line_no=None,
                )
            )
        overflow = self._warning_overflow.get(phase, 0)
        if overflow:
            emitted.append(self._summary_event(phase, f"其他 warning：{overflow} 行"))
        return emitted

    def _summary_event(self, phase: str, message: str) -> TaskLogEvent:
        return TaskLogEvent(
            event_type="summary",
            message=message,
            level="info",
            task_kind=self._task_kind,
            phase=phase,
            source=self._source,
        )

    def _append_once(
        self,
        output: list[TaskLogEvent],
        event: TaskLogEvent,
    ) -> bool:
        if event.raw_line_no is None:
            output.append(event)
            return True
        identity = (event.source, event.raw_line_no)
        if identity in self._emitted_raw_ids:
            return False
        self._emitted_raw_ids.add(identity)
        self._emitted_raw_order.append(identity)
        while len(self._emitted_raw_order) > 64:
            expired = self._emitted_raw_order.popleft()
            self._emitted_raw_ids.discard(expired)
        output.append(event)
        return True

    def _mark_context(self, event: TaskLogEvent) -> None:
        if event.raw_line_no is None:
            return
        identity = (event.source, event.raw_line_no)
        unclassified_phase = self._unclassified_ids.pop(identity, None)
        if unclassified_phase is not None:
            previous_stats = self._stats.setdefault(unclassified_phase, _PhaseStats())
            previous_stats.unclassified = max(0, previous_stats.unclassified - 1)
        stats = self._stats.setdefault(event.phase, _PhaseStats())
        stats.context += 1
        self._mark_dirty(event.phase)

    def _mark_dirty(self, phase: str) -> None:
        if phase not in self._dirty_phases:
            self._dirty_phases.append(phase)

    def _clear_phase_state(self, phase: str) -> None:
        self._stats.pop(phase, None)
        self._warning_duplicates.pop(phase, None)
        self._warning_overflow.pop(phase, None)
        if phase in self._dirty_phases:
            self._dirty_phases.remove(phase)

    def _prune_unclassified_ids(self) -> None:
        retained = {
            (event.source, event.raw_line_no)
            for event in (*self._before, *self._tail)
            if event.raw_line_no is not None
        }
        self._unclassified_ids = {
            identity: phase
            for identity, phase in self._unclassified_ids.items()
            if identity in retained
        }


class _BuildRawLogPolicy(_RawContextPolicy):
    """Summarize xcodebuild/altool noise while preserving diagnostics."""

    _PHASE_LABELS = {
        "archive": "归档",
        "export": "导出",
        "upload": "上传",
    }

    def __init__(
        self,
        source: str,
        raw_log_path: str | Path | None = None,
    ) -> None:
        super().__init__(raw_log_path)
        self._build_source = source
        self._category_counts: dict[str, dict[str, int]] = {}
        self._categorized_ids: dict[tuple[str, int], tuple[str, str]] = {}

    def _record_plain(self, event: TaskLogEvent) -> None:
        category = (
            _classify_xcode_line(event.message)
            if self._build_source == "xcodebuild"
            else "other"
        )
        counts = self._category_counts.setdefault(event.phase, {})
        counts[category] = counts.get(category, 0) + 1
        if event.raw_line_no is not None:
            self._categorized_ids[(event.source, event.raw_line_no)] = (
                event.phase,
                category,
            )

    def note_unclassified(self, event: TaskLogEvent) -> None:
        self._mark_dirty(event.phase)
        counts = self._category_counts.setdefault(event.phase, {})
        counts["other"] = counts.get("other", 0) + 1

    def _mark_context(self, event: TaskLogEvent) -> None:
        super()._mark_context(event)
        if event.raw_line_no is None:
            return
        categorized = self._categorized_ids.pop(
            (event.source, event.raw_line_no),
            None,
        )
        if categorized is None:
            return
        phase, category = categorized
        counts = self._category_counts.setdefault(phase, {})
        counts[category] = max(0, counts.get(category, 0) - 1)

    def _phase_summaries(self, phase: str) -> list[TaskLogEvent]:
        emitted = self._warning_summaries(phase)
        counts = self._category_counts.get(phase, {})
        stats = self._stats.get(phase)
        if not counts and stats is None and not emitted:
            return emitted
        parts = [
            f"{category} {counts[category]}"
            for category, _ in _XCODE_CATEGORY_PATTERNS
            if counts.get(category)
        ]
        other = counts.get("other", 0)
        if other:
            parts.append(f"省略其他输出 {other} 行")
        if stats is not None:
            if stats.errors:
                parts.append(f"error {stats.errors} 行")
            if stats.warnings:
                parts.append(f"warning {stats.warnings} 行")
            if stats.context:
                parts.append(f"context {stats.context} 行")
        if not parts:
            parts.append("无普通输出")
        path_hint = f"；完整日志：{self._raw_log_path}" if self._raw_log_path else ""
        label = self._PHASE_LABELS.get(phase, phase or "阶段")
        emitted.append(
            self._summary_event(
                phase,
                f"{label}摘要：" + "，".join(parts) + path_hint + "。",
            )
        )
        return emitted

    def _clear_phase_state(self, phase: str) -> None:
        super()._clear_phase_state(phase)
        self._category_counts.pop(phase, None)
        self._categorized_ids = {
            identity: value
            for identity, value in self._categorized_ids.items()
            if value[0] != phase
        }

    def _prune_unclassified_ids(self) -> None:
        super()._prune_unclassified_ids()
        retained = {
            (event.source, event.raw_line_no)
            for event in (*self._before, *self._tail)
            if event.raw_line_no is not None
        }
        self._categorized_ids = {
            identity: value
            for identity, value in self._categorized_ids.items()
            if identity in retained
        }


class _PipRawLogPolicy(_RawContextPolicy):
    """Summarize pip chatter while preserving bounded diagnostics."""

    def __init__(self, raw_log_path: str | Path | None = None) -> None:
        super().__init__(raw_log_path)
        self._category_counts: dict[str, dict[str, int]] = {}
        self._categorized_ids: dict[tuple[str, int], tuple[str, str]] = {}

    def _record_plain(self, event: TaskLogEvent) -> None:
        category = _classify_pip_line(event.message)
        counts = self._category_counts.setdefault(event.phase, {})
        counts[category] = counts.get(category, 0) + 1
        if event.raw_line_no is not None:
            self._categorized_ids[(event.source, event.raw_line_no)] = (
                event.phase,
                category,
            )

    def note_unclassified(self, event: TaskLogEvent) -> None:
        self._mark_dirty(event.phase)
        counts = self._category_counts.setdefault(event.phase, {})
        counts["other"] = counts.get("other", 0) + 1

    def _mark_context(self, event: TaskLogEvent) -> None:
        super()._mark_context(event)
        if event.raw_line_no is None:
            return
        categorized = self._categorized_ids.pop(
            (event.source, event.raw_line_no),
            None,
        )
        if categorized is None:
            return
        phase, category = categorized
        counts = self._category_counts.setdefault(phase, {})
        counts[category] = max(0, counts.get(category, 0) - 1)

    def _phase_summaries(self, phase: str) -> list[TaskLogEvent]:
        emitted = self._warning_summaries(phase)
        counts = self._category_counts.get(phase, {})
        stats = self._stats.get(phase)
        if not counts and stats is None and not emitted:
            return emitted
        parts = [
            f"{category} {counts[category]}"
            for category, _ in _PIP_CATEGORY_PATTERNS
            if counts.get(category)
        ]
        other = counts.get("other", 0)
        if other:
            parts.append(f"省略其他输出 {other} 行")
        if stats is not None:
            if stats.errors:
                parts.append(f"error {stats.errors} 行")
            if stats.warnings:
                parts.append(f"warning {stats.warnings} 行")
            if stats.context:
                parts.append(f"context {stats.context} 行")
        if not parts:
            parts.append("无普通输出")
        path_hint = f"；完整日志：{self._raw_log_path}" if self._raw_log_path else ""
        label = "下载" if phase == "download" else "安装" if phase == "install" else phase
        emitted.append(
            self._summary_event(
                phase,
                f"{label or 'pip'}摘要：" + "，".join(parts) + path_hint + "。",
            )
        )
        return emitted

    def _clear_phase_state(self, phase: str) -> None:
        super()._clear_phase_state(phase)
        self._category_counts.pop(phase, None)
        self._categorized_ids = {
            identity: value
            for identity, value in self._categorized_ids.items()
            if value[0] != phase
        }

    def _prune_unclassified_ids(self) -> None:
        super()._prune_unclassified_ids()
        retained = {
            (event.source, event.raw_line_no)
            for event in (*self._before, *self._tail)
            if event.raw_line_no is not None
        }
        self._categorized_ids = {
            identity: value
            for identity, value in self._categorized_ids.items()
            if identity in retained
        }


def web_policy_for(
    task_kind: str,
    source: str,
    raw_log_path: str | Path | None = None,
) -> RawLogPolicy:
    build_sources = {"xcodebuild", "altool", "transporter"}
    if task_kind in {"build", "release", "deploy"} and source in build_sources:
        return _BuildRawLogPolicy(source, raw_log_path)
    if task_kind == "update" and source == "pip":
        return _PipRawLogPolicy(raw_log_path)
    if source == "web-infrastructure":
        return _GenericRawLogPolicy(task_kind)
    return _PassthroughPolicy()


class CliSink:
    """Print progress and log lines to stdout."""

    def on_log(self, message: str, *, level: str = "info") -> None:
        print(message)

    def on_event(self, event: TaskLogEvent) -> None:
        if event.event_type not in {"phase", "milestone"} and event.message:
            self.on_log(event.message, level=event.level)

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

    def on_event(self, event: TaskLogEvent) -> None:
        if event.event_type != "phase" and event.message:
            self.on_log(event.message, level=event.level)

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

    def flush(self) -> bool:
        """Persist accumulated subprocess output in one database transaction."""
        if not self._pending_logs:
            return True
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
                    return False
            else:  # Compatibility with third-party TaskStore-like sinks.
                for message in messages:
                    self._store.append_log(self._task_id, message)
            return True
        except Exception as exc:  # noqa: BLE001 — keep install/update running
            self._requeue_logs(messages)
            self._flush_failures += 1
            print(f"⚠️  Task log flush failed: {exc}", file=sys.stderr)
            return False

    def _requeue_logs(self, messages: list[str]) -> None:
        # Prefer newest context; avoid unbounded growth if DB stays down.
        merged = messages + self._pending_logs
        self._pending_logs = merged[-self._MAX_PENDING_LOGS :]


class _RawLogCallback:
    def __init__(
        self,
        reporter: "TaskReporter",
        policy: RawLogPolicy,
        *,
        source: str,
        phase: str,
    ) -> None:
        self._reporter = reporter
        self._policy = policy
        self._source = source
        self._phase = phase
        self._raw_line_no = 0

    def __call__(self, message: str) -> None:
        self._raw_line_no += 1
        event = TaskLogEvent(
            event_type="raw",
            message=str(message).rstrip("\r\n"),
            level="info",
            task_kind=self._reporter.task_kind,
            phase=self._phase,
            source=self._source,
            raw_line_no=self._raw_line_no,
        )
        try:
            for emitted in self._policy.consume(event):
                self._reporter.emit(emitted)
        except Exception as exc:  # noqa: BLE001 — raw callbacks never abort subprocesses
            note_unclassified = getattr(self._policy, "note_unclassified", None)
            if callable(note_unclassified):
                try:
                    note_unclassified(event)
                except Exception:  # noqa: BLE001 — preserve original classifier failure
                    pass
            self._reporter.note_policy_error(
                source=self._source,
                phase=self._phase,
                raw_line_no=self._raw_line_no,
                exc=exc,
            )

    def application(self, message: str, *, level: str = "info") -> None:
        """Emit Spinner terminal text without feeding the raw-output policy."""
        self._reporter.log(message, level=level)

    def set_phase(self, phase: str) -> None:
        if phase == self._phase:
            return
        try:
            for emitted in self._policy.flush_phase(self._phase, closing=True):
                self._reporter.emit(emitted)
        except Exception as exc:  # noqa: BLE001
            self._reporter.note_policy_error(
                source=self._source,
                phase=self._phase,
                raw_line_no=self._raw_line_no,
                exc=exc,
            )
        self._phase = phase

    def finish(self, *, failed: bool) -> None:
        try:
            for emitted in self._policy.finish(failed=failed):
                self._reporter.emit(emitted)
        except Exception as exc:  # noqa: BLE001
            self._reporter.note_policy_error(
                source=self._source,
                phase=self._phase,
                raw_line_no=self._raw_line_no,
                exc=exc,
            )

    def flush(self) -> None:
        try:
            for emitted in self._policy.flush_phase(self._phase):
                self._reporter.emit(emitted)
        except Exception as exc:  # noqa: BLE001
            self._reporter.note_policy_error(
                source=self._source,
                phase=self._phase,
                raw_line_no=self._raw_line_no,
                exc=exc,
            )


class TaskReporter:
    """Map phased fine-grained progress to a monotonic global percentage."""

    def __init__(
        self,
        sinks: Sequence[ProgressSink] | None = None,
        *,
        verbose: bool = False,
        task_kind: str = "unknown",
        policy_factory: (
            Callable[[str, str, str | Path | None], RawLogPolicy] | None
        ) = None,
    ) -> None:
        self._sinks: list[ProgressSink] = list(sinks or [])
        self.verbose = verbose
        self.task_kind = task_kind
        self._policy_factory = policy_factory
        self._raw_callbacks: list[_RawLogCallback] = []
        self._milestones: dict[str, set[int]] = {}
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
            for callback in self._raw_callbacks:
                callback.set_phase(phase_id)
            self._phase_id = phase_id
            self._phase_label = phase_id
            self._phase_index = 1
            self._phase_start = 0.0
            self._phase_weight = 100.0
            self._emit_progress(msg="")
            self.emit(self._event("phase", phase_id))
            return

        idx = next((i for i, (pid, _, _) in enumerate(self._phases) if pid == phase_id), None)
        if idx is None:
            raise KeyError(f"unknown phase: {phase_id}")

        for callback in self._raw_callbacks:
            callback.set_phase(phase_id)
        self._phase_id = phase_id
        self._phase_label = self._phases[idx][2]
        self._phase_index = idx + 1  # 1-based
        self._phase_start = sum(w for _, w, _ in self._phases[:idx])
        self._phase_weight = self._phases[idx][1]
        # Phase start: effective current=0
        self._apply_pct(self._phase_start)
        self._emit_progress(msg="")
        self.emit(self._event("phase", self._phase_label or phase_id))

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
        event_level: TaskLogLevel
        if level in {"debug", "info", "warning", "error"}:
            event_level = level
        else:
            event_level = "info"
        event_type: TaskEventType = "error" if event_level == "error" else "operation"
        self.emit(
            TaskLogEvent(
                event_type=event_type,
                message=message,
                level=event_level,
                task_kind=self.task_kind,
                phase=self._phase_id,
            )
        )

    def emit(self, event: TaskLogEvent) -> None:
        for sink in self._sinks:
            try:
                on_event = getattr(sink, "on_event", None)
                if callable(on_event):
                    on_event(event)
                elif (
                    event.event_type not in {"phase", "milestone"}
                    and bool(event.message)
                ):
                    sink.on_log(event.message, level=event.level)
            except Exception:  # noqa: BLE001 — reporting must not abort task work
                _LOGGER.exception(
                    "Task log sink failed for task_kind=%s event_type=%s",
                    self.task_kind,
                    event.event_type,
                )

    def make_raw_log_callback(
        self,
        source: str | None = None,
        phase: str | None = None,
        raw_log_path: str | Path | None = None,
    ) -> RawLogCallback:
        """Return a callback suitable for a subprocess output tee.

        CLI reporters remain lossless. Web reporters classify only explicitly
        selected task-kind/source combinations.
        """
        resolved_source = source or self._default_raw_source()
        resolved_phase = phase if phase is not None else self._phase_id
        if self._policy_factory is None:
            policy = _PassthroughPolicy()
        else:
            try:
                policy = self._policy_factory(
                    self.task_kind,
                    resolved_source,
                    raw_log_path,
                )
            except Exception as exc:  # noqa: BLE001
                self.note_policy_error(
                    source=resolved_source,
                    phase=resolved_phase,
                    raw_line_no=0,
                    exc=exc,
                )
                policy = _PassthroughPolicy()
        callback = _RawLogCallback(
            self,
            policy,
            source=resolved_source,
            phase=resolved_phase,
        )
        self._raw_callbacks.append(callback)
        return callback

    def milestone(self, percent: int, *, message: str) -> None:
        if percent not in {0, 25, 50, 75, 100}:
            return
        seen = self._milestones.setdefault(self._phase_id, set())
        if percent in seen:
            return
        seen.add(percent)
        self.emit(self._event("milestone", message))

    def debug(self, message: str) -> None:
        if not self.verbose:
            return
        self.log(message, level="debug")

    def done(self, summary: str | None = None) -> None:
        self._pct = 100
        self._emit_progress(msg=summary or "")
        self.emit(self._event("success", summary or ""))

    def fail(self, message: str, *, detail: str | None = None) -> None:
        self.failed = True
        self.emit(self._event("failure", message, level="error"))
        if detail:
            self.emit(self._event("error", detail, level="error"))

    def flush(self, *, failed: bool | None = None) -> bool:
        """Flush buffered sinks before a task reaches a terminal state."""
        resolved_failed = self.failed if failed is None else failed
        for callback in self._raw_callbacks:
            callback.finish(failed=resolved_failed)
        succeeded = True
        for sink in self._sinks:
            flush = getattr(sink, "flush", None)
            if callable(flush):
                try:
                    if flush() is False:
                        succeeded = False
                except Exception:  # noqa: BLE001
                    succeeded = False
                    _LOGGER.exception("Task log sink flush failed for %s", self.task_kind)
        return succeeded

    def note_policy_error(
        self,
        *,
        source: str,
        phase: str,
        raw_line_no: int,
        exc: Exception,
    ) -> None:
        _LOGGER.exception(
            "Raw log policy failed source=%s phase=%s raw_line_no=%s: %s",
            source,
            phase,
            raw_line_no,
            exc,
        )

    def _event(
        self,
        event_type: TaskEventType,
        message: str,
        *,
        level: TaskLogLevel = "info",
    ) -> TaskLogEvent:
        return TaskLogEvent(
            event_type=event_type,
            message=message,
            level=level,
            task_kind=self.task_kind,
            phase=self._phase_id,
        )

    def _default_raw_source(self) -> str:
        if self.task_kind in {"build", "release", "deploy"}:
            return "altool" if self._phase_id == "upload" else "xcodebuild"
        if self.task_kind == "update":
            return "pip"
        return "subprocess"

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
            try:
                sink.on_progress(
                    pct=self._pct,
                    msg=msg,
                    phase=self._phase_id,
                    phase_label=self._phase_label,
                    phase_index=self._phase_index,
                    phase_total=phase_total,
                )
            except Exception:  # noqa: BLE001 — progress reporting is best effort
                _LOGGER.exception(
                    "Task progress sink failed for task_kind=%s phase=%s",
                    self.task_kind,
                    self._phase_id,
                )


def make_cli_reporter(*, verbose: bool = False) -> TaskReporter:
    return TaskReporter(sinks=[CliSink()], verbose=verbose, task_kind="cli")


def make_web_reporter(
    task_store: Any,
    task_id: str,
    task_kind: str,
    *,
    verbose: bool = False,
) -> TaskReporter:
    return TaskReporter(
        sinks=[TaskStoreSink(task_store, task_id)],
        verbose=verbose,
        task_kind=task_kind,
        policy_factory=web_policy_for,
    )
