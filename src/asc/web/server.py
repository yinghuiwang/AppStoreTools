"""FastAPI application factory and route registration for asc Web UI."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from asc import __version__
from asc.cli import _installed_commit_short
from asc.web.agent_store import agent_store
from asc.web.dashboard import build_dashboard_summary
from asc.web.tasks import task_store

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_ASSET_STAMP_FILES = (
    "agent-dock.js",
    "agent-rail.css",
    "task-log-drawer.css",
    "task-log-drawer.js",
)


def _web_asset_version() -> str:
    """Package version plus static mtime so local JS/CSS edits bust browser cache."""
    stamp = 0
    for name in _ASSET_STAMP_FILES:
        path = _STATIC_DIR / name
        try:
            stamp = max(stamp, int(path.stat().st_mtime))
        except OSError:
            continue
    return f"{__version__}.{stamp}" if stamp else __version__


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
    from asc.web.i18n import (
        COOKIE_NAME,
        html_lang as map_html_lang,
        load_catalog,
        resolve_lang,
        t as translate,
    )

    app = FastAPI(title="asc Web UI", docs_url=None, redoc_url=None, lifespan=_lifespan)
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
        """Resolve sidebar/current App: cookie if selectable, else machine match only."""
        from asc.web.profile_context import load_web_profile_state

        state = load_web_profile_state(request.cookies.get("asc_profile"))
        paths = state["paths"]
        asset_version = _web_asset_version()
        lang = getattr(request.state, "lang", None) or resolve_lang(
            cookie=request.cookies.get(COOKIE_NAME),
            accept_language=request.headers.get("accept-language"),
        )

        def _t(key: str, **kwargs: object) -> str:
            return translate(key, lang=lang, **kwargs)

        return {
            "profiles": state["profiles"],
            "profile_access": state["profile_access"],
            "has_machine_profile": state["has_machine_profile"],
            "current_profile": state["current_profile"],
            "profile_csv": paths["csv"],
            "profile_screenshots": paths["screenshots"],
            "profile_iap_file": paths["iap"],
            "asset_version": asset_version,
            "lang": lang,
            "html_lang": map_html_lang(lang),
            "t": _t,
            "i18n_catalog": load_catalog(lang),
        }

    def _render(request: Request, template: str, ctx: dict):
        """Render a page and sync ``asc_profile`` with the resolved selection.

        When a machine-matched profile is auto-selected, persist it to the cookie
        so API routes see the same app. When nothing is selected, clear a stale
        cookie so APIs do not silently fall through to ``default_app``.
        """
        from asc.web.profile_context import apply_profile_cookie

        resp = templates.TemplateResponse(request, template, ctx)
        apply_profile_cookie(
            resp,
            cookie=request.cookies.get("asc_profile") or "",
            current=ctx.get("current_profile") or "",
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
    def metadata_page(request: Request):
        ctx = _get_profile_context(request)
        action = request.query_params.get("action", "")
        ctx["workflow_action"] = action if action in {"check", "all", "metadata", "screenshots"} else ""
        return _render(request, "metadata.html", ctx)

    @app.get("/build", response_class=HTMLResponse)
    def build_page(request: Request):
        ctx = _get_profile_context(request)
        action = request.query_params.get("action", "")
        ctx["workflow_action"] = action if action == "build-upload" else ""
        return _render(request, "build.html", ctx)

    @app.get("/profiles", response_class=HTMLResponse)
    def profiles_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "profiles.html", ctx)

    @app.get("/iap", response_class=HTMLResponse)
    def iap_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "iap.html", ctx)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "settings.html", ctx)

    @app.get("/guard", response_class=HTMLResponse)
    def guard_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "guard.html", ctx)

    @app.get("/whats-new", response_class=HTMLResponse)
    def whats_new_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "whats_new.html", ctx)

    @app.get("/urls", response_class=HTMLResponse)
    def urls_page(request: Request):
        ctx = _get_profile_context(request)
        return _render(request, "urls.html", ctx)

    @app.get("/update", response_class=HTMLResponse)
    def update_page(request: Request):
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

    from asc.web import routes_api, routes_listing, routes_agent
    app.include_router(routes_api.router, prefix="/api")
    app.include_router(routes_listing.router, prefix="/api/listing")
    app.include_router(routes_agent.router, prefix="/api/agent")

    return app
