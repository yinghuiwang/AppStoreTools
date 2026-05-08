"""Auto-detect, cache, and interactively resolve build/deploy/release inputs."""
from __future__ import annotations

import hashlib
import plistlib
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


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
