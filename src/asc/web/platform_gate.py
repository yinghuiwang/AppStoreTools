"""HTTP gate that shares ``asc.platform`` with the CLI."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from asc.platform import feature_supported
from asc.web.i18n import t


def unsupported_response(request: Request, feature: str) -> JSONResponse | None:
    """Return a 400 when *feature* is disabled on this server OS."""
    if feature_supported(feature):
        return None
    lang = getattr(request.state, "lang", None) or "en"
    return JSONResponse(
        {"error": t("platform.unsupported", lang=lang)},
        status_code=400,
    )
