from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from asc.web import notifications
from asc.web import webhook_clients
from asc.web.server import create_app


TEST_MESSAGE = "**ASC 群通知测试**\n- 状态：配置验证\n- 结果：Webhook 可以接收消息"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ASC_WEBHOOK_CONFIG_PATH", str(tmp_path / "webhook.toml"))
    return TestClient(create_app())


def test_settings_webhooks_get_returns_defaults(client: TestClient):
    response = client.get("/api/settings/webhooks")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert "feishu" in data["providers"]
    assert data["providers"]["feishu"]["secret"] == ""


def test_settings_page_has_webhook_card(client: TestClient):
    response = client.get("/settings")

    assert response.status_code == 200
    html = response.text
    assert "群通知 / Webhook" in html
    assert "/api/settings/webhooks" in html
    assert "飞书/Lark" in html
    assert "企业微信" in html
    assert "钉钉" in html


def test_settings_webhooks_post_saves_config(client: TestClient):
    response = client.post("/api/settings/webhooks", json={
        "enabled": True,
        "notify_statuses": ["done", "error"],
        "notify_kinds": ["build"],
        "providers": {
            "feishu": {"enabled": True, "url": "https://feishu.example/hook", "secret": "secret"},
            "wecom": {"enabled": False, "url": "", "secret": ""},
            "dingtalk": {"enabled": False, "url": "", "secret": ""},
        },
    })

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    loaded = client.get("/api/settings/webhooks").json()
    assert loaded["enabled"] is True
    assert loaded["notify_kinds"] == ["build"]
    assert loaded["providers"]["feishu"]["secret"] == ""
    assert loaded["providers"]["feishu"]["has_secret"] is True


def test_settings_webhooks_post_invalid_json_returns_400(client: TestClient):
    response = client.post(
        "/api/settings/webhooks",
        content="{bad json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert "error" in response.json()


def test_settings_webhooks_test_sends_provider(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from asc.web import routes_api

    monkeypatch.setattr(
        routes_api.notifications,
        "send_test_notification",
        lambda provider=None: [{"provider": provider or "feishu", "ok": True}],
    )

    response = client.post("/api/settings/webhooks/test", json={"provider": "feishu"})

    assert response.status_code == 200
    assert response.json()["results"] == [{"provider": "feishu", "ok": True}]


def test_settings_webhooks_test_empty_provider_is_unsupported(client: TestClient):
    response = client.post("/api/settings/webhooks/test", json={"provider": ""})

    assert response.status_code == 200
    assert response.json()["results"] == [
        {"provider": "", "ok": False, "error": "Unsupported provider"},
    ]


def test_settings_webhooks_test_non_object_json_returns_400(client: TestClient):
    response = client.post("/api/settings/webhooks/test", json=[])

    assert response.status_code == 400
    assert "error" in response.json()


def test_send_test_notification_all_configured_providers_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ASC_WEBHOOK_CONFIG_PATH", str(tmp_path / "webhook.toml"))
    notifications.save_webhook_config({
        "enabled": True,
        "notify_statuses": ["done"],
        "notify_kinds": ["build"],
        "providers": {
            "feishu": {"enabled": True, "url": "https://feishu.example/hook", "secret": "fs"},
            "wecom": {"enabled": True, "url": "https://wecom.example/hook", "secret": "wc"},
            "dingtalk": {"enabled": True, "url": "https://ding.example/hook", "secret": "dt"},
        },
    })
    calls = []

    def fake_send_provider(provider: str, config: dict, text: str):
        calls.append((provider, config["url"], text))
        return {"provider": provider, "ok": True}

    monkeypatch.setattr(webhook_clients, "send_provider", fake_send_provider)

    result = notifications.send_test_notification()

    assert [item["provider"] for item in result] == ["feishu", "wecom", "dingtalk"]
    assert [call[0] for call in calls] == ["feishu", "wecom", "dingtalk"]


def test_send_test_notification_unsupported_provider_does_not_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ASC_WEBHOOK_CONFIG_PATH", str(tmp_path / "webhook.toml"))

    def fail_send_provider(provider: str, config: dict, text: str):
        raise AssertionError("send_provider should not be called")

    monkeypatch.setattr(webhook_clients, "send_provider", fail_send_provider)

    result = notifications.send_test_notification(provider="unknown")

    assert result == [{"provider": "unknown", "ok": False, "error": "Unsupported provider"}]


def test_send_test_notification_disabled_or_missing_url_is_not_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ASC_WEBHOOK_CONFIG_PATH", str(tmp_path / "webhook.toml"))
    notifications.save_webhook_config({
        "providers": {
            "feishu": {"enabled": False, "url": "https://feishu.example/hook", "secret": ""},
            "wecom": {"enabled": True, "url": "", "secret": ""},
            "dingtalk": {"enabled": False, "url": "", "secret": ""},
        },
    })

    def fail_send_provider(provider: str, config: dict, text: str):
        raise AssertionError("send_provider should not be called")

    monkeypatch.setattr(webhook_clients, "send_provider", fail_send_provider)

    assert notifications.send_test_notification(provider="feishu") == [
        {"provider": "feishu", "ok": False, "error": "Provider is not configured"},
    ]
    assert notifications.send_test_notification(provider="wecom") == [
        {"provider": "wecom", "ok": False, "error": "Provider is not configured"},
    ]


def test_send_test_notification_configured_provider_uses_fixed_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ASC_WEBHOOK_CONFIG_PATH", str(tmp_path / "webhook.toml"))
    notifications.save_webhook_config({
        "providers": {
            "feishu": {"enabled": True, "url": "https://feishu.example/hook", "secret": "fs"},
            "wecom": {"enabled": False, "url": "", "secret": ""},
            "dingtalk": {"enabled": False, "url": "", "secret": ""},
        },
    })
    calls = []

    def fake_send_provider(provider: str, config: dict, text: str):
        calls.append((provider, config, text))
        return {"provider": provider, "ok": True}

    monkeypatch.setattr(webhook_clients, "send_provider", fake_send_provider)

    result = notifications.send_test_notification(provider="feishu")

    assert result == [{"provider": "feishu", "ok": True}]
    assert calls == [
        (
            "feishu",
            {"enabled": True, "url": "https://feishu.example/hook", "secret": "fs"},
            TEST_MESSAGE,
        ),
    ]
