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


def test_get_machine_fingerprint_macos(tmp_path):
    from asc.guard import Guard
    with patch("asc.guard.GUARD_FILE", tmp_path / "guard.json"):
        with patch("asc.guard._get_machine_fingerprint_macos", return_value="FAKE-UUID-1234"):
            g = Guard()
            fp = g._get_machine_fingerprint()
            assert len(fp) == 64  # sha256 hex digest
            assert isinstance(fp, str)


def test_get_machine_fingerprint_fallback(tmp_path):
    from asc.guard import Guard
    with patch("asc.guard.GUARD_FILE", tmp_path / "guard.json"):
        with patch("asc.guard._get_machine_fingerprint_macos", side_effect=Exception("fail")):
            g = Guard()
            fp = g._get_machine_fingerprint()
            assert len(fp) == 64


def test_get_public_ip_success(tmp_path):
    from asc.guard import Guard
    with patch("asc.guard.GUARD_FILE", tmp_path / "guard.json"):
        with patch("asc.guard._fetch_public_ip", return_value="1.2.3.4"):
            g = Guard()
            ip = g._get_public_ip()
            assert ip == "1.2.3.4"


def test_get_public_ip_failure(tmp_path):
    from asc.guard import Guard
    with patch("asc.guard.GUARD_FILE", tmp_path / "guard.json"):
        with patch("asc.guard._fetch_public_ip", side_effect=Exception("timeout")):
            g = Guard()
            ip = g._get_public_ip()
            assert ip == "unknown"
