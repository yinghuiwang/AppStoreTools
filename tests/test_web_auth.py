"""Local session token + CSRF/Origin checks for the Web UI."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from asc.web.server import create_app


def _raw_client(app=None) -> TestClient:
    client = TestClient(app or create_app())
    client.headers.pop("X-ASC-Token", None)
    return client


def test_api_get_without_session_returns_401():
    resp = _raw_client().get("/api/profiles")
    assert resp.status_code == 401
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "unauthorized"


def test_api_post_without_session_returns_401():
    resp = _raw_client().post("/api/metadata/check")
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_spa_and_static_do_not_require_session(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text("<html>spa</html>", encoding="utf-8")
    monkeypatch.setattr("asc.web.server.SPA_INDEX", index)
    client = _raw_client()

    home = client.get("/")
    assert home.status_code == 200
    assert home.status_code != 401

    logo = client.get("/static/logo.svg")
    assert logo.status_code == 200
    assert logo.status_code != 401


def test_unknown_api_without_session_is_401_not_404():
    resp = _raw_client().get("/api/does-not-exist")
    assert resp.status_code == 401


def test_session_endpoint_sets_httponly_samesite_cookie():
    client = _raw_client()
    resp = client.get("/api/session")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    set_cookie = resp.headers.get("set-cookie", "")
    assert "asc_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()
    assert client.cookies.get("asc_session")


def test_session_cookie_allows_subsequent_api_calls():
    client = _raw_client()
    assert client.get("/api/session").status_code == 200
    with patch("asc.config.Config.list_apps", return_value=["myapp"]):
        resp = client.get("/api/profiles")
    assert resp.status_code == 200
    assert "myapp" in resp.json()["profiles"]


def test_spa_sets_session_cookie(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text("<html>spa</html>", encoding="utf-8")
    monkeypatch.setattr("asc.web.server.SPA_INDEX", index)
    client = _raw_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "asc_session=" in resp.headers.get("set-cookie", "")
    with patch("asc.config.Config.list_apps", return_value=["myapp"]):
        follow = client.get("/api/profiles")
    assert follow.status_code == 200


def test_wrong_token_returns_401():
    resp = _raw_client().get("/api/profiles", headers={"X-ASC-Token": "not-the-token"})
    assert resp.status_code == 401


def test_x_asc_token_header_allows_api():
    app = create_app()
    client = _raw_client(app)
    with patch("asc.config.Config.list_apps", return_value=["myapp"]):
        resp = client.get(
            "/api/profiles",
            headers={"X-ASC-Token": app.state.session_token},
        )
    assert resp.status_code == 200


def test_session_rejects_foreign_origin():
    client = _raw_client()
    resp = client.get("/api/session", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "forbidden_origin"
    assert "asc_session=" not in resp.headers.get("set-cookie", "")


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://[::1]:8080",
    ],
)
def test_loopback_origin_is_allowed(origin):
    app = create_app()
    client = _raw_client(app)
    with patch("asc.config.Config.list_apps", return_value=["myapp"]):
        resp = client.get(
            "/api/profiles",
            headers={
                "X-ASC-Token": app.state.session_token,
                "Origin": origin,
            },
        )
    assert resp.status_code == 200


def test_foreign_origin_post_is_rejected_even_with_token():
    app = create_app()
    client = _raw_client(app)
    resp = client.post(
        "/api/metadata/check",
        headers={
            "X-ASC-Token": app.state.session_token,
            "Origin": "https://evil.example",
        },
        cookies={"asc_profile": "myapp"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "forbidden_origin"


def test_foreign_referer_is_rejected():
    app = create_app()
    client = _raw_client(app)
    resp = client.get(
        "/api/profiles",
        headers={
            "X-ASC-Token": app.state.session_token,
            "Referer": "https://evil.example/attack",
        },
    )
    assert resp.status_code == 403


def test_is_allowed_origin_only_accepts_loopback():
    from asc.web.auth import is_allowed_origin

    assert is_allowed_origin("http://127.0.0.1:8080") is True
    assert is_allowed_origin("http://localhost:5173") is True
    assert is_allowed_origin("http://[::1]:8080") is True
    assert is_allowed_origin("https://evil.example") is False
    assert is_allowed_origin("http://192.168.1.5:8080") is False
    assert is_allowed_origin("not-a-url") is False


def test_frontend_establishes_session_before_bootstrap():
    root = Path(__file__).resolve().parents[1]
    main = (root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
    http = (root / "frontend" / "src" / "api" / "http.ts").read_text(encoding="utf-8")
    assert "ensureSession" in main
    assert 'fetch("/api/session"' in http
    assert "credentials: \"same-origin\"" in http
