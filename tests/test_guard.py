# tests/test_guard.py
from __future__ import annotations
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_guard_error_hierarchy():
    from asc.guard import GuardError, GuardViolationError, GuardConfigError
    assert issubclass(GuardViolationError, GuardError)
    assert issubclass(GuardConfigError, GuardError)


def test_guard_loads_empty_config(tmp_path):
    from asc.guard import Guard
    with patch("asc.guard.GUARD_FILE", tmp_path / "guard.json"):
        g = Guard()
        assert g.is_enabled() is True
        assert g._data == {"enabled": True, "bindings": {"machine": {}, "ip": {}, "credential": {}}}


def test_guard_loads_existing_config(tmp_path):
    from asc.guard import Guard
    guard_file = tmp_path / "guard.json"
    guard_file.write_text(json.dumps({"enabled": False, "bindings": {"machine": {}, "ip": {}, "credential": {}}}))
    with patch("asc.guard.GUARD_FILE", guard_file):
        g = Guard()
        assert g.is_enabled() is False


def test_guard_handles_corrupted_config(tmp_path):
    from asc.guard import Guard
    guard_file = tmp_path / "guard.json"
    guard_file.write_text("not valid json{{{{")
    with patch("asc.guard.GUARD_FILE", guard_file):
        g = Guard()
        assert g.is_enabled() is True
        assert (tmp_path / "guard.json.backup").exists()


def test_guard_disable_via_env(tmp_path, monkeypatch):
    from asc.guard import Guard
    monkeypatch.setenv("ASC_GUARD_DISABLE", "1")
    with patch("asc.guard.GUARD_FILE", tmp_path / "guard.json"):
        g = Guard()
        assert g.is_enabled() is False
