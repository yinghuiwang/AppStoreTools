"""Auto-detect, cache, and interactively resolve build/deploy/release inputs."""
from __future__ import annotations

import hashlib
import plistlib
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Sequence, TypeVar

import typer


@dataclass
class BuildInputsCLI:
    project: Optional[str] = None
    scheme: Optional[str] = None
    signing: Optional[str] = None
    profile: Optional[str] = None
    certificate: Optional[str] = None
    destination: Optional[str] = None


@dataclass(frozen=True)
class ResolvedInputs:
    project_path: str
    project_kind: str
    scheme: str
    bundle_id: str
    signing: str
    certificate: Optional[str]
    profile: Optional[str]
    destination: str


@dataclass(frozen=True)
class ProfileInfo:
    path: str
    uuid: str
    name: str
    team_id: str
    bundle_id: str
    expiration: datetime
    cert_sha1s: List[str]

    @property
    def is_expired(self) -> bool:
        now = datetime.now(timezone.utc)
        exp = self.expiration
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp <= now


def _decode_profile_plist(path) -> dict:
    """Run `security cms -D -i <path>` and parse the resulting plist."""
    result = subprocess.run(
        ["security", "cms", "-D", "-i", str(path)],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"security cms failed for {path}")
    return plistlib.loads(result.stdout)


def _cert_sha1(cert_bytes: bytes) -> str:
    return hashlib.sha1(cert_bytes).hexdigest().upper()


def parse_mobileprovision(path) -> ProfileInfo:
    plist = _decode_profile_plist(path)
    entitlements = plist.get("Entitlements") or {}
    app_id = entitlements.get("application-identifier", "")
    bundle_id = app_id.split(".", 1)[1] if "." in app_id else ""
    team_id = (plist.get("TeamIdentifier") or [""])[0]
    cert_blobs = plist.get("DeveloperCertificates") or []
    expiration = plist.get("ExpirationDate")
    if expiration is None:
        raise RuntimeError(f"Provisioning profile missing ExpirationDate: {path}")
    return ProfileInfo(
        path=str(path),
        uuid=plist.get("UUID", ""),
        name=plist.get("Name", ""),
        team_id=team_id,
        bundle_id=bundle_id,
        expiration=expiration,
        cert_sha1s=[_cert_sha1(b) for b in cert_blobs],
    )


PROFILE_DIRS = [
    Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles",
    Path.home() / "Library/MobileDevice/Provisioning Profiles",
]


def scan_profiles(dirs=None) -> List[ProfileInfo]:
    """Walk known profile dirs in order; first occurrence of each UUID wins."""
    seen: dict = {}
    for d in (dirs if dirs is not None else PROFILE_DIRS):
        if not Path(d).is_dir():
            continue
        for path in sorted(Path(d).glob("*.mobileprovision")):
            try:
                info = parse_mobileprovision(path)
            except Exception:
                continue
            if info.uuid and info.uuid not in seen:
                seen[info.uuid] = info
    return list(seen.values())


def detect_profiles(bundle_id: str, cert_sha1: Optional[str]) -> List[ProfileInfo]:
    """Filter discovered profiles by bundle ID, expiration, and (optionally) cert match."""
    out: List[ProfileInfo] = []
    for p in scan_profiles():
        if p.bundle_id != bundle_id:
            continue
        if p.is_expired:
            continue
        if cert_sha1 is not None and cert_sha1.upper() not in {s.upper() for s in p.cert_sha1s}:
            continue
        out.append(p)
    return out


@dataclass(frozen=True)
class Certificate:
    sha1: str
    name: str


_IDENTITY_RE = re.compile(r'^\s*\d+\)\s+([A-F0-9]{40})\s+"([^"]+)"\s*$')
_DISTRIBUTION_RE = re.compile(r"(Apple|iPhone)\s+Distribution:")


def detect_certificates() -> List[Certificate]:
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    out: List[Certificate] = []
    for line in result.stdout.splitlines():
        m = _IDENTITY_RE.match(line)
        if not m:
            continue
        sha1, name = m.group(1), m.group(2)
        if _DISTRIBUTION_RE.search(name):
            out.append(Certificate(sha1=sha1, name=name))
    return out


_BUNDLE_ID_RE = re.compile(r"^\s*PRODUCT_BUNDLE_IDENTIFIER\s*=\s*(\S+)\s*$")


def detect_bundle_id(project: str, kind: str, scheme: str) -> Optional[str]:
    flag = "-workspace" if kind == "workspace" else "-project"
    result = subprocess.run(
        ["xcodebuild", "-showBuildSettings", flag, project, "-scheme", scheme],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        m = _BUNDLE_ID_RE.match(line)
        if m:
            return m.group(1)
    return None


def validate_cache_entry(field: str, value: str) -> bool:
    """Return False if cached value is no longer usable; True otherwise.

    Unknown fields pass through unchecked (caller decides).
    """
    if not value:
        return False
    if field == "project":
        return Path(value).exists()
    if field == "certificate":
        return any(c.name == value for c in detect_certificates())
    if field == "profile":
        if not Path(value).exists():
            return False
        try:
            info = parse_mobileprovision(value)
        except Exception:
            return False
        return not info.is_expired
    return True


T = TypeVar("T")


def _pick_one(
    items: Sequence[T],
    *,
    label: str,
    interactive: bool,
    render: Optional[Callable[[T], str]] = None,
) -> T:
    if not items:
        raise RuntimeError(f"找不到可用的{label}")
    if len(items) == 1:
        return items[0]
    if not interactive:
        raise RuntimeError(
            f"发现多个{label}，请用 CLI 参数指定，或加 --interactive"
        )
    typer.echo(f"\n请选择{label}：")
    for i, item in enumerate(items, 1):
        text = render(item) if render else str(item)
        typer.echo(f"  [{i}] {text}")
    while True:
        raw = typer.prompt("编号")
        try:
            idx = int(raw)
            if 1 <= idx <= len(items):
                return items[idx - 1]
        except ValueError:
            pass
        typer.echo(f"❌ 无效编号，请输入 1-{len(items)}")
