"""Main CLI entry point for asc"""

from __future__ import annotations

import os
import sys
import warnings
from typing import Optional

# Suppress SSL warnings from urllib3 (not relevant to end users)
warnings.filterwarnings("ignore", message=".*urllib3.*OpenSSL.*")
warnings.filterwarnings("ignore", message=".*ssl.*LibreSSL.*")

import typer

# Monkey-patch typer.Exit to log errors before Typer handles them
_original_exit_class = typer.Exit

class LoggedExit(_original_exit_class):
    """Extended Exit that logs errors before raising."""

    def __init__(self, code: int = 1, message: str = ""):
        # Log the error to .asc/error.log before Typer handles it
        try:
            from asc.error_handler import is_debug, ensure_error_log_dir, get_error_log_path
            if is_debug():
                # In debug mode, use handle_error to show full traceback
                from asc.error_handler import handle_error
                exc = _original_exit_class(code)
                handle_error('cli', 'unknown', exc)
            else:
                # In non-debug mode, log simple message
                ensure_error_log_dir()
                log_path = get_error_log_path()
                from datetime import datetime
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                error_msg = message or f"Exit with code {code}"
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"{timestamp} | ERROR | cli | unknown | {error_msg}\n")
        except Exception:
            pass  # Don't fail if logging fails
        super().__init__(code)

# Replace typer.Exit with our logging version
typer.Exit = LoggedExit  # type: ignore

from asc import __version__
from asc.i18n import t, HELP, LANG, patch_typer_completion

patch_typer_completion()

app = typer.Typer(
    name="asc",
    help="App Store Connect CLI tool",
    no_args_is_help=True,
    context_settings={"help_option_names": ["--help", "-h"], "max_content_width": 120},
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
    debug: Optional[bool] = typer.Option(
        None, "--debug", "-d", envvar="ASC_DEBUG", is_eager=True,
        help={"en": "Enable debug mode with full traceback output", "zh": "启用调试模式，显示完整调用栈"}[LANG],
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
    if debug is not None:
        os.environ["_ASC_DEBUG"] = "1" if debug else "0"

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
from asc.commands.update_cmd import cmd_update
from asc.commands.uninstall_cmd import cmd_uninstall

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
app.command("update",              help=t(HELP['cmd_update']))(cmd_update)
app.command("uninstall",           help=t(HELP['cmd_uninstall']))(cmd_uninstall)

from asc.commands.guard_cmd import guard_app
app.add_typer(guard_app, name="guard")

# Install global exception handler (runs at module import time)
from asc.error_handler import install
install()


def run_app() -> int:
    """Run the Typer app with standalone_mode=False to allow exception propagation.

    This enables our global exception handler to catch and log ALL errors,
    including those that Typer would normally handle internally (like typer.Exit).
    """
    return app(standalone_mode=False)


# Entry point for: python -m asc
if __name__ == "__main__":
    import sys
    sys.exit(run_app())
