# tests/test_web_cmd.py
from __future__ import annotations
from unittest.mock import patch, MagicMock
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


def test_web_cmd_no_open_skips_browser():
    """--no-open 时不应调用 webbrowser.open"""
    mock_app = MagicMock()
    with patch("asc.web.server.create_app", return_value=mock_app), \
         patch("uvicorn.run") as mock_run, \
         patch("webbrowser.open") as mock_browser:
        result = runner.invoke(app, ["web", "--no-open", "--port", "19999"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        mock_browser.assert_not_called()


def test_web_cmd_passes_port_to_uvicorn():
    """--port 参数应正确传递给 uvicorn.run"""
    mock_app = MagicMock()
    with patch("asc.web.server.create_app", return_value=mock_app), \
         patch("uvicorn.run") as mock_run, \
         patch("threading.Timer"):
        result = runner.invoke(app, ["web", "--no-open", "--port", "9999"])
        assert result.exit_code == 0
        call_kwargs = mock_run.call_args
        assert call_kwargs[1]["port"] == 9999
