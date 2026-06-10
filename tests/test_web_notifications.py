from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest

from asc.web import notifications
from asc.web import webhook_clients
from asc.web.tasks import TaskStatus, TaskStore


def test_default_notify_constants():
    assert notifications.DEFAULT_NOTIFY_KINDS == [
        "metadata",
        "build",
        "whats-new",
        "iap",
        "urls",
    ]
    assert notifications.DEFAULT_NOTIFY_STATUSES == ["done", "error", "canceled"]


@pytest.fixture
def webhook_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "webhook.toml"
    monkeypatch.setenv("ASC_WEBHOOK_CONFIG_PATH", str(path))
    return path


def test_load_webhook_config_defaults_when_missing(webhook_path: Path):
    config = notifications.load_webhook_config()

    assert config["enabled"] is False
    assert config["notify_statuses"] == ["done", "error", "canceled"]
    assert config["notify_kinds"] == ["metadata", "build", "whats-new", "iap", "urls"]
    assert sorted(config["providers"]) == ["dingtalk", "feishu", "wecom"]
    assert config["providers"]["feishu"]["enabled"] is False
    assert config["providers"]["feishu"]["url"] == ""
    assert config["providers"]["feishu"]["secret"] == ""


def test_load_webhook_config_defaults_for_malformed_toml(webhook_path: Path):
    webhook_path.write_text("[providers.feishu\nenabled = true\n", encoding="utf-8")

    config = notifications.load_webhook_config()

    assert config == notifications.default_webhook_config()


def test_normalize_webhook_config_rejects_malformed_bool_values():
    config = notifications.normalize_webhook_config({
        "enabled": "false",
        "providers": {
            "feishu": {
                "enabled": "false",
            },
        },
    })

    assert config["enabled"] is False
    assert config["providers"]["feishu"]["enabled"] is False


def test_normalize_webhook_config_rejects_malformed_provider_strings():
    config = notifications.normalize_webhook_config({
        "providers": {
            "feishu": {
                "url": 123,
                "secret": ["secret"],
            },
            "wecom": {
                "url": "  https://wecom.example/hook  ",
                "secret": "wc-secret",
            },
        },
    })

    assert config["providers"]["feishu"]["url"] == ""
    assert config["providers"]["feishu"]["secret"] == ""
    assert config["providers"]["wecom"]["url"] == "https://wecom.example/hook"
    assert config["providers"]["wecom"]["secret"] == "wc-secret"


def test_save_and_load_webhook_config(webhook_path: Path):
    payload = {
        "enabled": True,
        "notify_statuses": ["done", "error"],
        "notify_kinds": ["build", "metadata"],
        "providers": {
            "feishu": {"enabled": True, "url": "https://feishu.example/hook", "secret": "fs"},
            "wecom": {"enabled": False, "url": "", "secret": ""},
            "dingtalk": {"enabled": True, "url": "https://ding.example/hook", "secret": "dt"},
        },
    }

    saved = notifications.save_webhook_config(payload)
    loaded = notifications.load_webhook_config()

    assert saved == loaded
    assert loaded["enabled"] is True
    assert loaded["notify_statuses"] == ["done", "error"]
    assert loaded["notify_kinds"] == ["build", "metadata"]
    assert loaded["providers"]["feishu"]["secret"] == "fs"
    assert loaded["providers"]["dingtalk"]["url"] == "https://ding.example/hook"


def test_public_webhook_config_masks_secrets(webhook_path: Path):
    notifications.save_webhook_config({
        "enabled": True,
        "notify_statuses": ["done"],
        "notify_kinds": ["build"],
        "providers": {
            "feishu": {"enabled": True, "url": "https://feishu.example/hook", "secret": "fs-secret"},
            "wecom": {"enabled": False, "url": "", "secret": ""},
            "dingtalk": {"enabled": True, "url": "https://ding.example/hook", "secret": "dt-secret"},
        },
    })

    public = notifications.load_public_webhook_config()

    assert public["providers"]["feishu"]["secret"] == ""
    assert public["providers"]["feishu"]["has_secret"] is True
    assert public["providers"]["wecom"]["has_secret"] is False
    assert public["providers"]["dingtalk"]["secret"] == ""


def test_save_webhook_config_preserves_existing_secret_when_blank(webhook_path: Path):
    notifications.save_webhook_config({
        "enabled": True,
        "notify_statuses": ["done"],
        "notify_kinds": ["build"],
        "providers": {
            "feishu": {"enabled": True, "url": "https://feishu.example/hook", "secret": "old-secret"},
            "wecom": {"enabled": False, "url": "", "secret": ""},
            "dingtalk": {"enabled": False, "url": "", "secret": ""},
        },
    })

    notifications.save_webhook_config({
        "enabled": True,
        "notify_statuses": ["done"],
        "notify_kinds": ["build"],
        "providers": {
            "feishu": {"enabled": True, "url": "https://feishu.example/new", "secret": ""},
            "wecom": {"enabled": False, "url": "", "secret": ""},
            "dingtalk": {"enabled": False, "url": "", "secret": ""},
        },
    }, preserve_blank_secrets=True)

    loaded = notifications.load_webhook_config()
    assert loaded["providers"]["feishu"]["url"] == "https://feishu.example/new"
    assert loaded["providers"]["feishu"]["secret"] == "old-secret"


def test_feishu_signature_payload(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(webhook_clients.time, "time", lambda: 1700000000)

    payload = webhook_clients.build_feishu_payload("hello", "secret")

    assert payload["msg_type"] == "text"
    assert payload["content"] == {"text": "hello"}
    assert payload["timestamp"] == "1700000000"
    assert payload["sign"] == "fiWS2+gh28DOydAv7hzONH/mDn9+b1Y4Y5ivXWXy8vA="


def test_wecom_payload_uses_markdown():
    payload = webhook_clients.build_wecom_payload("hello")

    assert payload == {"msgtype": "markdown", "markdown": {"content": "hello"}}


def test_dingtalk_signature_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(webhook_clients.time, "time", lambda: 1700000000)

    url = webhook_clients.build_dingtalk_url("https://ding.example/hook?access_token=abc", "secret")
    query = parse_qs(urlparse(url).query)

    assert "timestamp=1700000000000" in url
    assert query["sign"] == ["OuzzJR5+xZ4/EYwqtNt6sMYZQMTa/HEGvc9miJe7XzY="]
    assert "sign=OuzzJR5%2BxZ4%2FEYwqtNt6sMYZQMTa%2FHEGvc9miJe7XzY%3D" in url


def test_dingtalk_url_without_secret_is_unchanged():
    url = "https://ding.example/hook?access_token=abc"

    assert webhook_clients.build_dingtalk_url(url, "") == url


def test_dingtalk_signature_url_separators(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(webhook_clients.time, "time", lambda: 1700000000)

    no_query_url = webhook_clients.build_dingtalk_url("https://ding.example/hook", "secret")
    existing_query_url = webhook_clients.build_dingtalk_url(
        "https://ding.example/hook?access_token=abc",
        "secret",
    )
    trailing_question_url = webhook_clients.build_dingtalk_url("https://ding.example/hook?", "secret")
    trailing_ampersand_url = webhook_clients.build_dingtalk_url(
        "https://ding.example/hook?access_token=abc&",
        "secret",
    )

    assert no_query_url.startswith("https://ding.example/hook?timestamp=1700000000000&sign=")
    assert existing_query_url.startswith(
        "https://ding.example/hook?access_token=abc&timestamp=1700000000000&sign="
    )
    assert trailing_question_url.startswith("https://ding.example/hook?timestamp=1700000000000&sign=")
    assert trailing_ampersand_url.startswith(
        "https://ding.example/hook?access_token=abc&timestamp=1700000000000&sign="
    )
    assert "?&" not in trailing_question_url
    assert "&&" not in trailing_ampersand_url


def test_send_provider_success(monkeypatch: pytest.MonkeyPatch):
    calls = []

    class Response:
        status_code = 200
        text = "ok"

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr(webhook_clients.requests, "post", fake_post)

    result = webhook_clients.send_provider(
        "wecom",
        {"enabled": True, "url": "https://wecom.example/hook", "secret": ""},
        "hello",
    )

    assert result == {"provider": "wecom", "ok": True}
    assert calls[0]["json"]["msgtype"] == "markdown"
    assert calls[0]["timeout"] == 5


def test_send_provider_failure_sanitizes_url(monkeypatch: pytest.MonkeyPatch):
    class Response:
        status_code = 400
        text = "bad token"

    monkeypatch.setattr(webhook_clients.requests, "post", lambda *args, **kwargs: Response())

    result = webhook_clients.send_provider(
        "dingtalk",
        {"enabled": True, "url": "https://ding.example/hook?access_token=secret-token", "secret": ""},
        "hello",
    )

    assert result["provider"] == "dingtalk"
    assert result["ok"] is False
    assert "secret-token" not in result["error"]
    assert "HTTP 400" in result["error"]


def test_send_provider_exception_sanitizes_url_and_secret(monkeypatch: pytest.MonkeyPatch):
    def fake_post(url, json, timeout):
        raise RuntimeError("https://wecom.example/hook?key=secret-token secret-value")

    monkeypatch.setattr(webhook_clients.requests, "post", fake_post)

    result = webhook_clients.send_provider(
        "wecom",
        {
            "enabled": True,
            "url": "https://wecom.example/hook?key=secret-token",
            "secret": "secret-value",
        },
        "hello",
    )

    assert result == {"provider": "wecom", "ok": False, "error": "RuntimeError"}


def test_send_provider_unsupported_provider_is_sanitized_and_does_not_post(
    monkeypatch: pytest.MonkeyPatch,
):
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        raise AssertionError("requests.post should not be called")

    monkeypatch.setattr(webhook_clients.requests, "post", fake_post)

    result = webhook_clients.send_provider(
        "unknown",
        {
            "enabled": True,
            "url": "https://unknown.example/hook?token=secret-token",
            "secret": "secret-value",
        },
        "hello",
    )

    assert result == {"provider": "unknown", "ok": False, "error": "Unsupported provider"}
    assert calls == []
    assert "secret-token" not in result["error"]
    assert "secret-value" not in result["error"]


def test_send_provider_dingtalk_posts_signed_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(webhook_clients.time, "time", lambda: 1700000000)
    calls = []

    class Response:
        status_code = 200
        text = "ok"

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr(webhook_clients.requests, "post", fake_post)

    result = webhook_clients.send_provider(
        "dingtalk",
        {"enabled": True, "url": "https://ding.example/hook?access_token=abc", "secret": "secret"},
        "hello",
    )

    assert result == {"provider": "dingtalk", "ok": True}
    assert calls[0]["url"].startswith(
        "https://ding.example/hook?access_token=abc&timestamp=1700000000000&sign="
    )
    assert "sign=OuzzJR5%2BxZ4%2FEYwqtNt6sMYZQMTa%2FHEGvc9miJe7XzY%3D" in calls[0]["url"]
    assert calls[0]["json"] == {
        "msgtype": "markdown",
        "markdown": {"title": "ASC 任务通知", "text": "hello"},
    }


def test_should_notify_matches_kind_and_status():
    config = notifications.default_webhook_config()
    config["enabled"] = True
    config["notify_statuses"] = ["done"]
    config["notify_kinds"] = ["build"]

    assert notifications.should_notify({"kind": "build", "status": "done"}, config) is True
    assert notifications.should_notify({"kind": "metadata", "status": "done"}, config) is False
    assert notifications.should_notify({"kind": "build", "status": "error"}, config) is False


def test_build_task_message_for_failure():
    task = {
        "id": "12345678-abcd",
        "kind": "metadata",
        "title": "元数据上传",
        "profile": "demoapp",
        "status": "error",
        "duration_label": "12s",
        "completed_at": "2026-06-10T11:00:00",
        "result": {"success": False, "error": "ASC failed"},
        "logs": ["line1", "line2", "line3", "line4", "line5", "line6"],
    }

    text = notifications.build_task_message(task)

    assert "ASC 任务失败：元数据上传" in text
    assert "demoapp" in text
    assert "12s" in text
    assert "ASC failed" in text
    assert "12345678" in text
    assert "line1" not in text
    assert "line2" in text
    assert "line6" in text


def test_notify_task_finished_sends_enabled_providers(webhook_path: Path, monkeypatch: pytest.MonkeyPatch):
    notifications.save_webhook_config({
        "enabled": True,
        "notify_statuses": ["done"],
        "notify_kinds": ["build"],
        "providers": {
            "feishu": {"enabled": True, "url": "https://feishu.example/hook", "secret": ""},
            "wecom": {"enabled": True, "url": "https://wecom.example/hook", "secret": ""},
            "dingtalk": {"enabled": False, "url": "https://ding.example/hook", "secret": ""},
        },
    })
    sent = []
    monkeypatch.setattr(
        notifications.webhook_clients,
        "send_provider",
        lambda provider, provider_config, text: sent.append((provider, text)) or {"provider": provider, "ok": True},
    )
    store = TaskStore()
    task_id = store.create("build", profile="demoapp")
    store.set_status(task_id, TaskStatus.DONE)
    store.set_result(task_id, {"success": True})

    results = notifications.notify_task_finished(task_id, task_store=store)

    assert [item[0] for item in sent] == ["feishu", "wecom"]
    assert results == [{"provider": "feishu", "ok": True}, {"provider": "wecom", "ok": True}]


def test_notify_task_finished_logs_provider_failure(webhook_path: Path, monkeypatch: pytest.MonkeyPatch):
    notifications.save_webhook_config({
        "enabled": True,
        "notify_statuses": ["error"],
        "notify_kinds": ["metadata"],
        "providers": {
            "feishu": {"enabled": True, "url": "https://feishu.example/hook", "secret": ""},
            "wecom": {"enabled": False, "url": "", "secret": ""},
            "dingtalk": {"enabled": False, "url": "", "secret": ""},
        },
    })
    monkeypatch.setattr(
        notifications.webhook_clients,
        "send_provider",
        lambda provider, provider_config, text: {"provider": provider, "ok": False, "error": "HTTP 400"},
    )
    store = TaskStore()
    task_id = store.create("metadata", profile="demoapp")
    store.set_status(task_id, TaskStatus.ERROR)
    store.set_result(task_id, {"success": False, "error": "upload failed"})

    notifications.notify_task_finished(task_id, task_store=store)

    task = store.get(task_id)
    assert task["status"] == TaskStatus.ERROR
    assert any("群通知发送失败：feishu HTTP 400" in line for line in task["logs"])
