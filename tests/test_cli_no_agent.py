from __future__ import annotations

from typer.testing import CliRunner

from asc.cli import app


def test_help_has_no_agent_command():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "agent" not in result.output.lower().split()
    # also ensure no `asc agent` typer group
    listed = result.output.lower()
    assert "  agent " not in listed
