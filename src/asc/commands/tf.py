"""Read-only TestFlight Beta Review commands."""

from __future__ import annotations

import os
from typing import Optional

import typer

from asc.config import Config
from asc.error_handler import get_action_hint
from asc.i18n import HELP, TF_TEXT, t
from asc.testflight import fetch_testflight_builds
from asc.utils import make_api_from_config, resolve_app_profile

tf_app = typer.Typer(help=t(HELP["cmd_tf"]), no_args_is_help=True)


def _tf(key: str, **params: object) -> str:
    text = t(TF_TEXT[key])
    return text.format(**params) if params else text


def _resolve_config(app: Optional[str]) -> tuple:
    config = Config(app)
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env

        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        os.environ.pop("_ASC_APP", None)
    config = Config(resolved_app)
    return resolved_app, config


@tf_app.command("status", help=t(HELP["cmd_tf_status"]))
def cmd_tf_status(
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP["app_profile_name"])),
) -> None:
    """Show TestFlight external-group Beta Review status.

    \b
    Example:
        asc --app myapp tf status
        asc tf status --app myapp
    """
    resolved, config = _resolve_config(app)
    api, app_id = make_api_from_config(config)
    try:
        builds = fetch_testflight_builds(api, app_id)
    except Exception as exc:
        typer.echo(_tf("failed", error=exc), err=True)
        hint = get_action_hint(exc)
        if hint:
            typer.echo(f"💡 {hint}", err=True)
        raise typer.Exit(1)
    typer.echo(_tf("title"))
    typer.echo(f"{_tf('app')}: {resolved or config.app_name or ''} ({app_id})")
    if not builds:
        typer.echo(_tf("empty"))
        return
    header = [
        _tf("col_build"),
        _tf("col_groups"),
        _tf("col_beta_review"),
        _tf("col_external_state"),
    ]
    typer.echo("  ".join(header))
    for build in builds:
        groups = "、".join(build.external_groups) if build.external_groups else _tf("none_external")
        typer.echo(
            "  ".join(
                [
                    build.version or "-",
                    groups,
                    build.beta_review_state or "-",
                    build.external_build_state or "-",
                ]
            )
        )
