# tests/test_guard_cmd.py
from __future__ import annotations
import json
import pytest
from pathlib import Path
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock


def test_guard_status_enabled(tmp_path):
    from asc.cli import app
    runner = CliRunner()
    machine_fp = "SERIAL-C02ABC123456789"
    with patch("asc.commands.guard_cmd.Guard") as MockGuard:
        instance = MockGuard.return_value
        instance.is_enabled.return_value = True
        instance.get_status.return_value = {
            "enabled": True,
            "app_notes": {"123456789": "办公室 Mac"},
            "bindings": {
                "machine": {
                    machine_fp: {
                        "app_id": "123456789",
                        "app_name": "myapp",
                        "issuer_id": "iss-1",
                        "bound_at": "2026-05-18T10:00:00",
                        "last_checked": "2026-05-19T11:00:00",
                    }
                },
                "ip": {},
                "credential": {},
            }
        }
        instance.current_environment.return_value = {
            "machine": {
                "fingerprint": machine_fp,
                "bound": True,
                "app_id": "123456789",
                "app_name": "myapp",
                "note": "办公室 Mac",
            },
            "ip": {
                "address": "1.2.3.4",
                "available": True,
                "bound": False,
                "app_id": "",
                "app_name": "",
                "note": "",
            },
        }
        result = runner.invoke(app, ["guard", "status"])
    assert result.exit_code == 0
    assert "已启用" in result.output or "启用" in result.output
    assert machine_fp in result.output
    assert "办公室 Mac" in result.output
    assert "SERIAL-C02ABC1234..." not in result.output
    assert "✅ 已绑定" in result.output
    assert "myapp (123456789)" in result.output
    assert "❌ 未绑定" in result.output
    assert "绑定方式" not in result.output
    assert "Issuer ID" not in result.output
    assert "绑定时间" not in result.output.split("绑定记录:")[0]
    assert "最近检查" not in result.output


def test_guard_status_marks_current_ip_bound():
    from asc.cli import app
    runner = CliRunner()
    machine_fp = "SERIAL-CURRENT"
    ip = "203.0.113.10"
    with patch("asc.commands.guard_cmd.Guard") as MockGuard:
        instance = MockGuard.return_value
        instance.is_enabled.return_value = True
        instance.get_status.return_value = {
            "enabled": True,
            "app_notes": {},
            "bindings": {
                "machine": {},
                "ip": {
                    ip: {
                        "app_id": "6503186734",
                        "app_name": "test",
                        "issuer_id": "iss-test",
                        "bound_at": "2026-07-17T08:55:10",
                    }
                },
                "credential": {},
            },
        }
        instance.current_environment.return_value = {
            "machine": {
                "fingerprint": machine_fp,
                "bound": False,
                "app_id": "",
                "app_name": "",
                "note": "",
            },
            "ip": {
                "address": ip,
                "available": True,
                "bound": True,
                "app_id": "6503186734",
                "app_name": "test",
                "note": "",
            },
        }
        result = runner.invoke(app, ["guard", "status"])
    assert result.exit_code == 0
    assert "机器指纹" in result.output
    assert "❌ 未绑定" in result.output
    assert "test (6503186734)" in result.output
    assert "Issuer ID" not in result.output
    assert "绑定方式" not in result.output


def test_guard_disable(tmp_path):
    from asc.cli import app
    runner = CliRunner()
    with patch("asc.commands.guard_cmd.Guard") as MockGuard:
        instance = MockGuard.return_value
        result = runner.invoke(app, ["guard", "disable"])
    assert result.exit_code == 0
    instance.disable.assert_called_once()


def test_guard_enable(tmp_path):
    from asc.cli import app
    runner = CliRunner()
    with patch("asc.commands.guard_cmd.Guard") as MockGuard:
        instance = MockGuard.return_value
        result = runner.invoke(app, ["guard", "enable"])
    assert result.exit_code == 0
    instance.enable.assert_called_once()


def test_guard_reset(tmp_path):
    from asc.cli import app
    runner = CliRunner()
    with patch("asc.commands.guard_cmd.Guard") as MockGuard:
        instance = MockGuard.return_value
        instance.get_status.return_value = {
            "enabled": True,
            "bindings": {"machine": {"fp": {}}, "ip": {"1.1.1.1": {}}, "credential": {"K1": {}}}
        }
        result = runner.invoke(app, ["guard", "reset"], input="yes\n")
    assert result.exit_code == 0


def test_guard_unbind_current(tmp_path):
    from asc.cli import app
    runner = CliRunner()
    machine_fp = "SERIAL-C02ABC123456789"
    with patch("asc.commands.guard_cmd.Guard") as MockGuard:
        instance = MockGuard.return_value
        instance._get_machine_fingerprint.return_value = machine_fp
        instance._get_public_ip.return_value = "1.2.3.4"
        instance._data = {"bindings": {"machine": {machine_fp: {}}, "ip": {"1.2.3.4": {}}, "credential": {}}}
        result = runner.invoke(app, ["guard", "unbind", "--current"])
    assert result.exit_code == 0
    assert machine_fp in result.output


def test_guard_note_updates_app_note(tmp_path):
    from asc.cli import app
    runner = CliRunner()
    with patch("asc.commands.guard_cmd.Guard") as MockGuard:
        instance = MockGuard.return_value
        instance.set_app_note.return_value = True
        result = runner.invoke(app, ["guard", "note", "--app-id", "123456789", "--note", "办公室 Mac"])
    assert result.exit_code == 0
    instance.set_app_note.assert_called_once_with("123456789", "办公室 Mac")
    assert "办公室 Mac" in result.output


def test_guard_note_missing_app_exits_with_error(tmp_path):
    from asc.cli import app
    runner = CliRunner()
    with patch("asc.commands.guard_cmd.Guard") as MockGuard:
        instance = MockGuard.return_value
        instance.set_app_note.return_value = False
        result = runner.invoke(app, ["guard", "note", "--app-id", "missing.app", "--note", "home"])
    assert result.exit_code == 1
