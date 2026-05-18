# tests/test_web_cmd.py
from __future__ import annotations
from unittest.mock import patch
from typer.testing import CliRunner
from asc.cli import app

runner = CliRunner()

def test_web_cmd_help():
    result = runner.invoke(app, ["web", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output

def test_web_cmd_imports():
    from asc.commands.web_cmd import cmd_web
    assert callable(cmd_web)
