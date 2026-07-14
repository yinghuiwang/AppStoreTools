# src/asc/guard.py
from __future__ import annotations

import json
import os
import sys
import shutil
import copy
import typer
import click
import platform
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from asc.i18n import t, ERRORS

GUARD_FILE = Path.home() / ".config" / "asc" / "guard.json"

_EMPTY = {
    "enabled": True,
    "bindings": {"machine": {}, "ip": {}, "credential": {}},
    "app_notes": {},
    "bundle_bindings": {},
}


def _get_machine_fingerprint_macos() -> str:
    result = subprocess.run(
        ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
        capture_output=True, text=True, timeout=5,
    )
    for line in result.stdout.splitlines():
        if "IOPlatformSerialNumber" in line:
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
            data = copy.deepcopy(_EMPTY)
            data["enabled"] = False
            return data
        if not self._file.exists():
            return copy.deepcopy(_EMPTY)
        try:
            data = json.loads(self._file.read_text())
            data.setdefault("bindings", {})
            for k in ("machine", "ip", "credential"):
                data["bindings"].setdefault(k, {})
            for bindings in data["bindings"].values():
                for entry in bindings.values():
                    if "app_id" in entry:
                        entry["app_id"] = str(entry["app_id"])
            data.setdefault("app_notes", {})
            data.setdefault("bundle_bindings", {})
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
            return _get_machine_fingerprint_macos()
        except Exception:
            return f"{platform.node()}-{uuid.getnode()}"

    def _get_public_ip(self) -> str:
        try:
            return _fetch_public_ip()
        except Exception:
            typer.echo("⚠️  无法获取公网 IP，跳过 IP 绑定检查", err=True)
            return "unknown"

    def get_status(self) -> dict:
        return self._data

    def profile_machine_status(
        self, app_id: str, issuer_id: str, *, fingerprint: str | None = None
    ) -> dict[str, bool]:
        """Return whether an App Profile is bound to this or another machine."""
        fp = fingerprint or self._get_machine_fingerprint()
        current = self._data.get("bindings", {}).get("machine", {}).get(fp)
        current_match = bool(
            current
            and str(current.get("app_id")) == str(app_id)
            and self._same_account(current, app_id, issuer_id)
        )
        elsewhere = any(
            machine_fp != fp
            and str(entry.get("app_id")) == str(app_id)
            and self._same_account(entry, app_id, issuer_id)
            for machine_fp, entry in self._data.get("bindings", {}).get("machine", {}).items()
        )
        return {"current": current_match, "elsewhere": elsewhere}

    def check_bundle_binding(self, profile_name: str, bundle_id: str) -> None:
        """Enforce the one-Bundle-ID-to-one-profile mapping and bind new IDs."""
        bundle_id = str(bundle_id or "").strip()
        profile_name = str(profile_name or "").strip()
        if not bundle_id or not profile_name:
            return
        bindings = self._data.setdefault("bundle_bindings", {})
        existing = bindings.get(bundle_id)
        if existing and existing.get("profile_name") != profile_name:
            raise GuardViolationError(
                f"Bundle ID {bundle_id} 已绑定到 App Profile "
                f"{existing.get('profile_name', '')}，不能由 {profile_name} 上传"
            )
        now = self._now()
        if existing:
            existing["last_checked"] = now
        else:
            bindings[bundle_id] = {
                "profile_name": profile_name,
                "bound_at": now,
                "last_checked": now,
            }
        self._save()

    def profile_bundle_ids(self, profile_name: str) -> list[str]:
        return sorted(
            bundle_id
            for bundle_id, entry in self._data.get("bundle_bindings", {}).items()
            if entry.get("profile_name") == profile_name
        )

    def rename_profile(self, old_name: str, new_name: str) -> None:
        changed = False
        for entry in self._data.get("bundle_bindings", {}).values():
            if entry.get("profile_name") == old_name:
                entry["profile_name"] = new_name
                changed = True
        for category in ("machine", "ip", "credential"):
            for entry in self._data.get("bindings", {}).get(category, {}).values():
                if entry.get("app_name") == old_name:
                    entry["app_name"] = new_name
                    changed = True
        if changed:
            self._save()

    def remove_profile(self, profile_name: str) -> None:
        bindings = self._data.get("bundle_bindings", {})
        removed = [
            bundle_id for bundle_id, entry in bindings.items()
            if entry.get("profile_name") == profile_name
        ]
        for bundle_id in removed:
            bindings.pop(bundle_id, None)
        if removed:
            self._save()

    def profile_access(self, profiles: dict[str, dict]) -> dict:
        """Resolve Web profile availability for the current machine."""
        if not self.is_enabled():
            return {
                "matched_profile": "",
                "options": {
                    name: {"enabled": True, "current": False, "elsewhere": False}
                    for name in profiles
                },
            }
        fp = self._get_machine_fingerprint()
        options = {}
        matched_profile = ""
        for name, data in profiles.items():
            status = self.profile_machine_status(
                str(data.get("app_id", "")),
                str(data.get("issuer_id", "")),
                fingerprint=fp,
            )
            if status["current"] and not matched_profile:
                matched_profile = name
            options[name] = status
        for status in options.values():
            status["enabled"] = bool(status["current"] or (
                not matched_profile and not status["elsewhere"]
            ))
        return {"matched_profile": matched_profile, "options": options}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _entry(self, existing: dict | None, app_id: str, app_name: str, issuer_id: str, now: str) -> dict:
        existing = existing or {}
        app_id = str(app_id)
        return {
            "app_id": app_id,
            "app_name": app_name,
            "issuer_id": issuer_id,
            "bound_at": existing.get("bound_at", now),
            "last_checked": now,
        }

    def _upsert_bindings(
        self,
        app_id: str,
        app_name: str,
        key_id: str,
        issuer_id: str,
        fp: str,
        ip: str,
        note: str = "",
    ) -> None:
        now = self._now()
        b = self._data["bindings"]
        b["machine"][fp] = self._entry(b["machine"].get(fp), app_id, app_name, issuer_id, now)
        if ip != "unknown":
            b["ip"][ip] = self._entry(b["ip"].get(ip), app_id, app_name, issuer_id, now)
        credential = self._entry(b["credential"].get(key_id), app_id, app_name, issuer_id, now)
        credential["issuer_id"] = issuer_id
        b["credential"][key_id] = credential
        self._data.setdefault("app_notes", {})
        if note:
            self._data["app_notes"][app_id] = note
        self._save()

    def bind(self, app_id: str, app_name: str, key_id: str, issuer_id: str, note: str = "") -> None:
        fp = self._get_machine_fingerprint()
        ip = self._get_public_ip()
        self._upsert_bindings(app_id, app_name, key_id, issuer_id, fp, ip, note)

    def unbind(self, target: str, value: str) -> None:
        self._data["bindings"].get(target, {}).pop(value, None)
        self._save()

    def set_app_note(self, app_id: str, note: str) -> bool:
        app_id = str(app_id)
        app_exists = any(
            str(entry.get("app_id")) == app_id
            for bindings in self._data.get("bindings", {}).values()
            for entry in bindings.values()
        )
        if not app_exists:
            return False
        self._data.setdefault("app_notes", {})[app_id] = note
        self._save()
        return True

    def enable(self) -> None:
        self._data["enabled"] = True
        self._save()

    def disable(self) -> None:
        self._data["enabled"] = False
        self._save()

    def _same_account(self, entry: dict, app_id: str, issuer_id: str) -> bool:
        entry_issuer_id = entry.get("issuer_id")
        if entry_issuer_id:
            return entry_issuer_id == issuer_id
        return entry.get("app_id") == app_id

    def _collect_conflicts(self, app_id: str, key_id: str, issuer_id: str, fp: str, ip: str) -> list[dict]:
        """返回所有绑定到不同 Issuer ID 的冲突条目列表。"""
        b = self._data["bindings"]
        conflicts = []
        checks = [
            ("machine", fp, f"机器指纹 ({fp})"),
            ("ip", ip, f"IP 地址 ({ip})"),
            ("credential", key_id, f"API 凭证 ({key_id})"),
        ]
        for btype, bkey, label in checks:
            if bkey == "unknown":
                continue
            entry = b.get(btype, {}).get(bkey)
            if entry and not self._same_account(entry, app_id, issuer_id):
                conflicts.append({
                    "type": btype,
                    "key": bkey,
                    "label": label,
                    "entry": entry,
                })

        current_machine = b.get("machine", {}).get(fp)
        current_machine_matches = current_machine and self._same_account(
            current_machine, app_id, issuer_id
        ) and str(current_machine.get("app_id")) == str(app_id)
        credential = b.get("credential", {}).get(key_id)
        credential_matches = credential and self._same_account(
            credential, app_id, issuer_id
        ) and str(credential.get("app_id")) == str(app_id)
        if credential_matches and not current_machine_matches:
            for machine_fp, entry in b.get("machine", {}).items():
                if machine_fp == fp:
                    continue
                if (
                    str(entry.get("app_id")) == str(app_id)
                    and self._same_account(entry, app_id, issuer_id)
                ):
                    conflicts.append({
                        "type": "profile_machine",
                        "key": machine_fp,
                        "label": f"App Profile 已绑定机器 ({machine_fp})",
                        "entry": entry,
                    })
                    break
        return conflicts

    def _update_last_checked(self, app_id: str, key_id: str, fp: str, ip: str) -> None:
        now = self._now()
        b = self._data["bindings"]
        for btype, bkey in [("machine", fp), ("ip", ip), ("credential", key_id)]:
            if bkey != "unknown" and bkey in b.get(btype, {}):
                b[btype][bkey]["last_checked"] = now
        self._save()

    def _remove_other_profile_machines(
        self, app_id: str, issuer_id: str, current_fp: str
    ) -> None:
        machines = self._data["bindings"].get("machine", {})
        stale = [
            machine_fp
            for machine_fp, entry in machines.items()
            if machine_fp != current_fp
            and str(entry.get("app_id")) == str(app_id)
            and self._same_account(entry, app_id, issuer_id)
        ]
        for machine_fp in stale:
            machines.pop(machine_fp, None)

    def check_and_enforce(self, app_id: str, app_name: str, key_id: str, issuer_id: str) -> None:
        if not app_id or not key_id:
            typer.echo("⚠️  缺少 App ID 或凭证信息，跳过守卫检查", err=True)
            return

        # 只调用一次，避免重复网络请求
        fp = self._get_machine_fingerprint()
        ip = self._get_public_ip()

        conflicts = self._collect_conflicts(app_id, key_id, issuer_id, fp, ip)

        if not conflicts:
            b = self._data["bindings"]
            has_new_binding = (
                fp not in b.get("machine", {})
                or (ip != "unknown" and ip not in b.get("ip", {}))
                or key_id not in b.get("credential", {})
            )
            current_machine = b.get("machine", {}).get(fp)
            if current_machine and str(current_machine.get("app_id")) == str(app_id):
                self._remove_other_profile_machines(app_id, issuer_id, fp)
            self._upsert_bindings(app_id, app_name, key_id, issuer_id, fp, ip)
            if has_new_binding:
                typer.echo(f"ℹ️  已绑定当前环境到 App: {app_name}", err=True)
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

        self._remove_other_profile_machines(app_id, issuer_id, fp)
        self._upsert_bindings(app_id, app_name, key_id, issuer_id, fp, ip)


def enforce_config_guard(config) -> None:
    """Apply Guard consistently for any operation using an app Config."""
    guard = Guard()
    if not guard.is_enabled():
        return

    def string_value(value) -> str:
        return value if isinstance(value, str) else ""

    guard.check_and_enforce(
        app_id=string_value(config.app_id),
        app_name=string_value(config.app_name),
        key_id=string_value(config.key_id),
        issuer_id=string_value(config.issuer_id),
    )


def enforce_bundle_guard(config, bundle_id: str) -> None:
    """Check/bind a Bundle ID after the profile machine guard succeeds."""
    guard = Guard()
    if not guard.is_enabled():
        return
    profile_name = config.app_name if isinstance(config.app_name, str) else ""
    guard.check_bundle_binding(profile_name, bundle_id)


def read_ipa_bundle_id(ipa_path: str) -> str:
    """Read CFBundleIdentifier from the first application in an IPA."""
    import plistlib
    import zipfile

    with zipfile.ZipFile(ipa_path) as archive:
        candidates = [
            name for name in archive.namelist()
            if name.startswith("Payload/") and name.endswith(".app/Info.plist")
        ]
        if not candidates:
            raise GuardConfigError(f"IPA 中未找到应用 Info.plist: {ipa_path}")
        with archive.open(candidates[0]) as stream:
            data = plistlib.load(stream)
    bundle_id = data.get("CFBundleIdentifier")
    if not isinstance(bundle_id, str) or not bundle_id.strip():
        raise GuardConfigError(f"IPA 中缺少 CFBundleIdentifier: {ipa_path}")
    return bundle_id.strip()
