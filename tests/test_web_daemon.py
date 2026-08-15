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
         patch.object(daemon, "_signal_pid") as mock_signal:
        result = daemon.stop(timeout=0.2)

    assert result["status"] == "stopped"
    assert result["pid"] == 777
    mock_signal.assert_called_once()
    assert not state_file.exists()


def test_stop_with_explicit_pid(isolated_state):
    state_file, _ = isolated_state
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"pid": 111, "host": "127.0.0.1", "port": 8080}), encoding="utf-8")

    with patch.object(daemon, "is_process_alive", side_effect=[True, False]), \
         patch.object(daemon, "_signal_pid") as mock_signal:
        result = daemon.stop(timeout=0.2, pid=999)

    assert result["status"] == "stopped"
    assert result["pid"] == 999
    assert mock_signal.call_args.args[0] == 999


def test_signal_pid_uses_killpg_for_session_leader():
    import signal as signal_mod

    with patch("asc.web.daemon.os.getpgid", return_value=4242), \
         patch("asc.web.daemon.os.killpg") as killpg, \
         patch("asc.web.daemon.os.kill") as kill:
        daemon._signal_pid(4242, signal_mod.SIGTERM)

    killpg.assert_called_once_with(4242, signal_mod.SIGTERM)
    kill.assert_not_called()


def test_signal_pid_uses_kill_when_not_group_leader():
    import signal as signal_mod

    with patch("asc.web.daemon.os.getpgid", return_value=1), \
         patch("asc.web.daemon.os.killpg") as killpg, \
         patch("asc.web.daemon.os.kill") as kill:
        daemon._signal_pid(4242, signal_mod.SIGTERM)

    kill.assert_called_once_with(4242, signal_mod.SIGTERM)
    killpg.assert_not_called()


def test_schedule_restart_spawns_helper(isolated_state):
    import sys

    state_file, log_file = isolated_state
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 9090, "cwd": "/tmp"}),
        encoding="utf-8",
    )
    mock_proc = MagicMock()
    mock_proc.pid = 99999

    with patch.object(daemon, "is_process_alive", return_value=True), \
         patch("asc.web.daemon.os.getpid", return_value=555), \
         patch("asc.web.daemon.subprocess.Popen", return_value=mock_proc) as mock_popen:
        result = daemon.schedule_restart(delay=1.5)

    assert result["status"] == "scheduled"
    assert result["helper_pid"] == 99999
    assert result["target_pid"] == 555
    assert result["port"] == 9090
    assert result["delay"] == 1.5
    mock_popen.assert_called_once()
    args = mock_popen.call_args
    assert args.args[0][0] == sys.executable
    assert args.args[0][1] == "-c"
    helper_code = args.args[0][2]
    assert "time.sleep(1.5)" in helper_code
    assert "daemon.stop" in helper_code
    assert "pid=target_pid" in helper_code
    assert "_wait_port_free" in helper_code
    assert "start_background(host, port)" in helper_code
    assert log_file.exists()
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["pid"] == 555


def test_schedule_restart_registers_unmanaged_process(isolated_state):
    state_file, _ = isolated_state
    mock_proc = MagicMock()
    mock_proc.pid = 88888

    with patch.object(daemon, "get_status", return_value={"running": False}), \
         patch("asc.web.daemon.subprocess.Popen", return_value=mock_proc), \
         patch("asc.web.daemon.os.getpid", return_value=321), \
         patch.dict("os.environ", {"ASC_WEB_HOST": "127.0.0.1", "ASC_WEB_PORT": "8080"}, clear=False):
        result = daemon.schedule_restart(delay=0.5)

    assert result["status"] == "scheduled"
    assert result["target_pid"] == 321
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["pid"] == 321
    assert saved["port"] == 8080


def test_wait_port_free_when_connect_fails(isolated_state):
    with patch("socket.socket") as sock_cls:
        sock = sock_cls.return_value
        sock.connect_ex.return_value = 1
        assert daemon._wait_port_free("127.0.0.1", 65530, timeout=0.5) is True


def test_port_in_use_when_connect_succeeds(isolated_state):
    with patch("socket.socket") as sock_cls:
        sock = sock_cls.return_value
        sock.connect_ex.return_value = 0
        assert daemon.port_in_use("127.0.0.1", 8080) is True


def test_update_restart_marker_roundtrip(isolated_state):
    path = daemon.write_update_restart_marker("task-123", installed=True)
    assert path.exists()
    data = daemon.read_update_restart_marker()
    assert data is not None
    assert data["task_id"] == "task-123"
    assert data["installed"] is True
    daemon.clear_update_restart_marker()
    assert daemon.read_update_restart_marker() is None


def test_schedule_restart_includes_deferred_install(isolated_state):
    mock_proc = MagicMock()
    mock_proc.pid = 99999

    with patch.object(daemon, "get_status", return_value={"running": False}), \
         patch("asc.web.daemon.subprocess.Popen", return_value=mock_proc) as popen, \
         patch("asc.web.daemon.os.getpid", return_value=321), \
         patch.dict("os.environ", {"ASC_WEB_HOST": "127.0.0.1", "ASC_WEB_PORT": "8080"}, clear=False):
        result = daemon.schedule_restart(
            delay=0.5,
            install_ref="v0.1.26",
            commit="a" * 40,
            task_id="task-xyz",
        )

    assert result["status"] == "scheduled"
    assert result["install_ref"] == "v0.1.26"
    assert result["task_id"] == "task-xyz"
    helper_code = popen.call_args.args[0][2]
    assert "run_deferred_package_install" in helper_code
    assert "v0.1.26" in helper_code
    assert "task-xyz" in helper_code


def test_run_deferred_package_install_updates_marker(isolated_state, tmp_path, monkeypatch):
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("update", profile="system")
    monkeypatch.setattr("asc.web.tasks.task_store", store)
    daemon.write_update_restart_marker(task_id, pending_install=True, installed=False)

    with patch("asc.commands.update_cmd._install_git_ref") as install:
        result = daemon.run_deferred_package_install(
            install_ref="main",
            commit="b" * 40,
            task_id=task_id,
        )

    install.assert_called_once()
    assert result["status"] == "installed"
    marker = daemon.read_update_restart_marker()
    assert marker is not None
    assert marker["installed"] is True
    assert marker.get("pending_install") is False


def test_deferred_install_real_stream_persists_semantic_pip_events(
    isolated_state,
    tmp_path,
    monkeypatch,
):
    from asc.web.tasks import TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("update", profile="system")
    monkeypatch.setattr("asc.web.tasks.task_store", store)
    daemon.write_update_restart_marker(task_id, pending_install=True, installed=False)
    lines = [
        *(f"Collecting package-{index}\n" for index in range(100)),
        "Downloading package-a (25%)\n",
        "Installing collected packages: package-a\n",
        "Successfully installed package-a\n",
    ]
    proc = MagicMock()
    proc.stdout = iter(lines)
    proc.poll.return_value = 0
    proc.wait.return_value = 0

    with patch("asc.commands.update_cmd.subprocess.Popen", return_value=proc):
        result = daemon.run_deferred_package_install(
            install_ref="main",
            commit="b" * 40,
            task_id=task_id,
        )

    assert result["status"] == "installed"
    task = store.get(task_id)
    assert task is not None
    logs = task["logs"]
    assert any("Collecting 100" in line for line in logs)
    assert not any(line == "Collecting package-99" for line in logs)
    assert any("Deferred pip install after Web UI stop" in line for line in logs)
    assert any("Deferred package install completed" in line for line in logs)
    assert any("Downloading 25%" in line for line in logs)
