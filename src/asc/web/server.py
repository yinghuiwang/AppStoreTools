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
        """Extract current profile from cookie or config, including profile defaults."""
        from asc.config import Config
        profile_from_cookie = request.cookies.get("asc_profile")
        config = Config(app_name=profile_from_cookie)
        profiles = config.list_apps()
        current = profile_from_cookie or config.app_name or (profiles[0] if profiles else "")
        return {
            "profiles": profiles,
            "current_profile": current,
            "profile_csv": config.csv_path,
            "profile_screenshots": config.screenshots_path,
            "profile_iap_file": config.iap_path or "data/iap_packages.json",
        }

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        ctx = _get_profile_context(request)
        ctx["recent_tasks"] = task_store.list_recent(limit=20)
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

    @app.get("/iap", response_class=HTMLResponse)
    async def iap_page(request: Request):
        ctx = _get_profile_context(request)
        return templates.TemplateResponse(request, "iap.html", ctx)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        ctx = _get_profile_context(request)
        return templates.TemplateResponse(request, "settings.html", ctx)

    @app.get("/whats-new", response_class=HTMLResponse)
    async def whats_new_page(request: Request):
        ctx = _get_profile_context(request)
        return templates.TemplateResponse(request, "whats_new.html", ctx)

    @app.get("/urls", response_class=HTMLResponse)
    async def urls_page(request: Request):
        ctx = _get_profile_context(request)
        return templates.TemplateResponse(request, "urls.html", ctx)

    @app.get("/whatsnew", response_class=HTMLResponse)
    async def whatsnew_page(request: Request):
        ctx = _get_profile_context(request)
        return templates.TemplateResponse(request, "whatsnew.html", ctx)

    @app.get("/update", response_class=HTMLResponse)
    async def update_page(request: Request):
        ctx = _get_profile_context(request)
        return templates.TemplateResponse(request, "update.html", ctx)

    from asc.web import routes_api
    app.include_router(routes_api.router, prefix="/api")

    return app
