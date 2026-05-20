# tests/test_web_daemon.py
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from asc.web import daemon


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    state_dir = tmp_path / "asc"
    state_file = state_dir / "web.json"
    log_file = state_dir / "web.log"
    monkeypatch.setattr(daemon, "STATE_FILE", state_file)
    monkeypatch.setattr(daemon, "LOG_FILE", log_file)
    monkeypatch.setattr(daemon, "_STATE_DIR", state_dir)
    return state_file, log_file


def test_get_status_not_running(isolated_state):
    assert daemon.get_status() == {"running": False}


def test_get_status_running(isolated_state):
    state_file, _ = isolated_state
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 8080, "cwd": "/tmp"}),
        encoding="utf-8",
    )
    with patch.object(daemon, "is_process_alive", return_value=True):
        status = daemon.get_status()
    assert status["running"] is True
    assert status["pid"] == 4242
    assert status["url"] == "http://127.0.0.1:8080"


def test_get_status_clears_stale_state(isolated_state):
    state_file, _ = isolated_state
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"pid": 1, "host": "127.0.0.1", "port": 8080}), encoding="utf-8")
    with patch.object(daemon, "is_process_alive", return_value=False):
        status = daemon.get_status()
    assert status == {"running": False, "stale": True}
    assert not state_file.exists()


def test_start_background_already_running(isolated_state):
    with patch.object(
        daemon,
        "get_status",
        return_value={"running": True, "pid": 99, "url": "http://127.0.0.1:8080", "log": "/tmp/web.log"},
    ):
        result = daemon.start_background("127.0.0.1", 8080)
    assert result["status"] == "already_running"
    assert result["pid"] == 99


def test_start_background_starts_process(isolated_state):
    state_file, log_file = isolated_state
    mock_proc = MagicMock()
    mock_proc.pid = 55555

    with patch.object(daemon, "get_status", return_value={"running": False}), \
         patch("asc.web.daemon.subprocess.Popen", return_value=mock_proc) as mock_popen:
        result = daemon.start_background("127.0.0.1", 9090)

    assert result["status"] == "started"
    assert result["pid"] == 55555
    assert result["url"] == "http://127.0.0.1:9090"
    mock_popen.assert_called_once()
    assert state_file.exists()
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["pid"] == 55555
    assert saved["port"] == 9090
    assert log_file.exists()


def test_stop_not_running(isolated_state):
    result = daemon.stop()
    assert result == {"status": "not_running"}


def test_stop_sends_sigterm(isolated_state):
    state_file, _ = isolated_state
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"pid": 777, "host": "127.0.0.1", "port": 8080}), encoding="utf-8")

    with patch.object(daemon, "is_process_alive", side_effect=[True, False]), \
         patch("asc.web.daemon.os.kill") as mock_kill:
        result = daemon.stop(timeout=0.2)

    assert result["status"] == "stopped"
    assert result["pid"] == 777
    mock_kill.assert_called_once()
    assert not state_file.exists()
