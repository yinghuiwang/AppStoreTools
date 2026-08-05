"""asc update — check for and install the latest version from GitHub."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Optional

import typer
import requests

from asc.reporting import TaskReporter, make_cli_reporter

GITHUB_API = "https://api.github.com/repos/yinghuiwang/AppStoreTools/releases/latest"
INSTALL_URL = "https://github.com/yinghuiwang/AppStoreTools.git"
PACKAGE_NAME = "asc-appstore-tools"

# Overall pip timeout (clone + build + install). Web self-update can be slow on
# cold caches; fail with a clear message instead of hanging forever.
PIP_INSTALL_TIMEOUT_SEC = 900

# pip / git clone progress hints
_PIP_PCT_RE = re.compile(r"(?<![.\d])(\d{1,3})%(?!\d)")
_PIP_DOWNLOAD_RE = re.compile(
    r"(?i)\b(Downloading|Download complete|Cloning|Obtaining|Collecting|Fetching)\b"
)
_PIP_INSTALL_RE = re.compile(
    r"(?i)\b(Installing|Building wheel|Prepared|Successfully installed|Installing collected|Attempting uninstall)\b"
)


@dataclass(frozen=True)
class UpdateResult:
    """Outcome of ``_update_core``.

    ``changed`` is True when a package install ran *or* was deferred for
    post-restart install (Web UI self-update).
    """

    changed: bool
    deferred: bool = False
    install_ref: Optional[str] = None
    commit: Optional[str] = None
    message: Optional[str] = None

    def __bool__(self) -> bool:
        return self.changed


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


def _branches_from_github() -> Optional[list[str]]:
    """Fetch branch names from the GitHub remote."""
    try:
        output = subprocess.check_output(
            ["git", "ls-remote", "--heads", INSTALL_URL],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        return None

    branches = []
    prefix = "refs/heads/"
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].startswith(prefix):
            branches.append(parts[1][len(prefix):])
    return sorted(set(branches))


def _resolve_git_ref_commit(ref: str) -> Optional[str]:
    """Resolve a branch or tag ref to the commit hash that should be installed."""
    candidates = [
        f"refs/tags/{ref}^{{}}",
        f"refs/tags/{ref}",
        f"refs/heads/{ref}",
        ref,
    ]
    try:
        output = subprocess.check_output(
            ["git", "ls-remote", INSTALL_URL, *candidates],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        return None

    matches: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            matches[parts[1]] = parts[0]

    for candidate in candidates:
        if candidate in matches:
            return matches[candidate]
    return None


def _pip_install_env() -> dict[str, str]:
    """Environment for pip so progress/uninstall lines flush through pipes."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Avoid pip wrapping progress in a TTY-only spinner that never flushes to pipes.
    env.setdefault("PIP_PROGRESS_BAR", "on")
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    return env


def _pip_install_cmd(install_ref: str, *, no_deps: bool = False) -> list[str]:
    """Build the pip install command (no --quiet so progress/logs are visible).

    ``no_deps`` avoids uninstalling shared runtime deps (Pillow/FastAPI/…) while a
    live Web UI process still has them mapped — used only as a last-resort
    in-process install. Prefer deferred install after stop for Web updates.
    """
    cmd = [
        sys.executable,
        "-u",
        "-m",
        "pip",
        "install",
        "--progress-bar",
        "on",
        "--upgrade",
        "--force-reinstall",
    ]
    if no_deps:
        cmd.append("--no-deps")
    cmd.append(f"git+{INSTALL_URL}@{install_ref}")
    return cmd


def _extract_pip_percent(line: str) -> Optional[int]:
    """Return 0–100 if *line* contains a progress percentage."""
    matches = _PIP_PCT_RE.findall(line)
    if not matches:
        return None
    value = int(matches[-1])
    if 0 <= value <= 100:
        return value
    return None


def _install_git_ref(
    ref: str,
    commit: Optional[str] = None,
    *,
    reporter: TaskReporter | None = None,
    no_deps: bool = False,
    timeout: float = PIP_INSTALL_TIMEOUT_SEC,
) -> None:
    """Install from git ref, streaming pip output into *reporter* when provided."""
    install_ref = commit or ref
    cmd = _pip_install_cmd(install_ref, no_deps=no_deps)
    env = _pip_install_env()
    if reporter is None:
        subprocess.check_call(cmd, env=env, timeout=timeout)
        return

    reporter.log(f"$ {' '.join(cmd)}")
    if no_deps:
        reporter.log(
            "Installing package only (--no-deps); shared deps will not be reinstalled."
        )
    reporter.log(
        f"Downloading / installing package (pip, timeout={int(timeout)}s, unbuffered)..."
    )

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None

    line_queue: Queue[str | None] = Queue()

    def _reader() -> None:
        try:
            for raw in proc.stdout:
                line_queue.put(raw)
        finally:
            line_queue.put(None)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    in_install_phase = False
    last_reported_pct = -1
    download_floor = 5  # keep bar moving when pip has no percent yet
    last_output_at = time.monotonic()
    last_heartbeat_at = last_output_at
    deadline = time.monotonic() + float(timeout)
    timed_out = False

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            try:
                raw = line_queue.get(timeout=min(1.0, remaining))
            except Empty:
                # Heartbeat while pip is silent (e.g. long uninstall / compile).
                now = time.monotonic()
                silent_for = now - last_output_at
                if silent_for >= 30 and now - last_heartbeat_at >= 30:
                    reporter.log(
                        f"… pip still running ({int(silent_for)}s since last output; "
                        f"uninstall/install of native deps can be slow)"
                    )
                    last_heartbeat_at = now
                # Only stop after the reader thread drained stdout (avoids racing
                # an early proc.poll() against still-queued lines).
                if proc.poll() is not None and not reader.is_alive() and line_queue.empty():
                    break
                continue

            if raw is None:
                break

            last_output_at = time.monotonic()
            line = raw.rstrip("\n\r")
            if not line.strip():
                continue
            reporter.log(line)

            if not in_install_phase and _PIP_INSTALL_RE.search(line):
                reporter.phase("install")
                in_install_phase = True
                last_reported_pct = -1

            pct = _extract_pip_percent(line)
            if pct is not None:
                if pct == last_reported_pct:
                    continue
                last_reported_pct = pct
                label = "Downloading" if not in_install_phase else "Installing"
                reporter.progress(pct, 100, msg=f"{label} {pct}%")
                continue

            if not in_install_phase and _PIP_DOWNLOAD_RE.search(line):
                download_floor = min(95, download_floor + 8)
                if download_floor > last_reported_pct:
                    last_reported_pct = download_floor
                    reporter.progress(download_floor, 100, msg="downloading")
    finally:
        if timed_out:
            reporter.log(
                f"❌ pip install timed out after {int(timeout)}s "
                "(often caused by uninstalling packages still used by a running Web UI).",
                level="error",
            )
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
            raise TimeoutError(f"pip install timed out after {int(timeout)}s")

        returncode = proc.wait(timeout=30)

    reader.join(timeout=5)

    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)

    if not in_install_phase:
        reporter.phase("install")
    reporter.progress(1, 1, msg="installed")


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


def _update_phase_plan() -> list[tuple[str, int, str]]:
    return [("download", 70, "下载"), ("install", 30, "安装")]


class UpdateError(Exception):
    """User-facing update failure (maps to non-zero CLI exit)."""


def _install_with_reporter(
    reporter: TaskReporter,
    *,
    install_ref: str,
    commit: Optional[str],
    success_message: str,
    fail_hint: str,
    no_deps: bool = False,
) -> None:
    # Stay on "download" until pip output signals install; stream all pip logs.
    reporter.log(f"Starting install from git ref '{install_ref}'...")
    try:
        _install_git_ref(
            install_ref,
            commit,
            reporter=reporter,
            no_deps=no_deps,
        )
    except subprocess.CalledProcessError as exc:
        reporter.fail("Update failed. Try manually:")
        reporter.log(f"  {fail_hint}", level="error")
        raise UpdateError("install failed") from exc
    except TimeoutError as exc:
        reporter.fail(str(exc))
        reporter.log(f"  {fail_hint}", level="error")
        raise UpdateError("install timed out") from exc
    # Ensure install phase is marked complete (streaming install usually already did this).
    reporter.phase("install")
    reporter.progress(1, 1, msg="installed")
    reporter.done(success_message)


def _defer_install_outcome(
    reporter: TaskReporter,
    *,
    install_ref: str,
    commit: Optional[str],
    success_message: str,
) -> UpdateResult:
    """Skip in-process pip; Web restart helper will install after stop."""
    reporter.log(
        "Web UI is running in this environment — deferring pip install until "
        "after the server stops (avoids hanging on uninstall of Pillow/FastAPI "
        "while the process still holds them)."
    )
    reporter.phase("install")
    reporter.progress(1, 1, msg="deferred")
    reporter.done(
        "Install scheduled after Web UI restart. "
        + (success_message or "")
    )
    return UpdateResult(
        changed=True,
        deferred=True,
        install_ref=install_ref,
        commit=commit,
        message=success_message,
    )


def _update_core(
    *,
    version: Optional[str] = None,
    branch: Optional[str] = None,
    yes: bool = False,
    reporter: TaskReporter | None = None,
    confirm: bool = False,
    verbose: bool = False,
    defer_install: bool = False,
) -> UpdateResult:
    """Shared update logic for CLI and Web.

    ``confirm``: when True and ``yes`` is False, prompt before installing the
    latest release (CLI interactive path only).

    ``defer_install``: when True (Web UI), resolve the target and return a
    deferred plan so pip runs only after the server process has stopped.

    Returns an ``UpdateResult`` (truthy when install ran or was deferred).
    """
    if reporter is None:
        reporter = make_cli_reporter(verbose=verbose)

    if version and branch:
        msg = "Cannot use --version and --branch at the same time."
        reporter.fail(f"❌ {msg}")
        raise UpdateError(msg)

    # Only check editable mode for latest update; version/branch install always proceeds
    if _is_editable() and not version and not branch:
        reporter.log("Running in development mode (editable install). Skipping auto-update.")
        reporter.log("To update manually: git pull && pip install -e .")
        reporter.done()
        return UpdateResult(changed=False)

    reporter.set_phases(_update_phase_plan())
    reporter.phase("download")

    if branch:
        reporter.log(f"Installing from branch '{branch}'...")
        commit = _resolve_git_ref_commit(branch)
        if commit:
            reporter.log(f"Install commit : {commit}")
        else:
            reporter.log("Install commit : unable to resolve before install")
        reporter.progress(1, 1, msg="resolved")
        suffix = f" (commit {commit})" if commit else ""
        success_message = f"Done. asc installed from branch '{branch}'{suffix}."
        fail_hint = f"pip install git+https://github.com/yinghuiwang/AppStoreTools.git@{branch}"
        if defer_install:
            return _defer_install_outcome(
                reporter,
                install_ref=branch,
                commit=commit,
                success_message=success_message,
            )
        _install_with_reporter(
            reporter,
            install_ref=branch,
            commit=commit,
            success_message=success_message,
            fail_hint=fail_hint,
        )
        return UpdateResult(
            changed=True,
            install_ref=branch,
            commit=commit,
            message=success_message,
        )

    if version:
        target_version = version.lstrip("v")
        reporter.log(f"Installing version {target_version}...")

        all_versions = _all_versions_from_github()
        if all_versions and f"v{target_version}" not in [f"v{v}" for v in all_versions]:
            similar = _similar_versions(target_version, all_versions)
            similar_str = ", ".join(f"v{v}" for v in similar) if similar else "N/A"
            reporter.fail(f"❌ Version v{target_version} not found.")
            if similar:
                reporter.log(f"Similar versions: {similar_str}", level="error")
            raise UpdateError(f"version not found: {target_version}")

        install_version = f"v{target_version}"
        commit = _resolve_git_ref_commit(install_version)
        if commit:
            reporter.log(f"Install commit : {commit}")
        else:
            reporter.log("Install commit : unable to resolve before install")
        reporter.progress(1, 1, msg="resolved")
        suffix = f" (commit {commit})" if commit else ""
        success_message = f"Done. asc updated to v{target_version}{suffix}."
        fail_hint = (
            f"pip install git+https://github.com/yinghuiwang/AppStoreTools.git@"
            f"{install_version}"
        )
        if defer_install:
            return _defer_install_outcome(
                reporter,
                install_ref=install_version,
                commit=commit,
                success_message=success_message,
            )
        _install_with_reporter(
            reporter,
            install_ref=install_version,
            commit=commit,
            success_message=success_message,
            fail_hint=fail_hint,
        )
        return UpdateResult(
            changed=True,
            install_ref=install_version,
            commit=commit,
            message=success_message,
        )

    current = _current_version()
    reporter.log("Checking for updates...")
    reporter.log(f"Current version : {current}")

    latest = _latest_version_from_github()
    if not latest:
        reporter.fail("Unable to reach GitHub. Check your internet connection.")
        raise UpdateError("github unreachable")

    reporter.log(f"Latest version  : {latest}  (github.com/yinghuiwang/AppStoreTools)")

    if _parse_version(latest) <= _parse_version(current):
        reporter.log(f"\nasc is already up to date ({current}).")
        reporter.done()
        return UpdateResult(changed=False)

    reporter.log(f"\nUpdate available: {current} → {latest}")
    if confirm and not yes:
        if not typer.confirm("Install now?", default=True):
            reporter.log("Update cancelled.")
            reporter.done()
            return UpdateResult(changed=False)

    reporter.log(f"Updating asc to {latest}...")
    install_version = f"v{latest}"
    commit = _resolve_git_ref_commit(install_version)
    if commit:
        reporter.log(f"Install commit : {commit}")
    else:
        reporter.log("Install commit : unable to resolve before install")
    reporter.progress(1, 1, msg="resolved")
    suffix = f" (commit {commit})" if commit else ""
    success_message = f"Done. asc updated to {latest}{suffix}."
    fail_hint = f"pip install git+https://github.com/yinghuiwang/AppStoreTools.git@v{latest}"
    if defer_install:
        return _defer_install_outcome(
            reporter,
            install_ref=install_version,
            commit=commit,
            success_message=success_message,
        )
    _install_with_reporter(
        reporter,
        install_ref=install_version,
        commit=commit,
        success_message=success_message,
        fail_hint=fail_hint,
    )
    reporter.log("Restart your shell or re-run asc for the new version.")
    return UpdateResult(
        changed=True,
        install_ref=install_version,
        commit=commit,
        message=success_message,
    )


def cmd_update(
    version: Optional[str] = typer.Option(None, "--version", help="Install a specific version."),
    branch: Optional[str] = typer.Option(None, "--branch", help="Install from a specific branch."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt (for CI/scripts)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress logs"),
):
    """Check for updates and install the latest version from GitHub."""
    reporter = make_cli_reporter(verbose=verbose)
    try:
        _update_core(
            version=version,
            branch=branch,
            yes=yes,
            reporter=reporter,
            confirm=True,
            verbose=verbose,
        )
    except UpdateError:
        raise typer.Exit(1)
