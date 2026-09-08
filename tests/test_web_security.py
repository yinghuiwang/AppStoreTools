"""Harden Web file APIs, outbound URLs, and credential display."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from asc.web.server import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def isolated_guard(monkeypatch):
    monkeypatch.setattr("asc.web.routes_api.enforce_config_guard", MagicMock())
    monkeypatch.setattr("asc.web.routes_iap.enforce_config_guard", MagicMock())
    monkeypatch.setattr("asc.web.routes_listing.enforce_config_guard", MagicMock())


def test_is_safe_outbound_url_rejects_metadata_and_non_http():
    from asc.web.security import is_safe_outbound_url

    assert is_safe_outbound_url("https://api.openai.com/v1") is True
    assert is_safe_outbound_url("http://127.0.0.1:11434/v1") is True
    assert is_safe_outbound_url("file:///etc/passwd") is False
    assert is_safe_outbound_url("http://169.254.169.254/latest/meta-data") is False
    assert is_safe_outbound_url("http://metadata.google.internal/") is False


def test_mask_helpers_keep_tail_only():
    from asc.web.security import mask_identifier, mask_ip

    assert mask_identifier("issuer-123") == "••••••-123"
    assert mask_identifier("KEY123") == "••Y123"
    assert mask_ip("1.2.3.4") == "1.2.3.*"
    assert "SERIAL-FULL" not in mask_identifier("SERIAL-FULL")


def test_listing_thumb_rejects_p8_even_under_root(client, tmp_path):
    key = tmp_path / "AuthKey_TEST.p8"
    key.write_text("-----BEGIN PRIVATE KEY-----\n", encoding="utf-8")
    resp = client.get(
        "/api/listing/thumb",
        params={"path": str(key), "root": str(tmp_path)},
    )
    assert resp.status_code == 403


def test_listing_thumb_rejects_asc_keys_dir(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    keys = tmp_path / ".config" / "asc" / "keys"
    key = keys / "AuthKey_TEST.p8"
    key.parent.mkdir(parents=True)
    key.write_text("secret", encoding="utf-8")
    resp = client.get(
        "/api/listing/thumb",
        params={"path": str(key), "root": str(keys)},
    )
    assert resp.status_code == 403


def test_listing_save_rejects_secret_and_outside_home(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    key = tmp_path / "home" / ".config" / "asc" / "keys" / "leak.csv"
    key.parent.mkdir(parents=True)
    body = {
        "csv_path": str(key),
        "locales": [{"locale": "en-US", "fields": {"name": "X"}}],
    }
    secret = client.post(
        "/api/listing/local/save",
        json=body,
        cookies={"asc_profile": "test"},
    )
    assert secret.status_code == 403

    outside = client.post(
        "/api/listing/local/save",
        json={
            "csv_path": "/etc/asc-web-should-not-write.csv",
            "locales": [{"locale": "en-US", "fields": {"name": "X"}}],
        },
        cookies={"asc_profile": "test"},
    )
    assert outside.status_code == 403


def test_iap_save_rejects_p8_path(client, tmp_path):
    key = tmp_path / "AuthKey_TEST.p8"
    mock_config = MagicMock()
    mock_config.iap_path = str(key)
    with patch("asc.web.routes_iap.Config", return_value=mock_config):
        resp = client.post(
            "/api/iap/local/save",
            cookies={"asc_profile": "testapp"},
            json={
                "iapFile": str(key),
                "snapshot": {"items": [], "subscriptionGroups": []},
            },
        )
    assert resp.status_code == 403
    assert not key.exists()


def test_browse_rejects_asc_keys_dir(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    keys = tmp_path / ".config" / "asc" / "keys"
    keys.mkdir(parents=True)
    (keys / "AuthKey_TEST.p8").write_text("secret", encoding="utf-8")
    resp = client.get(f"/api/browse?path={keys}&mode=dir")
    assert resp.status_code == 403


def test_browse_hides_p8_in_normal_folder(client, tmp_path):
    (tmp_path / "shot.png").write_bytes(b"png")
    (tmp_path / "AuthKey_TEST.p8").write_text("secret", encoding="utf-8")
    resp = client.get(f"/api/browse?path={tmp_path}&mode=file&ext=.png,.p8")
    assert resp.status_code == 200
    names = [e["name"] for e in resp.json()["entries"]]
    assert "shot.png" in names
    assert "AuthKey_TEST.p8" not in names


def test_llm_save_rejects_link_local_metadata(client):
    resp = client.post(
        "/api/settings/llm",
        json={
            "name": "evil",
            "base_url": "http://169.254.169.254/latest",
            "api_key": "k",
            "model": "gpt",
        },
    )
    assert resp.status_code == 400


def test_webhook_save_rejects_file_url(client):
    resp = client.post(
        "/api/settings/webhooks",
        json={
            "enabled": True,
            "providers": {
                "feishu": {"enabled": True, "url": "file:///etc/passwd"},
            },
        },
    )
    assert resp.status_code == 400


def test_profiles_list_masks_issuer_and_key(client):
    mock_config = MagicMock()
    mock_config.list_apps.return_value = ["myapp"]
    mock_config.app_name = "myapp"
    mock_config.get_app_profile.return_value = {
        "issuer_id": "issuer-123",
        "key_id": "KEY123",
        "key_file": "/tmp/AuthKey_KEY123.p8",
        "app_id": "123456789",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }
    with patch("asc.config.Config", return_value=mock_config):
        resp = client.get("/api/profiles")
    assert resp.status_code == 200
    details = resp.json()["profile_details"]["myapp"]
    assert details["issuer_id"] != "issuer-123"
    assert details["key_id"] != "KEY123"
    assert details["issuer_id"].endswith("-123")
    assert details["key_id"].endswith("Y123")
    assert details["issuer_id"].startswith("•")
    assert details["key_id"].startswith("•")


def test_guard_status_shows_full_fingerprint_and_ip(client):
    from unittest.mock import MagicMock

    mock_guard = MagicMock()
    mock_guard.get_status.return_value = {
        "enabled": True,
        "app_notes": {},
        "bindings": {
            "machine": {
                "SERIAL-FULL": {
                    "app_id": "123",
                    "app_name": "myapp",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                }
            },
            "ip": {
                "1.2.3.4": {
                    "app_id": "123",
                    "app_name": "myapp",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                }
            },
            "credential": {},
        },
    }
    mock_guard.current_environment.return_value = {
        "machine": {
            "fingerprint": "SERIAL-FULL",
            "bound": True,
            "app_id": "123",
            "app_name": "myapp",
            "note": "",
        },
        "ip": {
            "address": "1.2.3.4",
            "available": True,
            "bound": True,
            "app_id": "123",
            "app_name": "myapp",
            "note": "",
        },
    }
    mock_config = MagicMock()
    mock_config.list_apps.return_value = ["myapp"]
    mock_config.get_app_profile.return_value = {"app_id": "123"}
    with patch("asc.guard.Guard", return_value=mock_guard), patch(
        "asc.config.Config", return_value=mock_config
    ):
        resp = client.get("/api/guard/status")
    data = resp.json()
    dumped = json.dumps(data)
    assert "SERIAL-FULL" in dumped
    assert "1.2.3.4" in dumped
    assert data["bindings"]["machine"]["SERIAL-FULL"]["issuer_id"] == "••••"
    assert data["current_environment"]["machine"]["fingerprint"] == "SERIAL-FULL"
    assert data["current_environment"]["ip"]["address"] == "1.2.3.4"


def test_profile_edit_does_not_reuse_listed_secrets():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "src"
        / "views"
        / "system"
        / "ProfilesTab.vue"
    ).read_text(encoding="utf-8")
    assert 'issuer_id: ""' in src
    assert "issuer_id: d.issuer_id" not in src
    assert "key_id: d.key_id" not in src
