"""FastAPI application factory and route registration for asc Web UI."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from asc.web.tasks import task_store

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app() -> FastAPI:
    app = FastAPI(title="asc Web UI", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    def _get_profile_context(request: Request) -> dict:
        """Extract current profile from cookie or config."""
        from asc.config import Config
        profile_from_cookie = request.cookies.get("asc_profile")
        config = Config(app_name=profile_from_cookie)
        profiles = config.list_apps()
        current = profile_from_cookie or config.app_name or (profiles[0] if profiles else "")
        return {"profiles": profiles, "current_profile": current}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        ctx = _get_profile_context(request)
        ctx["recent_tasks"] = task_store.list_recent(limit=5)
        return templates.TemplateResponse(request, "index.html", ctx)

    @app.get("/metadata", response_class=HTMLResponse)
    async def metadata_page(request: Request):
        ctx = _get_profile_context(request)
        return templates.TemplateResponse(request, "metadata.html", ctx)

    @app.get("/build", response_class=HTMLResponse)
    async def build_page(request: Request):
        ctx = _get_profile_context(request)
        return templates.TemplateResponse(request, "build.html", ctx)

    @app.get("/profiles", response_class=HTMLResponse)
    async def profiles_page(request: Request):
        ctx = _get_profile_context(request)
        return templates.TemplateResponse(request, "profiles.html", ctx)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        ctx = _get_profile_context(request)
        return templates.TemplateResponse(request, "settings.html", ctx)

    from asc.web import routes_api
    app.include_router(routes_api.router, prefix="/api")

    return app
