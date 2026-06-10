from __future__ import annotations

from pathlib import Path

import pytest

from asc.web import notifications


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
