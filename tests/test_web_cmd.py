# tests/test_web_cmd.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from asc.cli import app

runner = CliRunner()


def test_web_cmd_help():
    result = runner.invoke(app, ["web", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
    assert "--foreground" in result.output


def test_web_cmd_imports():
    from asc.commands.web_cmd import web_app

    assert web_app is not None


def test_web_cmd_default_uses_background():
    """默认启动应走后端 daemon，而非 uvicorn.run"""
    with patch("asc.commands.web_cmd.start_background") as mock_start, \
         patch("uvicorn.run") as mock_run, \
         patch("webbrowser.open"):
        mock_start.return_value = {
            "status": "started",
            "pid": 12345,
            "url": "http://127.0.0.1:8080",
            "log": "/tmp/web.log",
        }
        result = runner.invoke(app, ["web", "--no-open"])
        assert result.exit_code == 0
        mock_start.assert_called_once_with("127.0.0.1", 8080)
        mock_run.assert_not_called()
        assert "后台启动" in result.output


def test_web_cmd_foreground_runs_uvicorn():
    """--foreground 应调用 uvicorn.run"""
    mock_app = MagicMock()
    with patch("asc.web.server.create_app", return_value=mock_app), \
         patch("uvicorn.run") as mock_run, \
         patch("asc.commands.web_cmd.start_background") as mock_start, \
         patch("threading.Timer"):
        result = runner.invoke(app, ["web", "--foreground", "--no-open", "--port", "9999"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        mock_start.assert_not_called()
        assert mock_run.call_args[1]["port"] == 9999


def test_web_cmd_no_open_skips_browser_on_foreground():
    """--foreground --no-open 时不应调用 webbrowser.open"""
    mock_app = MagicMock()
    with patch("asc.web.server.create_app", return_value=mock_app), \
         patch("uvicorn.run"), \
         patch("webbrowser.open") as mock_browser:
        result = runner.invoke(app, ["web", "--foreground", "--no-open", "--port", "19999"])
        assert result.exit_code == 0
        mock_browser.assert_not_called()


def test_web_cmd_already_running_opens_browser():
    with patch("asc.commands.web_cmd.start_background") as mock_start, \
         patch("asc.commands.web_cmd._open_browser") as mock_open:
        mock_start.return_value = {
            "status": "already_running",
            "pid": 999,
            "url": "http://127.0.0.1:8080",
            "log": "/tmp/web.log",
        }
        result = runner.invoke(app, ["web"])
        assert result.exit_code == 0
        mock_open.assert_called_once_with("http://127.0.0.1:8080")
        assert "已在运行" in result.output


def test_web_cmd_stop():
    with patch("asc.commands.web_cmd.stop") as mock_stop:
        mock_stop.return_value = {"status": "stopped", "pid": 123}
        result = runner.invoke(app, ["web", "stop"])
        assert result.exit_code == 0
        mock_stop.assert_called_once()
        assert "已停止" in result.output


def test_web_cmd_status_running():
    with patch("asc.commands.web_cmd.get_status") as mock_status:
        mock_status.return_value = {
            "running": True,
            "url": "http://127.0.0.1:8080",
            "pid": 123,
            "cwd": "/tmp",
            "log": "/tmp/web.log",
        }
        result = runner.invoke(app, ["web", "status"])
        assert result.exit_code == 0
        assert "运行中" in result.output
