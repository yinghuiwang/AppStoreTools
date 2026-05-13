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


def _all_versions_from_github() -> Optional[list[str]]:
    """Fetch all release versions from GitHub."""
    try:
        resp = requests.get(
            "https://api.github.com/repos/yinghuiwang/AppStoreTools/releases",
            timeout=8
        )
        resp.raise_for_status()
        releases = resp.json()
        versions = []
        for release in releases:
            tag = release.get("tag_name", "")
            if tag:
                versions.append(tag.lstrip("v"))
        return versions
    except Exception:
        return None


def _similar_versions(target: str, all_versions: list[str], limit: int = 3) -> list[str]:
    """Return the most similar versions to target using version distance."""
    from packaging.version import Version

    def version_distance(v1: str, v2: str) -> int:
        try:
            p1 = Version(v1.lstrip("v"))
            p2 = Version(v2.lstrip("v"))
            # Distance based on major.minor.patch difference
            d1 = abs(p1.major - p2.major) * 1000
            d2 = abs(p1.minor - p2.minor) * 100
            d3 = abs(p1.micro - p2.micro) * 10
            return d1 + d2 + d3
        except Exception:
            # Fallback: string similarity
            return abs(len(v1) - len(v2))

    scored = [(version_distance(target, v), v) for v in all_versions]
    scored.sort()
    return [v for _, v in scored[:limit]]


def cmd_update(
    version: Optional[str] = typer.Option(None, "--version", help="Install a specific version."),
    branch: Optional[str] = typer.Option(None, "--branch", help="Install from a specific branch."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt (for CI/scripts)."),
):
    """Check for updates and install the latest version from GitHub."""
    if version and branch:
        typer.echo("❌ Cannot use --version and --branch at the same time.", err=True)
        raise typer.Exit(1)

    if _is_editable():
        typer.echo("Running in development mode (editable install). Skipping auto-update.")
        typer.echo(f"To update manually: git pull && pip install -e .")
        return

    if branch:
        # Branch installation
        typer.echo(f"Installing from branch '{branch}'...")
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--quiet",
                f"git+https://github.com/yinghuiwang/AppStoreTools.git@{branch}",
            ])
            typer.echo(f"Done. asc installed from branch '{branch}'.")
        except subprocess.CalledProcessError:
            typer.echo("Update failed. Try manually:", err=True)
            typer.echo(f"  pip install git+https://github.com/yinghuiwang/AppStoreTools.git@{branch}", err=True)
            raise typer.Exit(1)
        return

    if version:
        # Specific version installation
        target_version = version.lstrip("v")
        typer.echo(f"Installing version {target_version}...")

        # Check if version exists
        all_versions = _all_versions_from_github()
        if all_versions and f"v{target_version}" not in [f"v{v}" for v in all_versions]:
            similar = _similar_versions(target_version, all_versions)
            similar_str = ", ".join(f"v{v}" for v in similar) if similar else "N/A"
            typer.echo(f"❌ Version v{target_version} not found.", err=True)
            if similar:
                typer.echo(f"Similar versions: {similar_str}", err=True)
            raise typer.Exit(1)

        install_version = f"v{target_version}"
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--quiet",
                f"git+https://github.com/yinghuiwang/AppStoreTools.git@{install_version}",
            ])
            typer.echo(f"Done. asc updated to v{target_version}.")
        except subprocess.CalledProcessError:
            typer.echo("Update failed. Try manually:", err=True)
            typer.echo(f"  pip install git+https://github.com/yinghuiwang/AppStoreTools.git@{install_version}", err=True)
            raise typer.Exit(1)
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
