"""Build, deploy, and release commands for asc CLI."""
from __future__ import annotations

import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import typer

from asc.config import Config
from asc.utils import make_api_from_config


def _require_macos() -> None:
    if sys.platform != "darwin":
        typer.echo("❌ 此命令仅支持 macOS", err=True)
        raise typer.Exit(2)


def detect_project(path: str) -> tuple[str, str]:
    """Return (project_path, kind) where kind is 'workspace' or 'project'.

    If path points directly to a .xcworkspace or .xcodeproj, return it.
    Otherwise search the directory for one, preferring .xcworkspace.
    """
    p = Path(path)

    if p.suffix == ".xcworkspace":
        return str(p), "workspace"
    if p.suffix == ".xcodeproj":
        return str(p), "project"

    # Search directory
    workspaces = list(p.glob("*.xcworkspace"))
    if workspaces:
        return str(workspaces[0]), "workspace"

    projects = list(p.glob("*.xcodeproj"))
    if projects:
        return str(projects[0]), "project"

    raise ValueError(f"No Xcode project or workspace found in: {path}")


def list_schemes(project_path: str, kind: str) -> list[str]:
    """Return list of scheme names from xcodebuild -list."""
    flag = "-workspace" if kind == "workspace" else "-project"
    result = subprocess.run(
        ["xcodebuild", flag, project_path, "-list"],
        capture_output=True, text=True,
    )
    schemes: list[str] = []
    in_schemes = False
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped == "Schemes:":
            in_schemes = True
            continue
        if in_schemes:
            if stripped and not stripped.endswith(":"):
                schemes.append(stripped)
            elif stripped.endswith(":") and stripped != "Schemes:":
                break
    return schemes
