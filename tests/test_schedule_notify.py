from pathlib import Path

import pytest

from asc.guard import GuardViolationError
from asc.schedule import (
    QueryOutcome,
    SendOutcome,
    combine_last_error,
    query_review,
    send_channels,
)


def _creds(tmp_path: Path, **overrides) -> dict:
    key = tmp_path / "AuthKey.p8"
    key.write_bytes(b"not-a-real-key")
    data = {
        "issuer_id": "issuer",
        "key_id": "KEYID",
        "key_file": str(key),
        "app_id": "123",
    }
    data.update(overrides)
    return data


class RecordingAPI:
    def __init__(self, versions=None, error=None):
        self.versions = [] if versions is None else versions
        self.error = error
        self.calls = []

    def _get_paginated_data(self, path, **params):
        self.calls.append((path, params))
        if self.error is not None:
            raise self.error
        return self.versions


def _factory(api):
    created = []

    def factory(issuer_id, key_id, key_file):
        created.append((issuer_id, key_id, key_file))
        return api

    factory.created = created
    return factory


def test_query_calls_paginated_ios_versions_once(tmp_path: Path):
    api = RecordingAPI([
        {"id": "b", "attributes": {"appStoreState": "IN_REVIEW", "versionString": "1.2.3"}},
    ])
    factory = _factory(api)
    outcome = query_review(
        "myapp",
        profile_lookup=lambda name: _creds(tmp_path),
        api_factory=factory,
        guard=lambda profile, creds: None,
    )
    assert factory.created
    assert api.calls == [("/v1/apps/123/appStoreVersions", {"filter[platform]": "IOS"})]
    assert outcome.last_result == "1.2.3 审核中"
    assert outcome.query_error == ""
    assert outcome.snapshot is not None


def test_prepare_for_submission_is_not_in_review(tmp_path: Path):
    api = RecordingAPI([
        {"id": "a", "attributes": {"appStoreState": "PREPARE_FOR_SUBMISSION", "versionString": "1.0.0"}},
    ])
    outcome = query_review(
        "myapp",
        profile_lookup=lambda name: _creds(tmp_path),
        api_factory=_factory(api),
        guard=lambda profile, creds: None,
    )
    assert outcome.last_result == "当前无在审版本；暂无已上架版本"


def test_api_error_is_not_reported_as_no_review(tmp_path: Path):
    api = RecordingAPI(error=Exception("API 错误 [500] token=abc"))
    outcome = query_review(
        "myapp",
        profile_lookup=lambda name: _creds(tmp_path),
        api_factory=_factory(api),
        guard=lambda profile, creds: None,
    )
    assert outcome.last_result == "检查失败"
    assert outcome.snapshot is None
    assert "token=[redacted]" in outcome.query_error
    assert "当前无在审版本" not in outcome.query_error
    assert "当前无在审版本" not in outcome.last_result


@pytest.mark.parametrize(
    "lookup",
    [
        lambda tmp_path: None,
        lambda tmp_path: _creds(tmp_path, app_id=""),
        lambda tmp_path: _creds(tmp_path, key_file=str(tmp_path / "missing.p8")),
    ],
)
def test_missing_profile_and_incomplete_credentials_skip_api(tmp_path: Path, lookup):
    factory = _factory(RecordingAPI())
    found = lookup(tmp_path)

    def profile_lookup(name):
        return found

    outcome = query_review(
        "myapp",
        profile_lookup=profile_lookup,
        api_factory=factory,
        guard=lambda profile, creds: (_ for _ in ()).throw(AssertionError("guard")),
    )
    assert factory.created == []
    assert outcome.last_result == "检查失败"
    if found is None:
        assert outcome.query_error == "profile 不存在"
    else:
        assert outcome.query_error == "凭证不完整"


def test_guard_violation_is_clamped(tmp_path: Path):
    factory = _factory(RecordingAPI())

    def guard(profile, creds):
        raise GuardViolationError("冲突 token=abc")

    outcome = query_review(
        "myapp",
        profile_lookup=lambda name: _creds(tmp_path),
        api_factory=factory,
        guard=guard,
    )
    assert factory.created == []
    assert outcome.last_result == "检查失败"
    assert "冲突" in outcome.query_error
    assert "token=[redacted]" in outcome.query_error


def test_default_guard_passes_noninteractive_keywords(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    seen = {}

    class FakeGuard:
        def is_enabled(self):
            return True

        def check_and_enforce(self, *args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs

    monkeypatch.setattr("asc.guard.Guard", FakeGuard)
    api = RecordingAPI([])
    query_review(
        "myapp",
        profile_lookup=lambda name: _creds(tmp_path),
        api_factory=_factory(api),
    )
    assert seen["kwargs"]["interactive"] is False
    assert seen["kwargs"]["app_name"] == "myapp"
    assert seen["args"][0] == "123"
    assert api.calls


def test_missing_webhook_does_not_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ASC_WEBHOOK_CONFIG_PATH", str(tmp_path / "missing.toml"))

    def sender(provider, config, text):
        raise AssertionError("sender")

    outcome = send_channels("hello", sender=sender)
    assert outcome.attempted is False
    assert outcome.config_invalid is False
    assert combine_last_error("", outcome) == ""


def test_enabled_webhook_ignores_notify_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "webhook.toml"
    path.write_text(
        "\n".join([
            "enabled = true",
            "notify_kinds = []",
            "notify_statuses = []",
            "",
            "[providers.feishu]",
            "enabled = true",
            'url = "https://example.com/hook"',
            'secret = ""',
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("ASC_WEBHOOK_CONFIG_PATH", str(path))
    calls = []

    def sender(provider, config, text):
        calls.append((provider, text))
        return {"provider": provider, "ok": True}

    outcome = send_channels("状态", sender=sender)
    assert calls == [("feishu", "状态")]
    assert outcome.attempted is True
    assert outcome.failures == []


def test_partial_provider_failures_continue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "webhook.toml"
    path.write_text(
        "\n".join([
            "enabled = true",
            "[providers.feishu]",
            "enabled = true",
            'url = "https://example.com/feishu"',
            "[providers.wecom]",
            "enabled = true",
            'url = "https://example.com/wecom"',
            "[providers.dingtalk]",
            "enabled = true",
            'url = "https://example.com/dingtalk"',
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("ASC_WEBHOOK_CONFIG_PATH", str(path))
    calls = []

    def sender(provider, config, text):
        calls.append(provider)
        if provider == "wecom":
            return {"provider": provider, "ok": True}
        error = "HTTP 500" if provider == "feishu" else "HTTP 502"
        return {"provider": provider, "ok": False, "error": error}

    outcome = send_channels("状态", sender=sender)
    assert calls == ["feishu", "wecom", "dingtalk"]
    assert outcome.failures == ["feishu HTTP 500", "dingtalk HTTP 502"]


def test_combine_last_error_prefixes():
    invalid = SendOutcome(True, [], False)
    failed = SendOutcome(False, ["feishu HTTP 500"], True)
    assert combine_last_error("凭证不完整", invalid) == "凭证不完整；通知配置无效"
    assert combine_last_error("凭证不完整", failed) == "凭证不完整；通知发送失败：feishu HTTP 500"


def test_corrupt_webhook_skips_sender(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "webhook.toml"
    path.write_text("enabled = [\n", encoding="utf-8")
    monkeypatch.setenv("ASC_WEBHOOK_CONFIG_PATH", str(path))

    def sender(provider, config, text):
        raise AssertionError("sender")

    outcome = send_channels("状态", sender=sender)
    assert outcome.config_invalid is True
    assert outcome.attempted is False
