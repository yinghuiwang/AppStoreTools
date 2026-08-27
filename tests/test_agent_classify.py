from __future__ import annotations

import json

from asc.web.agent_classify import classify_task_failure
from asc.web.tasks import TaskStatus, TaskStore


def _failed_task(tmp_path, message: str, *, result=None):
    store = TaskStore(tmp_path / "t.db")
    task_id = store.create("metadata", profile="myapp")
    store.append_log(task_id, message)
    if result is not None:
        store.set_result(task_id, result)
    store.set_status(task_id, TaskStatus.ERROR)
    return store, task_id


def _assert_classified(out: dict, code: str) -> None:
    assert out["ok"] is True
    assert out["code"] == code
    assert out["hint"]
    assert out["evidence"]
    blob = json.dumps(out, ensure_ascii=False)
    assert "BEGIN PRIVATE" not in blob
    assert "sk-secret" not in blob
    assert "api_key=" not in blob.lower() or "[redacted]" in blob.lower()


def test_classify_no_editable_version_prepare(tmp_path):
    store, task_id = _failed_task(
        tmp_path, "version state must be PREPARE_FOR_SUBMISSION"
    )
    _assert_classified(classify_task_failure(store, task_id), "no_editable_version")
    store.close()


def test_classify_no_editable_version_chinese(tmp_path):
    store, task_id = _failed_task(tmp_path, "当前版本不可编辑，没有可提交的版本")
    _assert_classified(classify_task_failure(store, task_id), "no_editable_version")
    store.close()


def test_classify_screenshot_size(tmp_path):
    store, task_id = _failed_task(
        tmp_path, "unmapped screenshot display type UNKNOWN 2778 pixel 尺寸"
    )
    _assert_classified(classify_task_failure(store, task_id), "screenshot_size")
    store.close()


def test_classify_territory_code(tmp_path):
    store, task_id = _failed_task(
        tmp_path, "baseTerritory must be 3-letter like USA, not US"
    )
    _assert_classified(classify_task_failure(store, task_id), "territory_code")
    store.close()


def test_classify_create_only_skip(tmp_path):
    store, task_id = _failed_task(
        tmp_path, "create-only: subscription already exists, skipped 已存在"
    )
    _assert_classified(classify_task_failure(store, task_id), "create_only_skip")
    store.close()


def test_classify_rate_limited(tmp_path):
    store, task_id = _failed_task(tmp_path, "HTTP 429 rate limit Retry-After: 8")
    _assert_classified(classify_task_failure(store, task_id), "rate_limited")
    store.close()


def test_classify_auth(tmp_path):
    store, task_id = _failed_task(tmp_path, "401 unauthorized: invalid token")
    _assert_classified(classify_task_failure(store, task_id), "auth")
    store.close()


def test_classify_unknown_fallback(tmp_path):
    store, task_id = _failed_task(tmp_path, "unexpected network glitch")
    _assert_classified(classify_task_failure(store, task_id), "unknown")
    store.close()


def test_classify_first_match_wins(tmp_path):
    store, task_id = _failed_task(
        tmp_path, "no editable version then later HTTP 429 rate limit"
    )
    assert classify_task_failure(store, task_id)["code"] == "no_editable_version"
    store.close()


def test_classify_reads_result_and_redacts_secrets(tmp_path):
    store, task_id = _failed_task(
        tmp_path,
        "api_key=sk-secret -----BEGIN PRIVATE KEY-----\nMIIHide\n-----END PRIVATE KEY-----",
        result={"error": "403 forbidden"},
    )
    out = classify_task_failure(store, task_id)
    _assert_classified(out, "auth")
    blob = json.dumps(out, ensure_ascii=False)
    assert "MIIHide" not in blob
    store.close()


def test_classify_hint_uses_lang_fallbacks(tmp_path):
    store, task_id = _failed_task(tmp_path, "HTTP 429 rate limit")
    en = classify_task_failure(store, task_id, lang="en")
    zh = classify_task_failure(store, task_id, lang="zh")
    assert en["code"] == zh["code"] == "rate_limited"
    assert en["hint"] != zh["hint"]
    store.close()


def test_classify_missing_task_is_unknown(tmp_path):
    store = TaskStore(tmp_path / "t.db")
    out = classify_task_failure(store, "missing-id")
    assert out["ok"] is True
    assert out["code"] == "unknown"
    store.close()
