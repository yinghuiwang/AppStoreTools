"""Build, deploy, and release commands for asc CLI."""
from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

import typer


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
    if result.returncode != 0:
        raise RuntimeError(f"xcodebuild -list failed:\n{result.stderr}")

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


def generate_export_options(
    signing: str,
    destination: str,
    profile: str | None,
    certificate: str | None,
    output_dir: str,
) -> str:
    """Generate ExportOptions.plist and return its path.

    Args:
        signing: "auto" or "manual"
        destination: "appstore" or "testflight" (reserved for future use; both currently use app-store-connect method)
        profile: Provisioning profile path (required for manual signing)
        certificate: Certificate name (optional for manual signing)
        output_dir: Directory to write ExportOptions.plist

    Returns:
        Path to generated ExportOptions.plist

    Raises:
        ValueError: If signing is "manual" but profile is None
    """
    if signing == "manual" and not profile:
        raise ValueError("Manual signing requires a provisioning profile")

    opts: dict = {
        "method": "app-store-connect",
        "signingStyle": "automatic" if signing == "auto" else "manual",
    }
    if signing == "manual":
        if certificate:
            opts["signingCertificate"] = certificate
        if profile:
            opts["provisioningProfiles"] = {"": profile}

    plist_path = Path(output_dir) / "ExportOptions.plist"
    with open(plist_path, "wb") as f:
        plistlib.dump(opts, f)
    return str(plist_path)
