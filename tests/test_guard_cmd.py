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
                "machine": {machine_fp: {"app_id": "123456789", "app_name": "myapp", "bound_at": "2026-05-18T10:00:00"}},
                "ip": {},
                "credential": {},
            }
        }
        instance._get_machine_fingerprint.return_value = machine_fp
        instance._get_public_ip.return_value = "1.2.3.4"
        result = runner.invoke(app, ["guard", "status"])
    assert result.exit_code == 0
    assert "已启用" in result.output or "启用" in result.output
    assert machine_fp in result.output
    assert "办公室 Mac" in result.output
    assert "SERIAL-C02ABC1234..." not in result.output


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
