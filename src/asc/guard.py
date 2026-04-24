# src/asc/guard.py
from __future__ import annotations

import json
import os
import shutil
import copy
import typer
from datetime import datetime, timezone
from pathlib import Path

GUARD_FILE = Path.home() / ".config" / "asc" / "guard.json"

_EMPTY = {"enabled": True, "bindings": {"machine": {}, "ip": {}, "credential": {}}}


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

    def get_status(self) -> dict:
        return self._data
