# src/asc/guard.py
from __future__ import annotations

import json
import os
import shutil
import copy
import typer
import hashlib
import platform
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

GUARD_FILE = Path.home() / ".config" / "asc" / "guard.json"

_EMPTY = {"enabled": True, "bindings": {"machine": {}, "ip": {}, "credential": {}}}


def _get_machine_fingerprint_macos() -> str:
    result = subprocess.run(
        ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
        capture_output=True, text=True, timeout=5,
    )
    for line in result.stdout.splitlines():
        if "IOPlatformUUID" in line:
            parts = line.split('"')
            if len(parts) >= 4:
                return parts[-2]
    raise RuntimeError("IOPlatformUUID not found")


def _fetch_public_ip() -> str:
    import urllib.request
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.read().decode().strip()
        except Exception:
            continue
    raise RuntimeError("All IP endpoints failed")


class GuardError(Exception):
    pass


class GuardViolationError(GuardError):
    pass


class GuardConfigError(GuardError):
    pass


class Guard:
    def __init__(self):
        self._file = GUARD_FILE
        self._data = self._load()

    def _load(self) -> dict:
        if os.getenv("ASC_GUARD_DISABLE", "").strip() == "1":
            return {"enabled": False, "bindings": {"machine": {}, "ip": {}, "credential": {}}}
        if not self._file.exists():
            return copy.deepcopy(_EMPTY)
        try:
            data = json.loads(self._file.read_text())
            data.setdefault("bindings", {})
            for k in ("machine", "ip", "credential"):
                data["bindings"].setdefault(k, {})
            return data
        except Exception:
            backup = self._file.with_suffix(".json.backup")
            try:
                shutil.copy(self._file, backup)
            except Exception:
                pass
            typer.echo(f"⚠️  守卫配置文件损坏，已重置。旧文件备份至 {backup}", err=True)
            return copy.deepcopy(_EMPTY)

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(self._data, indent=2, ensure_ascii=False))
        try:
            self._file.chmod(0o600)
        except Exception:
            pass

    def is_enabled(self) -> bool:
        return bool(self._data.get("enabled", True))

    def _get_machine_fingerprint(self) -> str:
        try:
            raw = _get_machine_fingerprint_macos()
        except Exception:
            raw = f"{platform.node()}-{uuid.getnode()}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _get_public_ip(self) -> str:
        try:
            return _fetch_public_ip()
        except Exception:
            typer.echo("⚠️  无法获取公网 IP，跳过 IP 绑定检查", err=True)
            return "unknown"

    def get_status(self) -> dict:
        return self._data
