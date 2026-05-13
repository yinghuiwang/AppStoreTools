# src/asc/guard.py
from __future__ import annotations

import json
import os
import sys
import shutil
import copy
import typer
import click
import hashlib
import platform
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from asc.i18n import t, ERRORS

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
    raise RuntimeError(t(ERRORS['machine_id_failed']))


def _fetch_public_ip() -> str:
    import urllib.request
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.read().decode().strip()
        except Exception:
            continue
    raise RuntimeError(t(ERRORS['ip_fetch_failed']))


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

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def bind(self, app_id: str, app_name: str, key_id: str, issuer_id: str) -> None:
        fp = self._get_machine_fingerprint()
        ip = self._get_public_ip()
        now = self._now()
        b = self._data["bindings"]
        b["machine"][fp] = {"app_id": app_id, "app_name": app_name, "bound_at": now, "last_checked": now}
        if ip != "unknown":
            b["ip"][ip] = {"app_id": app_id, "app_name": app_name, "bound_at": now, "last_checked": now}
        b["credential"][key_id] = {"app_id": app_id, "app_name": app_name, "issuer_id": issuer_id, "bound_at": now, "last_checked": now}
        self._save()

    def unbind(self, target: str, value: str) -> None:
        self._data["bindings"].get(target, {}).pop(value, None)
        self._save()

    def enable(self) -> None:
        self._data["enabled"] = True
        self._save()

    def disable(self) -> None:
        self._data["enabled"] = False
        self._save()

    def _collect_conflicts(self, app_id: str, key_id: str, fp: str, ip: str) -> list[dict]:
        """返回所有绑定到不同 App 的冲突条目列表。"""
        b = self._data["bindings"]
        conflicts = []
        checks = [
            ("machine", fp, f"机器指纹 ({fp[:8]}...)"),
            ("ip", ip, f"IP 地址 ({ip})"),
            ("credential", key_id, f"API 凭证 ({key_id})"),
        ]
        for btype, bkey, label in checks:
            if bkey == "unknown":
                continue
            entry = b.get(btype, {}).get(bkey)
            if entry and entry.get("app_id") != app_id:
                conflicts.append({
                    "type": btype,
                    "key": bkey,
                    "label": label,
                    "entry": entry,
                })
        return conflicts

    def _update_last_checked(self, app_id: str, key_id: str, fp: str, ip: str) -> None:
        now = self._now()
        b = self._data["bindings"]
        for btype, bkey in [("machine", fp), ("ip", ip), ("credential", key_id)]:
            if bkey != "unknown" and bkey in b.get(btype, {}):
                b[btype][bkey]["last_checked"] = now
        self._save()

    def check_and_enforce(self, app_id: str, app_name: str, key_id: str, issuer_id: str) -> None:
        if not app_id or not key_id:
            typer.echo("⚠️  缺少 App ID 或凭证信息，跳过守卫检查", err=True)
            return

        # 只调用一次，避免重复网络请求
        fp = self._get_machine_fingerprint()
        ip = self._get_public_ip()

        conflicts = self._collect_conflicts(app_id, key_id, fp, ip)

        if not conflicts:
            b = self._data["bindings"]
            first_bind = fp not in b.get("machine", {})
            if first_bind:
                self.bind(app_id, app_name, key_id, issuer_id)
                typer.echo(f"ℹ️  已绑定当前环境到 App: {app_name}", err=True)
            else:
                self._update_last_checked(app_id, key_id, fp, ip)
            return

        typer.echo("\n⚠️  检测到 App 绑定冲突：\n", err=True)
        for c in conflicts:
            entry = c["entry"]
            bound_at = entry.get("bound_at", "未知")[:19].replace("T", " ")
            typer.echo(f"  • {c['label']} 已绑定到: {entry['app_id']} ({entry.get('app_name', '')})", err=True)
            typer.echo(f"    绑定时间: {bound_at}\n", err=True)
        typer.echo(f"当前尝试操作的 App: {app_id} ({app_name})\n", err=True)
        typer.echo("此限制旨在防止意外使用同一环境发布多个 App。", err=True)
        typer.echo("如需继续，请输入 'yes' 确认，或使用 'asc guard unbind' 解除绑定。\n", err=True)

        if not sys.stdin.isatty():
            typer.echo("\n❌ 检测到绑定冲突且当前为非交互式环境，操作终止", err=True)
            raise GuardViolationError("非交互式环境中检测到绑定冲突")

        try:
            answer = typer.prompt("是否继续? [yes/no]")
        except KeyboardInterrupt:
            typer.echo("\n❌ 操作已取消", err=True)
            raise GuardViolationError("用户取消操作")

        if answer.strip().lower() != "yes":
            raise GuardViolationError("用户拒绝继续操作")

        self.bind(app_id, app_name, key_id, issuer_id)
