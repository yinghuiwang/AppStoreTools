"""Auto-detect, cache, and interactively resolve build/deploy/release inputs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


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
