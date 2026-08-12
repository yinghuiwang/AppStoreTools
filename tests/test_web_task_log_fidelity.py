from __future__ import annotations

import inspect
from threading import Event

import pytest

from asc.progress import ProcessCanceled
from asc.reporting import make_web_reporter
from asc.web.task_runner import _execute_task, finalize_task
from asc.web.tasks import TaskStatus


class MockTaskStore:
    def __init__(self) -> None:
        self.logs: list[tuple[str, str]] = []

    def append_logs(self, task_id: str, lines: list[str]) -> bool:
        self.logs.extend((task_id, line) for line in lines)
        return True

    def set_progress(self, *args, **kwargs) -> bool:
        return True


@pytest.mark.parametrize(
    ("task_kind", "message", "identifier"),
    [
        ("metadata", "✅ locale=en-US metadata updated", "en-US"),
        ("metadata", "❌ locale=ja metadata failed: denied", "ja"),
        ("metadata", "✅ screenshot=01_home.png uploaded", "01_home.png"),
        ("iap", "✅ product=coins_100 created", "coins_100"),
        ("iap", "⏭ subscription=pro_monthly exists", "pro_monthly"),
        ("iap", "❌ localization=fr-FR product=coins_100 failed", "fr-FR"),
        ("whats-new", "✅ locale=de-DE uploaded", "de-DE"),
        ("whats-new-translate", "❌ locale=ko translation failed", "ko"),
        ("urls", "✅ locale=pt-BR supportUrl updated", "pt-BR"),
        ("iap-review-screenshots", "✅ product=coins_100 review.png", "review.png"),
        (
            "listing-pull-screenshots",
            "✅ locale=es-ES screenshot=01_store.png",
            "01_store.png",
        ),
        ("update", "❌ pip install failed for commit abc1234", "abc1234"),
        ("build", "❌ archive failed: signing profile missing", "signing profile"),
        ("deploy", "❌ upload failed: Example.ipa", "Example.ipa"),
        ("release", "❌ export failed: ExportOptions.plist", "ExportOptions.plist"),
    ],
)
def test_business_object_logs_are_preserved(task_kind, message, identifier):
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-1", task_kind)

    reporter.log(message, level="error" if "❌" in message else "info")
    reporter.flush()

    persisted = "\n".join(line for _, line in store.logs)
    assert identifier in persisted


def test_different_business_objects_are_not_merged():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-1", "metadata")

    reporter.log("retry 429 endpoint=/v1/localizations locale=en-US")
    reporter.log("retry 429 endpoint=/v1/localizations locale=ja")
    reporter.flush()

    assert [line for _, line in store.logs] == [
        "retry 429 endpoint=/v1/localizations locale=en-US",
        "retry 429 endpoint=/v1/localizations locale=ja",
    ]


def test_make_web_reporter_requires_explicit_task_kind():
    parameter = inspect.signature(make_web_reporter).parameters["task_kind"]
    assert parameter.default is inspect.Parameter.empty


def test_task_store_sink_omits_phase_but_keeps_readable_milestone_events():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-1", "deploy")

    reporter.phase("upload")
    reporter.milestone(25, message="internal progress milestone")
    reporter.log("✅ file=Example.ipa uploaded")
    reporter.flush()

    assert [line for _, line in store.logs] == [
        "internal progress milestone",
        "✅ file=Example.ipa uploaded",
    ]


class RecordingReporter:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls
        self.failed = False

    def flush(self, *, failed: bool | None = None) -> None:
        self.calls.append(("flush_reporter", failed))

    def fail(self, message: str, *, detail: str | None = None) -> None:
        self.failed = True
        self.calls.append(("fail", message, detail))

    def log(self, message: str, *, level: str = "info") -> None:
        self.calls.append(("log", level, message))


class RecordingTaskStore:
    def __init__(
        self,
        *,
        fail_result: bool = False,
        status_failures: int = 0,
        path: str = "/tmp/tasks.db",
    ) -> None:
        self.calls: list[tuple] = []
        self.status = TaskStatus.PENDING
        self.result: dict | None = None
        self._event = Event()
        self._db_path = path
        self.fail_result = fail_result
        self.status_failures = status_failures

    def get_state(self, task_id: str) -> dict:
        return {"status": self.status, "result": self.result}

    get = get_state

    def is_cancel_requested(self, task_id: str) -> bool:
        return False

    def cancel_event(self, task_id: str) -> Event:
        return self._event

    def set_result(self, task_id: str, result: dict) -> bool:
        self.calls.append(("set_result", task_id, result))
        if self.fail_result:
            raise RuntimeError("database locked")
        self.result = result
        return True

    def set_result_if_nonterminal(
        self,
        task_id: str,
        result: dict,
        *,
        wait: bool = True,
    ) -> bool:
        del wait
        if self.status in {
            TaskStatus.DONE,
            TaskStatus.ERROR,
            TaskStatus.CANCELED,
        }:
            return False
        return self.set_result(task_id, result)

    def set_status(self, task_id: str, status: TaskStatus) -> bool:
        self.calls.append(("set_status", task_id, status))
        if status in {TaskStatus.DONE, TaskStatus.ERROR, TaskStatus.CANCELED}:
            if self.status_failures > 0:
                self.status_failures -= 1
                raise TimeoutError("writer queue timed out")
        self.status = status
        return True


@pytest.mark.parametrize(
    ("outcome", "status", "expected_result"),
    [
        ("success-none", TaskStatus.DONE, {"success": True}),
        ("failure", TaskStatus.ERROR, {"success": False, "error": "boom"}),
        ("cancel", TaskStatus.CANCELED, {"success": False, "canceled": True}),
    ],
)
def test_terminal_result_is_nonempty_before_status(
    outcome, status, expected_result, monkeypatch
):
    store = RecordingTaskStore()
    reporter = RecordingReporter(store.calls)
    monkeypatch.setattr(
        "asc.web.task_runner.make_web_reporter",
        lambda *args, **kwargs: reporter,
    )

    def run(_reporter, _cancel_event):
        if outcome == "failure":
            raise RuntimeError("boom")
        if outcome == "cancel":
            raise ProcessCanceled("stopped")
        return None

    _execute_task(store, "task-1", "metadata", run, verbose=False)

    result_index, result_call = next(
        (index, call)
        for index, call in enumerate(store.calls)
        if call[0] == "set_result" and call[1] == "task-1"
    )
    persisted_result = result_call[2]
    for key, value in expected_result.items():
        assert persisted_result[key] == value
    assert persisted_result["_asc_terminal_recovery"]["status"] == status.value
    status_index = store.calls.index(("set_status", "task-1", status))
    flush_index = max(
        index
        for index, call in enumerate(store.calls[:result_index])
        if call[0] == "flush_reporter"
    )
    assert flush_index < result_index < status_index


def test_terminal_db_failure_is_visible_and_never_fakes_success(capsys, monkeypatch):
    store = RecordingTaskStore(fail_result=True, path="/tmp/tasks.db")
    reporter = RecordingReporter(store.calls)
    monkeypatch.setattr(
        "asc.web.task_runner.make_web_reporter",
        lambda *args, **kwargs: reporter,
    )

    _execute_task(store, "task-7", "urls", lambda *_: None, verbose=False)

    err = capsys.readouterr().err
    assert "task-7" in err
    assert "set_result" in err
    assert "/tmp/tasks.db" in err
    assert ("set_status", "task-7", TaskStatus.DONE) not in store.calls


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (
            TaskStatus.DONE,
            {
                "success": True,
                "uploaded": 2,
                "skipped": 1,
                "failed": 0,
                "failures": [],
            },
        ),
        (
            TaskStatus.ERROR,
            {
                "success": False,
                "uploaded": 1,
                "skipped": 2,
                "failed": 1,
                "failures": [{"productId": "coins_100", "error": "denied"}],
            },
        ),
    ],
)
def test_finalize_does_not_requeue_deterministic_status_failure(status, payload):
    store = RecordingTaskStore(status_failures=1)
    store.status = TaskStatus.RUNNING
    reporter = RecordingReporter(store.calls)

    assert finalize_task(store, reporter, "task-1", status, payload) is False

    assert store.status == TaskStatus.RUNNING
    assert store.result is not None
    assert store.result["uploaded"] == payload["uploaded"]
    assert store.result["failures"] == payload["failures"]
    assert "terminal_write_uncertainty" in store.result
    assert [call[2] for call in store.calls if call[0] == "set_status"] == [
        status,
    ]


def test_finalize_status_failure_preserves_payload_with_write_uncertainty():
    payload = {
        "success": False,
        "uploaded": 1,
        "skipped": 2,
        "failed": 1,
        "failures": [{"productId": "coins_100", "error": "denied"}],
    }
    store = RecordingTaskStore(status_failures=10)
    store.status = TaskStatus.RUNNING
    reporter = RecordingReporter(store.calls)

    assert finalize_task(
        store, reporter, "task-iap", TaskStatus.ERROR, payload
    ) is False

    assert store.status == TaskStatus.RUNNING
    assert store.result is not None
    assert store.result["uploaded"] == 1
    assert store.result["skipped"] == 2
    assert store.result["failed"] == 1
    assert store.result["failures"] == payload["failures"]
    assert "terminal_write_uncertainty" in store.result
    assert len([call for call in store.calls if call[0] == "set_status"]) == 1
    assert not any(
        call == ("set_status", "task-iap", TaskStatus.DONE)
        for call in store.calls
    )


def test_recording_store_models_nonterminal_result_guard():
    store = RecordingTaskStore()
    canceled = {"success": False, "canceled": True}
    store.status = TaskStatus.CANCELED
    store.result = canceled

    assert store.set_result_if_nonterminal(
        "task-1",
        {"success": True},
        wait=False,
    ) is False
    assert store.result == canceled


def test_finalize_is_idempotent_for_matching_terminal_task():
    payload = {"success": True, "uploaded": 1}
    store = RecordingTaskStore()
    store.status = TaskStatus.DONE
    store.result = payload
    reporter = RecordingReporter(store.calls)

    assert finalize_task(
        store, reporter, "task-1", TaskStatus.DONE, payload
    ) is True

    assert not any(call[0] in {"set_result", "set_status"} for call in store.calls)
    assert store.calls == [("flush_reporter", False)]


def test_finalize_outcome_states_for_commit_and_blocked_paths():
    from asc.web.task_runner import TerminalWriteState, finalize_task_outcome

    store = RecordingTaskStore()
    store.status = TaskStatus.RUNNING
    reporter = RecordingReporter(store.calls)
    committed = finalize_task_outcome(
        store, reporter, "task-ok", TaskStatus.DONE, {"success": True}
    )
    assert committed.state is TerminalWriteState.COMMITTED
    assert committed.persisted is True
    assert committed.blocked is False
    assert bool(committed) is True

    blocked_store = RecordingTaskStore(fail_result=True)
    blocked_store.status = TaskStatus.RUNNING
    blocked = finalize_task_outcome(
        blocked_store,
        RecordingReporter(blocked_store.calls),
        "task-blocked",
        TaskStatus.DONE,
        {"success": True},
    )
    assert blocked.state is TerminalWriteState.BLOCKED
    assert blocked.blocked is True
    assert bool(blocked) is False


def test_finalize_done_flushes_failed_raw_context_when_reporter_failed():
    store = RecordingTaskStore()
    store.status = TaskStatus.RUNNING
    reporter = RecordingReporter(store.calls)
    reporter.failed = True

    assert finalize_task(
        store, reporter, "task-1", TaskStatus.DONE, {"success": True}
    ) is True

    assert store.calls[0] == ("flush_reporter", True)


def test_flush_failure_blocks_terminal_write(capsys):
    class FailingFlushReporter(RecordingReporter):
        def flush(self, *, failed: bool | None = None) -> None:
            raise RuntimeError("flush exploded")

    store = RecordingTaskStore(path="/tmp/tasks.db")
    store.status = TaskStatus.RUNNING
    reporter = FailingFlushReporter(store.calls)

    assert finalize_task(
        store, reporter, "task-flush", TaskStatus.DONE, {"success": True}
    ) is False

    assert store.status == TaskStatus.RUNNING
    assert store.result is None
    assert not any(call[0] in {"set_result", "set_status"} for call in store.calls)
    err = capsys.readouterr().err
    assert "task-flush" in err
    assert "operation=flush" in err
    assert "/tmp/tasks.db" in err


def test_execute_flushes_late_exception_logs_without_rewriting_terminal(monkeypatch):
    store = RecordingTaskStore()
    reporter = RecordingReporter(store.calls)
    monkeypatch.setattr(
        "asc.web.task_runner.make_web_reporter",
        lambda *args, **kwargs: reporter,
    )

    def run(_reporter, _cancel_event):
        store.result = {"success": True, "side_effect": "scheduled"}
        store.status = TaskStatus.DONE
        reporter.log("restart side effect failed", level="error")
        raise RuntimeError("restart exploded")

    _execute_task(store, "task-late", "update", run, verbose=False)

    assert store.status == TaskStatus.DONE
    assert store.result == {"success": True, "side_effect": "scheduled"}
    assert any("Traceback" in str(call) for call in store.calls)
    assert store.calls[-1][0] == "flush_reporter"
    assert not any(
        call[0] == "set_status" and call[2] == TaskStatus.ERROR
        for call in store.calls
    )


@pytest.mark.parametrize(
    ("task_kind", "source", "phase", "message", "identifier"),
    [
        (
            "build",
            "xcodebuild",
            "archive",
            "error: archive failed file=Demo.xcarchive",
            "Demo.xcarchive",
        ),
        (
            "deploy",
            "altool",
            "upload",
            "ERROR: upload failed file=Demo.ipa",
            "Demo.ipa",
        ),
        (
            "release",
            "xcodebuild",
            "export",
            "error: export failed file=ExportOptions.plist",
            "ExportOptions.plist",
        ),
        (
            "update",
            "pip",
            "install",
            "ERROR: install failed commit=abc1234",
            "abc1234",
        ),
    ],
)
def test_web_raw_policy_preserves_business_error_identity(
    task_kind, source, phase, message, identifier
):
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-raw", task_kind)
    callback = reporter.make_raw_log_callback(source, phase)

    callback(message)
    reporter.flush(failed=True)

    assert identifier in "\n".join(line for _, line in store.logs)


@pytest.mark.parametrize(
    ("message", "identity"),
    [
        (
            "poll endpoint=/v1/builds locale=en-US status=PROCESSING",
            "locale=en-US",
        ),
        (
            "pagination success endpoint=/v1/localizations product=coins_100 page=2",
            "product=coins_100",
        ),
        (
            "HTTP retry endpoint=/v1/localizations locale=ja status=429",
            "locale=ja",
        ),
        (
            "progress endpoint=/v1/assets file=01_home.png percent=12",
            "file=01_home.png",
        ),
        (
            "debug note endpoint=/v1/apps no business object",
            "endpoint=/v1/apps",
        ),
    ],
)
def test_generic_raw_policy_aggregates_infrastructure_by_business_identity(
    message, identity
):
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-generic", "metadata")
    callback = reporter.make_raw_log_callback("web-infrastructure", "locales")

    callback(message)
    callback(message)
    reporter.flush()

    lines = [line for _, line in store.logs]
    assert len([line for line in lines if identity in line]) == 1
    assert any("重复 1 次" in line and identity in line for line in lines)


def test_generic_raw_policy_does_not_merge_distinct_business_objects():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-generic", "metadata")
    callback = reporter.make_raw_log_callback("web-infrastructure", "locales")

    callback("HTTP retry endpoint=/v1/localizations locale=en-US status=429")
    callback("HTTP retry endpoint=/v1/localizations locale=ja status=429")
    reporter.flush()

    persisted = "\n".join(line for _, line in store.logs)
    assert "locale=en-US" in persisted
    assert "locale=ja" in persisted


def test_generic_raw_policy_key_separates_phase_source_category_and_endpoint():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-generic", "metadata")
    http = reporter.make_raw_log_callback("web-infrastructure", "locales")
    worker = reporter.make_raw_log_callback("worker", "locales")

    http("poll endpoint=/v1/apps locale=en-US status=WAITING")
    http("HTTP retry endpoint=/v1/apps locale=en-US status=429")
    http("poll endpoint=/v1/localizations locale=en-US status=WAITING")
    worker("poll endpoint=/v1/apps locale=en-US status=WAITING")
    http.set_phase("screenshots")
    http("poll endpoint=/v1/apps locale=en-US status=WAITING")
    reporter.flush()

    lines = [line for _, line in store.logs]
    assert len(lines) == 5
    assert sum("endpoint=/v1/apps" in line for line in lines) == 4
    assert sum("endpoint=/v1/localizations" in line for line in lines) == 1


def test_generic_policy_is_explicit_and_default_raw_remains_passthrough():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-default", "metadata")
    callback = reporter.make_raw_log_callback("http", "locales")
    message = "poll endpoint=/v1/apps locale=en-US status=WAITING"

    callback(message)
    callback(message)
    reporter.flush()

    assert [line for _, line in store.logs] == [message, message]


def test_generic_policy_bounds_high_cardinality_groups_with_overflow_summary():
    store = MockTaskStore()
    reporter = make_web_reporter(store, "task-generic", "metadata")
    callback = reporter.make_raw_log_callback("web-infrastructure", "poll")

    for index in range(100_000):
        callback(f"poll endpoint=/v1/apps asset=asset-{index} status=WAITING")

    assert len(callback._policy._groups) <= 256
    assert len(callback._policy._before) <= 5
    assert len(callback._policy._tail) <= 20
    assert len(callback._policy._phase_order) <= 1
    assert len(callback._policy._visible_ids) <= 64
    reporter.flush()
    assert any("overflow" in line.lower() for _, line in store.logs)
    assert len(callback._policy._groups) == 0
    assert callback._policy._phase_order == []
    assert callback._policy._overflow_count == 0
    assert len(callback._policy._before) == 0
    assert len(callback._policy._tail) == 0
