"""Main CLI entry point for asc"""

from __future__ import annotations

import os
from typing import Optional

import typer

from asc import __version__
from asc.i18n import t, HELP, patch_typer_completion

patch_typer_completion()

app = typer.Typer(
    name="asc",
    help="App Store Connect CLI tool",
    no_args_is_help=True,
    context_settings={"help_option_names": ["--help"], "max_content_width": 120},
)
app_cmd = typer.Typer(help=t(HELP['cmd_app']), no_args_is_help=True)
app.add_typer(app_cmd, name="app")


def version_callback(value: bool):
    if value:
        typer.echo(f"asc version {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True,
        help=t(HELP['version_info']),
    ),
    app: Optional[str] = typer.Option(
        None, "--app", "-a", help=t(HELP['app_profile_name']),
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
from asc.commands.app_config import cmd_app_add, cmd_app_list, cmd_app_remove, cmd_app_default, cmd_install, cmd_app_show, cmd_app_edit, cmd_app_import, cmd_init
from asc.commands.build import cmd_build, cmd_deploy, cmd_release

app.command("upload",              help=t(HELP['cmd_upload']))(cmd_upload)
app.command("metadata",            help=t(HELP['cmd_metadata']))(cmd_metadata)
app.command("keywords",            help=t(HELP['cmd_keywords']))(cmd_keywords)
app.command("support-url",         help=t(HELP['cmd_support_url']))(cmd_support_url)
app.command("marketing-url",       help=t(HELP['cmd_marketing_url']))(cmd_marketing_url)
app.command("privacy-policy-url",  help=t(HELP['cmd_privacy_policy_url']))(cmd_privacy_policy_url)
app.command("set-support-url",     help=t(HELP['cmd_set_support_url']))(cmd_set_support_url)
app.command("set-marketing-url",   help=t(HELP['cmd_set_marketing_url']))(cmd_set_marketing_url)
app.command("set-privacy-policy-url", help=t(HELP['cmd_set_privacy_policy_url']))(cmd_set_privacy_policy_url)
app.command("screenshots",         help=t(HELP['cmd_screenshots']))(cmd_screenshots)
app.command("iap",                 help=t(HELP['cmd_iap']))(cmd_iap)
app.command("whats-new",           help=t(HELP['cmd_whats_new']))(cmd_whats_new)
app.command("check",               help=t(HELP['cmd_check']))(cmd_check)
app_cmd.command("add",             help=t(HELP['cmd_app_add']))(cmd_app_add)
app_cmd.command("list",            help=t(HELP['cmd_app_list']))(cmd_app_list)
app_cmd.command("remove",          help=t(HELP['cmd_app_remove']))(cmd_app_remove)
app_cmd.command("default",         help=t(HELP['cmd_app_default']))(cmd_app_default)
app_cmd.command("show",            help=t(HELP['cmd_app_show']))(cmd_app_show)
app_cmd.command("edit",            help=t(HELP['cmd_app_edit']))(cmd_app_edit)
app_cmd.command("import",          help=t(HELP['cmd_app_import']))(cmd_app_import)
app.command("install",             help=t(HELP['cmd_install']))(cmd_install)
app.command("init",                help=t(HELP['cmd_init']))(cmd_init)
app.command("build",               help=t(HELP['cmd_build']))(cmd_build)
app.command("deploy",              help=t(HELP['cmd_deploy']))(cmd_deploy)
app.command("release",             help=t(HELP['cmd_release']))(cmd_release)

from asc.commands.guard_cmd import guard_app
app.add_typer(guard_app, name="guard")
