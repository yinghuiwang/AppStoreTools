"""Main CLI entry point for asc"""

from __future__ import annotations

import os
from typing import Optional

import typer

from asc import __version__

app = typer.Typer(
    name="asc",
    help="App Store Connect CLI tool",
    no_args_is_help=True,
)
app_cmd = typer.Typer(help="Manage app profiles", no_args_is_help=True)
app.add_typer(app_cmd, name="app")


def version_callback(value: bool):
    if value:
        typer.echo(f"asc version {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", callback=version_callback, is_eager=True,
        help="Show version information",
    ),
    app: Optional[str] = typer.Option(
        None, "--app", help="App profile name (from 'asc app add')",
        is_eager=True,
    ),
):
    """App Store Connect CLI — upload metadata, screenshots, IAP, and subscriptions.

    This tool helps you manage your App Store Connect content including:

    \b
    • Metadata: app names, subtitles, descriptions, keywords
    • URLs: support, marketing, privacy policy
    • Screenshots for all device types
    • In-App Purchases (IAP) and Subscriptions
    • Release notes (What's New)

    \b
    Configuration priority (highest to lowest):
    1. CLI arguments (--app, --csv, etc.)
    2. Local .asc/config.toml
    3. Global ~/.config/asc/profiles/<name>.toml
    4. Environment variables

    \b
    First time? Run 'asc app add' to set up your credentials.
    """
    if app:
        os.environ["_ASC_APP"] = app


from asc.commands.metadata import (
    cmd_check,
    cmd_keywords,
    cmd_marketing_url,
    cmd_metadata,
    cmd_privacy_policy_url,
    cmd_set_marketing_url,
    cmd_set_privacy_policy_url,
    cmd_set_support_url,
    cmd_support_url,
    cmd_upload,
)
from asc.commands.screenshots import cmd_screenshots
from asc.commands.iap import cmd_iap
from asc.commands.whats_new import cmd_whats_new
from asc.commands.app_config import cmd_app_add, cmd_app_list, cmd_app_remove, cmd_app_default, cmd_install, cmd_app_show, cmd_app_edit
from asc.commands.build import cmd_build, cmd_deploy, cmd_release

app.command("upload")(cmd_upload)
app.command("metadata")(cmd_metadata)
app.command("keywords")(cmd_keywords)
app.command("support-url")(cmd_support_url)
app.command("marketing-url")(cmd_marketing_url)
app.command("privacy-policy-url")(cmd_privacy_policy_url)
app.command("set-support-url")(cmd_set_support_url)
app.command("set-marketing-url")(cmd_set_marketing_url)
app.command("set-privacy-policy-url")(cmd_set_privacy_policy_url)
app.command("screenshots")(cmd_screenshots)
app.command("iap")(cmd_iap)
app.command("whats-new")(cmd_whats_new)
app.command("check")(cmd_check)
app_cmd.command("add")(cmd_app_add)
app_cmd.command("list")(cmd_app_list)
app_cmd.command("remove")(cmd_app_remove)
app_cmd.command("default")(cmd_app_default)
app_cmd.command("show")(cmd_app_show)
app_cmd.command("edit")(cmd_app_edit)
app.command("install")(cmd_install)
app.command("build")(cmd_build)
app.command("deploy")(cmd_deploy)
app.command("release")(cmd_release)

from asc.commands.guard_cmd import guard_app
app.add_typer(guard_app, name="guard")
