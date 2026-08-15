from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from asc.web.server import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def _config(apps, *, csv="data/appstore_info.csv", shots="data/screenshots", iap=None):
    config = MagicMock()
    config.list_apps.return_value = list(apps)
    config.csv_path = csv
    config.screenshots_path = shots
    config.iap_path = iap
    config.get_app_profile.side_effect = lambda name: {
        "app_id": f"app-{name}",
        "issuer_id": f"ISS-{name}",
        "key_id": f"KEY-{name}",
    }
    return config


def test_bootstrap_shape_without_cookie_or_machine_match():
    config = _config(["alpha", "beta"])
    access = {
        "matched_profile": "",
        "options": {
            "alpha": {"enabled": True, "current": False, "elsewhere": False},
            "beta": {"enabled": True, "current": False, "elsewhere": False},
        },
    }
    with patch("asc.config.Config", return_value=config), patch(
        "asc.guard.Guard.profile_access", return_value=access
    ):
        resp = _client().get("/api/bootstrap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["current_profile"] == ""
    assert body["profiles"] == ["alpha", "beta"]
    assert body["has_machine_profile"] is False
    assert body["paths"] == {
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
        "iap": "data/iap_packages.json",
    }
    assert "i18n_catalog" not in body
    assert isinstance(body["boot_id"], str) and len(body["boot_id"]) == 32
    assert body["lang"] in {"zh", "en"}
    assert body["html_lang"] in {"zh-CN", "en"}
    assert "version" in body and "commit" in body
    assert isinstance(body["is_editable"], bool)


def test_bootstrap_cookie_wins_when_profile_is_selectable():
    config = _config(["myapp", "other"])
    access = {
        "matched_profile": "myapp",
        "options": {
            "myapp": {"enabled": True, "current": True, "elsewhere": False},
            "other": {"enabled": True, "current": False, "elsewhere": False},
        },
    }
    with patch("asc.config.Config", return_value=config), patch(
        "asc.guard.Guard.profile_access", return_value=access
    ):
        resp = _client().get("/api/bootstrap", cookies={"asc_profile": "other"})
    assert resp.json()["current_profile"] == "other"


def test_bootstrap_clears_stale_cookie_for_other_machine_profile():
    config = _config(["current-app", "other-app"])
    access = {
        "matched_profile": "current-app",
        "options": {
            "current-app": {"enabled": True, "current": True, "elsewhere": False},
            "other-app": {"enabled": False, "current": False, "elsewhere": True},
        },
    }
    with patch("asc.config.Config", return_value=config), patch(
        "asc.guard.Guard.profile_access", return_value=access
    ):
        resp = _client().get(
            "/api/bootstrap", cookies={"asc_profile": "other-app"}
        )
    body = resp.json()
    assert body["current_profile"] == "current-app"
    assert body["profile_access"]["other-app"]["enabled"] is False
    assert resp.cookies.get("asc_profile") == "current-app"


def test_bootstrap_does_not_fall_back_to_default_app():
    config = _config(["alpha", "beta"])
    config.app_name = "alpha"
    access = {
        "matched_profile": "",
        "options": {
            "alpha": {"enabled": True, "current": False, "elsewhere": False},
            "beta": {"enabled": True, "current": False, "elsewhere": False},
        },
    }
    with patch("asc.config.Config", return_value=config), patch(
        "asc.guard.Guard.profile_access", return_value=access
    ):
        resp = _client().get("/api/bootstrap")
    assert resp.json()["current_profile"] == ""
