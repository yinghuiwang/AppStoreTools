"""Local session token and loopback Origin checks for the Web UI."""
from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from asc.web.daemon import is_loopback_host

COOKIE_NAME = "asc_session"
HEADER_NAME = "X-ASC-Token"


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def is_allowed_origin(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname
    if not host:
        return False
    return is_loopback_host(host)


def origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin:
        return is_allowed_origin(origin)
    referer = request.headers.get("referer")
    if referer:
        return is_allowed_origin(referer)
    return True


def is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def is_session_path(path: str, method: str) -> bool:
    return path == "/api/session" and method.upper() in {"GET", "HEAD"}


def attach_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        path="/",
        secure=False,
    )


def _tokens_match(provided: str | None, expected: str) -> bool:
    if not provided:
        return False
    if len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided, expected)


def request_has_valid_token(request: Request, expected: str) -> bool:
    header = request.headers.get(HEADER_NAME)
    if _tokens_match(header, expected):
        return True
    return _tokens_match(request.cookies.get(COOKIE_NAME), expected)


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "unauthorized", "message": "Web UI session required"},
        status_code=401,
    )


def _forbidden_origin() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "forbidden_origin", "message": "Origin is not a local Web UI"},
        status_code=403,
    )


def protect_request(request: Request) -> JSONResponse | None:
    """Return an error response when the request must not proceed."""
    path = request.url.path
    method = request.method.upper()

    if not origin_allowed(request):
        return _forbidden_origin()

    if is_session_path(path, method) or not is_api_path(path):
        return None

    token = getattr(request.app.state, "session_token", None)
    if not token or not request_has_valid_token(request, token):
        return _unauthorized()
    return None
