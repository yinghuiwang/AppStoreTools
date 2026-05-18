"""API routes for asc Web UI (/api/*)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/switch-profile")
async def switch_profile(profile: str):
    """Switch active app profile (stores in session cookie)."""
    resp = JSONResponse({"ok": True, "profile": profile})
    resp.set_cookie("asc_profile", profile, httponly=True, samesite="lax")
    return resp
