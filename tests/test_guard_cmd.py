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
    with patch("asc.commands.guard_cmd.Guard") as MockGuard:
        instance = MockGuard.return_value
        instance.is_enabled.return_value = True
        instance.get_status.return_value = {
            "enabled": True,
            "bindings": {"machine": {}, "ip": {}, "credential": {}}
        }
        instance._get_machine_fingerprint.return_value = "fp123abc"
        instance._get_public_ip.return_value = "1.2.3.4"
        result = runner.invoke(app, ["guard", "status"])
    assert result.exit_code == 0
    assert "已启用" in result.output or "启用" in result.output


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
    with patch("asc.commands.guard_cmd.Guard") as MockGuard:
        instance = MockGuard.return_value
        instance._get_machine_fingerprint.return_value = "fp123"
        instance._get_public_ip.return_value = "1.2.3.4"
        instance._data = {"bindings": {"machine": {"fp123": {}}, "ip": {"1.2.3.4": {}}, "credential": {}}}
        result = runner.invoke(app, ["guard", "unbind", "--current"])
    assert result.exit_code == 0
