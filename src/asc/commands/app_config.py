"""App profile management commands"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import typer

from asc.config import Config


def cmd_app_add(
    name: str = typer.Argument(..., help="Profile name for this app"),
):
    """Interactively add a new app profile"""
    typer.echo(f"Adding app profile: {name}")
    typer.echo("Enter your App Store Connect credentials:")

    issuer_id = typer.prompt("  Issuer ID")
    key_id = typer.prompt("  Key ID")
    key_file_input = typer.prompt("  Path to .p8 private key file")
    app_id = typer.prompt("  App ID (numeric)")

    typer.echo("\nEnter default data paths (press Enter to use defaults):")
    csv_path = typer.prompt(
        "  CSV metadata file path", default="data/appstore_info.csv"
    )
    screenshots_path = typer.prompt(
        "  Screenshots directory", default="data/screenshots"
    )

    key_path = Path(key_file_input).expanduser()
    if not key_path.exists():
        typer.echo(f"❌ Key file not found: {key_path}", err=True)
        raise typer.Exit(1)

    global_keys_dir = Path.home() / ".config" / "asc" / "keys"
    global_keys_dir.mkdir(parents=True, exist_ok=True)
    dest_key = global_keys_dir / key_path.name
    if not dest_key.exists():
        shutil.copy2(key_path, dest_key)
        typer.echo(f"  ✅ Key file copied to {dest_key}")

    config = Config()
    config.save_app_profile(
        name, issuer_id, key_id, str(dest_key), app_id, csv_path, screenshots_path
    )
    typer.echo(f"\n✅ App profile '{name}' saved.")
    typer.echo(f"   Use: asc --app {name} upload")


def cmd_app_list():
    """List all configured app profiles"""
    config = Config()
    apps = config.list_apps()
    if not apps:
        typer.echo("No app profiles configured.")
        typer.echo("Run: asc app add <name>")
        return
    typer.echo("Configured app profiles:")
    for app_name in apps:
        typer.echo(f"  • {app_name}")


def cmd_app_remove(
    name: str = typer.Argument(..., help="Profile name to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove an app profile"""
    if not yes:
        confirmed = typer.confirm(f"Remove app profile '{name}'?")
        if not confirmed:
            raise typer.Abort()
    config = Config()
    config.remove_app_profile(name)
    typer.echo(f"✅ App profile '{name}' removed.")
