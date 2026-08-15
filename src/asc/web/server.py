"""FastAPI application factory and route registration for asc Web UI."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from asc import __version__
from asc.cli import _installed_commit_short
from asc.web.agent_store import agent_store
from asc.web.tasks import task_store

_STATIC_DIR = Path(__file__).parent / "static"
SPA_INDEX = _STATIC_DIR / "spa" / "index.html"


def runtime_identity() -> tuple[str, str]:
    """Return startup version and commit without making boot depend on git."""
    try:
        commit = _installed_commit_short() or "unknown"
    except Exception:  # noqa: BLE001
        commit = "unknown"
    return __version__, commit


@asynccontextmanager
async def _lifespan(app: FastAPI):
    version, commit = await asyncio.to_thread(runtime_identity)
    logging.getLogger("asc.web").info(
        "Web UI started asc_version=%s commit=%s",
        version,
        commit,
    )
    yield
    try:
        from asc.web.task_runner import shutdown_scheduler

        shutdown_scheduler(task_store, wait=True, timeout=30.0)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  TaskScheduler shutdown failed: {exc}")
    try:
        task_store.close()
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  TaskStore shutdown failed: {exc}")
    try:
        agent_store.close()
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  AgentStore shutdown failed: {exc}")


def create_app() -> FastAPI:
    from asc.web.i18n import COOKIE_NAME, resolve_lang

    app = FastAPI(title="asc Web UI", docs_url=None, redoc_url=None, lifespan=_lifespan)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.middleware("http")
    async def language_middleware(request: Request, call_next):
        request.state.lang = resolve_lang(
            cookie=request.cookies.get(COOKIE_NAME),
            accept_language=request.headers.get("accept-language"),
        )
        return await call_next(request)

    from asc.web import routes_api, routes_listing, routes_agent
    app.include_router(routes_api.router, prefix="/api")
    app.include_router(routes_listing.router, prefix="/api/listing")
    app.include_router(routes_agent.router, prefix="/api/agent")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path == "api" or full_path.startswith("api/") or full_path == "static" or full_path.startswith("static/"):
            raise HTTPException(status_code=404, detail="Not Found")
        index = SPA_INDEX
        if not index.is_file():
            return JSONResponse({"ok": False, "error": "spa_not_built"}, status_code=503)
        return FileResponse(
            index,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    return app
