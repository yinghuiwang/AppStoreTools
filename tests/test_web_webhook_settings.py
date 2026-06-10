from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from asc.web.server import create_app


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
