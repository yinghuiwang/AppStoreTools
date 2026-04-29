"""asc uninstall — remove asc-appstore-tools from the system."""
from __future__ import annotations

import subprocess
import sys

import typer

PACKAGE_NAME = "asc-appstore-tools"


def cmd_uninstall(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
):
    """Uninstall asc-appstore-tools from this system."""
    if not yes:
        confirm = typer.confirm(f"Uninstall {PACKAGE_NAME}?", default=False)
        if not confirm:
            typer.echo("Cancelled.")
            return

    typer.echo(f"Uninstalling {PACKAGE_NAME}...")
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "uninstall", "-y", PACKAGE_NAME,
        ])
        typer.echo("Done. asc has been removed.")
    except subprocess.CalledProcessError:
        typer.echo(f"Failed to uninstall. Try manually: pip uninstall {PACKAGE_NAME}", err=True)
        raise typer.Exit(1)
