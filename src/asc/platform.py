"""Shared OS capability checks for the CLI and the local Web UI.

Windows cannot run the Apple toolchain (xcodebuild, codesign, provisioning
profiles, altool / notarytool). Review schedules stay available: Windows wakes
``asc schedule tick`` with Task Scheduler, and macOS / Linux keep launchd or
cron. Metadata, screenshots, IAP, What's New, URLs, app profiles, Guard, and
the Web UI itself stay available.

The Web UI grays the Apple toolchain out only on Windows, so macOS and other
systems keep their current screens. The CLI still refuses the Apple toolchain
on every non-macOS system.
"""

from __future__ import annotations

import sys

# Local signing, archive, export, and IPA upload.
APPLE_TOOLCHAIN_FEATURES = ("build", "deploy", "release")

# Features the Web UI disables when the server itself is running on Windows.
WINDOWS_DISABLED_FEATURES = APPLE_TOOLCHAIN_FEATURES


def normalize_system(system: str | None = None) -> str:
    """Return ``windows``, ``darwin``, ``linux``, or the lowercased name."""
    raw = sys.platform if system is None else system
    name = str(raw or "").strip().lower().replace("-", "")
    if name in {"win32", "windows", "cygwin"} or name.startswith("win"):
        return "windows"
    if name in {"darwin", "macos", "macosx"}:
        return "darwin"
    if name.startswith("linux"):
        return "linux"
    return name


def is_windows(system: str | None = None) -> bool:
    return normalize_system(system) == "windows"


def is_darwin(system: str | None = None) -> bool:
    return normalize_system(system) == "darwin"


def feature_supported(feature: str, system: str | None = None) -> bool:
    """Whether the Web UI should keep *feature* enabled on *system*.

    Non-Windows systems stay enabled. Windows disables only
    ``WINDOWS_DISABLED_FEATURES`` (the Apple toolchain).
    """
    if not is_windows(system):
        return True
    return feature not in WINDOWS_DISABLED_FEATURES


def cli_allows(feature: str, system: str | None = None) -> bool:
    """Whether a CLI command may proceed on *system*.

    Apple toolchain commands remain macOS-only. Schedules run on macOS, Linux,
    and Windows. Everything else is allowed.
    """
    name = normalize_system(system)
    if feature in APPLE_TOOLCHAIN_FEATURES:
        return name == "darwin"
    return True


def web_unsupported_features(system: str | None = None) -> list[str]:
    if not is_windows(system):
        return []
    return [feature for feature in WINDOWS_DISABLED_FEATURES if not feature_supported(feature, system)]


def platform_status(system: str | None = None) -> dict[str, object]:
    """Payload embedded in ``GET /api/bootstrap``.

    ``system`` is the server OS, never the browser user agent.
    """
    name = normalize_system(system)
    labels = {"windows": "Windows", "darwin": "Darwin", "linux": "Linux"}
    return {
        "system": labels.get(name, name),
        "windows": name == "windows",
        "unsupported": web_unsupported_features(name),
    }
