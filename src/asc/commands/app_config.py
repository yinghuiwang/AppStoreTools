"""App profile management commands"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import typer

from asc.config import Config


def cmd_app_add(
    name: str = typer.Argument(..., help="Profile name for this app (used with --app)"),
):
    """Interactively add a new app profile.

    This command guides you through setting up credentials for App Store Connect API.
    You'll need your App Store Connect API key details (Issuer ID, Key ID, .p8 private key)
    and your app's numeric ID.

    \b
    The profile stores:
    - API credentials (Issuer ID, Key ID, key file path)
    - Default paths for CSV and screenshots
    - App ID

    \b
    Example:
        asc app add myapp
        asc app add production-app
    """
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
    """List all configured app profiles.

    Shows all app profiles that have been configured via 'asc app add'.

    \b
    Example:
        asc app list
    """
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
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Remove an app profile.

    Deletes the profile configuration saved in ~/.config/asc/profiles/.

    \b
    Example:
        asc app remove myapp
        asc app remove myapp --yes
    """
    if not yes:
        confirmed = typer.confirm(f"Remove app profile '{name}'?")
        if not confirmed:
            raise typer.Abort()
    config = Config()
    config.remove_app_profile(name)
    typer.echo(f"✅ App profile '{name}' removed.")


def cmd_app_default(
    name: str = typer.Argument(..., help="Profile name to set as default"),
):
    """Set or update the default app profile.

    Writes the default app to .asc/config.toml in the current directory.
    When no --app is specified, commands will use this default profile.

    \b
    Example:
        asc app default myapp
        asc app default production-app
    """
    local_dir = Path.cwd() / ".asc"
    local_dir.mkdir(parents=True, exist_ok=True)
    config_file = local_dir / "config.toml"

    # Check if profile exists
    config = Config()
    apps = config.list_apps()
    if name not in apps:
        typer.echo(f"❌ Profile '{name}' not found. Available profiles:", err=True)
        for app_name in apps:
            typer.echo(f"  • {app_name}")
        raise typer.Exit(1)

    # Read existing config or create new
    existing = ""
    if config_file.exists():
        existing = config_file.read_text()

    # Update or create default_app setting
    if "[defaults]" in existing:
        # Update existing section
        lines = existing.splitlines()
        new_lines = []
        found_default = False
        for line in lines:
            if line.strip().startswith("default_app"):
                new_lines.append(f'default_app = "{name}"')
                found_default = True
            else:
                new_lines.append(line)
        if not found_default:
            # Insert after [defaults] line
            result = []
            for line in new_lines:
                result.append(line)
                if line.strip() == "[defaults]":
                    result.append(f'default_app = "{name}"')
            existing = "\n".join(result)
        else:
            existing = "\n".join(new_lines)
    else:
        # Add new section
        if existing.strip():
            existing = existing.rstrip() + "\n\n"
        else:
            existing = ""
        existing += """[defaults]
default_app = "{name}"
"""

    config_file.write_text(existing.format(name=name))
    typer.echo(f"✅ Default app profile set to '{name}'")
    typer.echo(f"   Config written to: {config_file.relative_to(Path.cwd())}")
    typer.echo(f"   Run 'asc upload' without --app to use this default.")
