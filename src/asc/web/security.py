"""Shared Web UI path, outbound-URL, and display-redaction helpers."""
from __future__ import annotations

import copy
import ipaddress
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi.responses import JSONResponse

from asc.web.agent_workspace import is_blocked_workspace_path

_METADATA_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "169.254.169.254",
    }
)


class WebPathError(ValueError):
    """Path is outside the local data roots or is a secret file."""


def allowed_data_roots() -> tuple[Path, ...]:
    return (Path.home().resolve(), Path(tempfile.gettempdir()).resolve())


def is_under_allowed_root(target: Path) -> bool:
    resolved = target.expanduser().resolve()
    for root in allowed_data_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def resolve_web_data_path(path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    if not is_under_allowed_root(target) or is_blocked_workspace_path(target):
        raise WebPathError("Forbidden")
    return target


def forbidden_response() -> JSONResponse:
    return JSONResponse({"ok": False, "error": "Forbidden"}, status_code=403)


def mask_identifier(value: str, *, keep: int = 4) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= keep:
        return "•" * len(text)
    return "•" * (len(text) - keep) + text[-keep:]


def mask_ip(address: str) -> str:
    text = str(address or "").strip()
    if not text or text == "unknown":
        return text
    if "." in text and ":" not in text:
        parts = text.split(".")
        if len(parts) == 4:
            return ".".join([*parts[:3], "*"])
    if ":" in text:
        parts = text.split(":")
        if parts:
            return ":".join(["*" if part else "" for part in parts[:-1]] + [parts[-1]])
    return mask_identifier(text)


def _ip_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (ip.is_unspecified or ip.is_multicast or ip.is_reserved or ip.is_link_local)


def is_safe_outbound_url(url: str, *, resolve: bool = False) -> bool:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host or host in _METADATA_HOSTS:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not _ip_allowed(ip):
        return False
    if not resolve:
        return True
    try:
        infos = socket.getaddrinfo(host, parsed.port or 80, type=socket.SOCK_STREAM)
    except OSError:
        return True
    for info in infos:
        resolved = ipaddress.ip_address(info[4][0])
        if not _ip_allowed(resolved):
            return False
    return True


def kept_or_submitted(submitted: str, existing: str) -> str:
    value = str(submitted or "").strip()
    if not value or value == mask_identifier(existing):
        return existing
    return value


def redact_credential_fields(data: dict) -> dict:
    out = dict(data)
    if "issuer_id" in out:
        out["issuer_id"] = mask_identifier(out.get("issuer_id") or "")
    if "key_id" in out:
        out["key_id"] = mask_identifier(out.get("key_id") or "")
    return out


def redact_guard_status(data: dict) -> dict:
    redacted = copy.deepcopy(data)
    bindings = redacted.get("bindings") or {}
    for category, masker in (
        ("machine", mask_identifier),
        ("ip", mask_ip),
        ("credential", mask_identifier),
    ):
        remapped: dict[str, dict] = {}
        for key, info in (bindings.get(category) or {}).items():
            entry = dict(info or {})
            if "issuer_id" in entry:
                entry["issuer_id"] = mask_identifier(entry.get("issuer_id") or "")
            remapped[masker(str(key))] = entry
        bindings[category] = remapped
    env = redacted.get("current_environment") or {}
    machine = env.get("machine") or {}
    if "fingerprint" in machine:
        machine["fingerprint"] = mask_identifier(machine.get("fingerprint") or "")
    ip = env.get("ip") or {}
    if ip.get("address"):
        ip["address"] = mask_ip(str(ip.get("address") or ""))
    return redacted
