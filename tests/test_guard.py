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


def test_bind_creates_entries(tmp_path):
    from asc.guard import Guard
    guard_file = tmp_path / "guard.json"
    with patch("asc.guard.GUARD_FILE", guard_file), \
         patch.object(Guard, "_get_machine_fingerprint", return_value="fp123"), \
         patch.object(Guard, "_get_public_ip", return_value="1.2.3.4"):
        g = Guard()
        g.bind(app_id="com.ex.app", app_name="myapp", key_id="KEY1", issuer_id="ISS1")
        data = json.loads(guard_file.read_text())
        assert "fp123" in data["bindings"]["machine"]
        assert "1.2.3.4" in data["bindings"]["ip"]
        assert "KEY1" in data["bindings"]["credential"]
        assert data["bindings"]["machine"]["fp123"]["app_id"] == "com.ex.app"


def test_unbind_removes_entry(tmp_path):
    from asc.guard import Guard
    guard_file = tmp_path / "guard.json"
    with patch("asc.guard.GUARD_FILE", guard_file), \
         patch.object(Guard, "_get_machine_fingerprint", return_value="fp123"), \
         patch.object(Guard, "_get_public_ip", return_value="1.2.3.4"):
        g = Guard()
        g.bind(app_id="com.ex.app", app_name="myapp", key_id="KEY1", issuer_id="ISS1")
        g.unbind("machine", "fp123")
        data = json.loads(guard_file.read_text())
        assert "fp123" not in data["bindings"]["machine"]


def test_enable_disable(tmp_path):
    from asc.guard import Guard
    guard_file = tmp_path / "guard.json"
    with patch("asc.guard.GUARD_FILE", guard_file):
        g = Guard()
        g.disable()
        assert g.is_enabled() is False
        g.enable()
        assert g.is_enabled() is True


def test_no_conflict_first_bind(tmp_path):
    """首次使用，无冲突，自动绑定并静默通过"""
    from asc.guard import Guard
    guard_file = tmp_path / "guard.json"
    with patch("asc.guard.GUARD_FILE", guard_file), \
         patch.object(Guard, "_get_machine_fingerprint", return_value="fp1"), \
         patch.object(Guard, "_get_public_ip", return_value="1.1.1.1"):
        g = Guard()
        g.check_and_enforce(app_id="com.ex.app", app_name="myapp", key_id="K1", issuer_id="I1")
        data = json.loads(guard_file.read_text())
        assert data["bindings"]["machine"]["fp1"]["app_id"] == "com.ex.app"


def test_no_conflict_same_app(tmp_path):
    """已绑定，操作同一 App，不产生冲突"""
    from asc.guard import Guard
    guard_file = tmp_path / "guard.json"
    with patch("asc.guard.GUARD_FILE", guard_file), \
         patch.object(Guard, "_get_machine_fingerprint", return_value="fp1"), \
         patch.object(Guard, "_get_public_ip", return_value="1.1.1.1"):
        g = Guard()
        g.bind("com.ex.app", "myapp", "K1", "I1")
        g.check_and_enforce(app_id="com.ex.app", app_name="myapp", key_id="K1", issuer_id="I1")


def test_conflict_user_confirms(tmp_path):
    """冲突时用户输入 yes，更新绑定后继续"""
    from asc.guard import Guard
    guard_file = tmp_path / "guard.json"
    with patch("asc.guard.GUARD_FILE", guard_file), \
         patch.object(Guard, "_get_machine_fingerprint", return_value="fp1"), \
         patch.object(Guard, "_get_public_ip", return_value="1.1.1.1"), \
         patch("sys.stdin.isatty", return_value=True), \
         patch("typer.prompt", return_value="yes"):
        g = Guard()
        g.bind("com.ex.other", "otherapp", "K1", "I1")
        g.check_and_enforce(app_id="com.ex.app", app_name="myapp", key_id="K1", issuer_id="I1")
        data = json.loads(guard_file.read_text())
        assert data["bindings"]["credential"]["K1"]["app_id"] == "com.ex.app"


def test_conflict_user_denies(tmp_path):
    """冲突时用户输入 no，抛出 GuardViolationError"""
    from asc.guard import Guard, GuardViolationError
    guard_file = tmp_path / "guard.json"
    with patch("asc.guard.GUARD_FILE", guard_file), \
         patch.object(Guard, "_get_machine_fingerprint", return_value="fp1"), \
         patch.object(Guard, "_get_public_ip", return_value="1.1.1.1"), \
         patch("sys.stdin.isatty", return_value=True), \
         patch("typer.prompt", return_value="no"):
        g = Guard()
        g.bind("com.ex.other", "otherapp", "K1", "I1")
        with pytest.raises(GuardViolationError):
            g.check_and_enforce(app_id="com.ex.app", app_name="myapp", key_id="K1", issuer_id="I1")


def test_conflict_non_interactive(tmp_path):
    """非交互式环境冲突时直接抛出 GuardViolationError"""
    from asc.guard import Guard, GuardViolationError
    guard_file = tmp_path / "guard.json"
    with patch("asc.guard.GUARD_FILE", guard_file), \
         patch.object(Guard, "_get_machine_fingerprint", return_value="fp1"), \
         patch.object(Guard, "_get_public_ip", return_value="1.1.1.1"), \
         patch("sys.stdin.isatty", return_value=False):
        g = Guard()
        g.bind("com.ex.other", "otherapp", "K1", "I1")
        with pytest.raises(GuardViolationError):
            g.check_and_enforce(app_id="com.ex.app", app_name="myapp", key_id="K1", issuer_id="I1")


def test_conflict_keyboard_interrupt(tmp_path):
    """Ctrl+C 时视为拒绝，抛出 GuardViolationError"""
    from asc.guard import Guard, GuardViolationError
    guard_file = tmp_path / "guard.json"
    with patch("asc.guard.GUARD_FILE", guard_file), \
         patch.object(Guard, "_get_machine_fingerprint", return_value="fp1"), \
         patch.object(Guard, "_get_public_ip", return_value="1.1.1.1"), \
         patch("sys.stdin.isatty", return_value=True), \
         patch("typer.prompt", side_effect=KeyboardInterrupt):
        g = Guard()
        g.bind("com.ex.other", "otherapp", "K1", "I1")
        with pytest.raises(GuardViolationError):
            g.check_and_enforce(app_id="com.ex.app", app_name="myapp", key_id="K1", issuer_id="I1")
