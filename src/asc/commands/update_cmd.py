"""asc update — check for and install the latest version from GitHub."""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Optional

import typer
import requests

GITHUB_API = "https://api.github.com/repos/yinghuiwang/AppStoreTools/releases/latest"
INSTALL_URL = "https://github.com/yinghuiwang/AppStoreTools.git"
PACKAGE_NAME = "asc-appstore-tools"


def _current_version() -> str:
    from importlib.metadata import version
    return version(PACKAGE_NAME)


def _is_editable() -> bool:
    try:
        from importlib.metadata import distribution
        import json as _json
        dist = distribution(PACKAGE_NAME)
        direct_url = dist.read_text("direct_url.json")
        if direct_url:
            info = _json.loads(direct_url)
            return info.get("dir_info", {}).get("editable", False)
    except Exception:
        pass
    return False


def _latest_version_from_github() -> Optional[str]:
    try:
        resp = requests.get(GITHUB_API, timeout=8)
        resp.raise_for_status()
        tag = resp.json().get("tag_name", "")
        return tag.lstrip("v") if tag else None
    except Exception:
        return None


def _parse_version(v: str):
    try:
        from packaging.version import Version
        return Version(v)
    except Exception:
        return tuple(int(x) for x in v.split(".") if x.isdigit())


def cmd_update(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt (for CI/scripts)."),
):
    """Check for updates and install the latest version from GitHub."""
    if _is_editable():
        typer.echo("Running in development mode (editable install). Skipping auto-update.")
        typer.echo(f"To update manually: git pull && pip install -e .")
        return

    current = _current_version()
    typer.echo(f"Checking for updates...")
    typer.echo(f"Current version : {current}")

    latest = _latest_version_from_github()
    if not latest:
        typer.echo("Unable to reach GitHub. Check your internet connection.", err=True)
        raise typer.Exit(1)

    typer.echo(f"Latest version  : {latest}  (github.com/yinghuiwang/AppStoreTools)")

    if _parse_version(latest) <= _parse_version(current):
        typer.echo(f"\nasc is already up to date ({current}).")
        return

    typer.echo(f"\nUpdate available: {current} → {latest}")
    if not yes:
        confirm = typer.confirm("Install now?", default=True)
        if not confirm:
            typer.echo("Update cancelled.")
            return

    typer.echo(f"Updating asc to {latest}...")
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "--quiet",
            f"git+https://github.com/yinghuiwang/AppStoreTools.git@v{latest}",
        ])
        typer.echo(f"Done. asc updated to {latest}.")
        typer.echo("Restart your shell or re-run asc for the new version.")
    except subprocess.CalledProcessError:
        typer.echo("Update failed. Try manually:", err=True)
        typer.echo(f"  pip install git+https://github.com/yinghuiwang/AppStoreTools.git@v{latest}", err=True)
        raise typer.Exit(1)
