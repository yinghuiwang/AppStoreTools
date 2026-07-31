"""FastAPI application factory and route registration for asc Web UI."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from asc.web.dashboard import build_dashboard_summary
from asc.web.tasks import task_store

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    from asc.web.i18n import (
        COOKIE_NAME,
        html_lang as map_html_lang,
        load_catalog,
        resolve_lang,
        t as translate,
    )

    app = FastAPI(title="asc Web UI", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    @app.middleware("http")
    async def language_middleware(request: Request, call_next):
        request.state.lang = resolve_lang(
            cookie=request.cookies.get(COOKIE_NAME),
            accept_language=request.headers.get("accept-language"),
        )
        return await call_next(request)

    def _get_profile_context(request: Request) -> dict:
        """Extract current profile from cookie or config, including profile defaults."""
        from asc.config import Config
        profile_from_cookie = request.cookies.get("asc_profile")
        config = Config(app_name=profile_from_cookie)
        profiles = config.list_apps()
        profile_data = {
            name: config.get_app_profile(name) or {}
            for name in profiles
        }
        from asc.guard import Guard
        access = Guard().profile_access(profile_data)
        options = access["options"]
        selectable = [name for name in profiles if options[name]["enabled"]]
        requested = profile_from_cookie or config.app_name or ""
        current = requested if requested in selectable else ""
        if not current:
            current = access["matched_profile"] or (selectable[0] if selectable else "")
        current_config = Config(app_name=current) if current else config
        from asc import __version__ as asset_version
        lang = getattr(request.state, "lang", None) or resolve_lang(
            cookie=request.cookies.get(COOKIE_NAME),
            accept_language=request.headers.get("accept-language"),
        )

        def _t(key: str, **kwargs: object) -> str:
            return translate(key, lang=lang, **kwargs)

        return {
            "profiles": profiles,
            "profile_access": options,
            "has_machine_profile": bool(access["matched_profile"]),
            "current_profile": current,
            "profile_csv": current_config.csv_path,
            "profile_screenshots": current_config.screenshots_path,
            "profile_iap_file": current_config.iap_path or "data/iap_packages.json",
            "asset_version": asset_version,
            "lang": lang,
            "html_lang": map_html_lang(lang),
            "t": _t,
            "i18n_catalog": load_catalog(lang),
        }

    def _render(request: Request, template: str, ctx: dict):
        """Render a page and persist the resolved profile to the cookie when missing.

        The sidebar switcher only writes ``asc_profile`` on a manual ``onchange``.
        Without this, the first visit shows a selected app (via fallback) but the
        cookie stays empty, so API endpoints reject requests with
        "No profile selected". Setting the cookie here keeps the visible selection
        and the backend in sync.
        """
        resp = templates.TemplateResponse(request, template, ctx)
        if request.cookies.get("asc_profile") != ctx.get("current_profile") and ctx.get("current_profile"):
            resp.set_cookie(
                "asc_profile",
                ctx["current_profile"],
                httponly=True,
                samesite="lax",
            )
        return resp

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        ctx = _get_profile_context(request)
        recent_states = task_store.list_recent_states(limit=500)
        ctx["dashboard"] = build_dashboard_summary(
            recent_states,
            days=30,
            profile=ctx["current_profile"],
        )
        ctx["recent_tasks"] = ctx["dashboard"]["tasks"]
        return _render(request, "index.html", ctx)

    @app.get("/metadata", response_class=HTMLResponse)
    async def metadata_page(request: Request):
        ctx = _get_profile_context(request)
        action = request.query_params.get("action", "")
        ctx["workflow_action"] = action if action in {"check", "all", "metadata", "screenshots"} else ""
        return _render(request, "metadata.html", ctx)

    @app.get("/build", response_class=HTMLResponse)
    async def build_page(request: Request):
        ctx = _get_profile_context(request)
        action = request.query_params.get("action", "")
        ctx["workflow_action"] = action if action == "build-upload" else ""
        return _render(request, "build.html", ctx)

    @app.get("/profiles", response_class=HTMLResponse)
    async def profiles_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "profiles.html", ctx)

    @app.get("/iap", response_class=HTMLResponse)
    async def iap_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "iap.html", ctx)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "settings.html", ctx)

    @app.get("/guard", response_class=HTMLResponse)
    async def guard_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "guard.html", ctx)

    @app.get("/whats-new", response_class=HTMLResponse)
    async def whats_new_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "whats_new.html", ctx)

    @app.get("/urls", response_class=HTMLResponse)
    async def urls_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "urls.html", ctx)

    @app.get("/update", response_class=HTMLResponse)
    async def update_page(request: Request):
        ctx = _get_profile_context(request)
        from asc.commands.update_cmd import _current_version, _is_editable
        from asc.cli import _installed_commit_short
        try:
            tool_version = _current_version()
        except Exception:
            tool_version = ctx.get("asset_version", "?")
        ctx["tool_version"] = tool_version
        ctx["tool_commit"] = _installed_commit_short() or ""
        ctx["is_editable"] = _is_editable()
        return _render(request, "update.html", ctx)

    from asc.web import routes_api
    app.include_router(routes_api.router, prefix="/api")

    return app
