"""Background process management for asc Web UI."""
from __future__ import annotations

import json
import ipaddress
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_STATE_DIR = Path.home() / ".config" / "asc"
STATE_FILE = _STATE_DIR / "web.json"
LOG_FILE = _STATE_DIR / "web.log"


def _update_restart_path() -> Path:
    return _STATE_DIR / "update_restart.json"


def is_loopback_host(host: str) -> bool:
    """Return whether *host* is a loopback address accepted by the local UI."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _open_url(host: str, port: int) -> str:
    open_host = "127.0.0.1" if host == "0.0.0.0" else host
    return f"http://{open_host}:{port}"


def is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_state() -> dict[str, Any] | None:
    if not STATE_FILE.exists():
        return None
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_state(state: dict[str, Any]) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def clear_state() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def write_update_restart_marker(task_id: str, **extra: Any) -> Path:
    """Persist pending update completion across the Web UI process restart."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": str(task_id),
        "scheduled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "old_pid": os.getpid(),
        **{key: value for key, value in extra.items() if value is not None},
    }
    path = _update_restart_path()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def read_update_restart_marker() -> dict[str, Any] | None:
    path = _update_restart_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("task_id"):
        return None
    return data


def clear_update_restart_marker() -> None:
    path = _update_restart_path()
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def get_status() -> dict[str, Any]:
    state = read_state()
    if not state:
        return {"running": False}

    pid = int(state.get("pid", 0))
    if not is_process_alive(pid):
        clear_state()
        return {"running": False, "stale": True}

    host = str(state.get("host", "127.0.0.1"))
    port = int(state.get("port", 8080))
    return {
        "running": True,
        "pid": pid,
        "host": host,
        "port": port,
        "url": _open_url(host, port),
        "cwd": state.get("cwd", ""),
        "log": str(state.get("log", LOG_FILE)),
    }


def _uvicorn_cmd(host: str, port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "asc.web.server:create_app",
        "--factory",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        "info",
    ]


def start_background(host: str, port: int) -> dict[str, Any]:
    if not is_loopback_host(host):
        return {
            "status": "error",
            "message": "Web UI only supports loopback hosts (127.0.0.1, ::1, or localhost)",
        }
    current = get_status()
    if current.get("running"):
        return {
            "status": "already_running",
            "pid": current["pid"],
            "url": current["url"],
            "log": current.get("log", str(LOG_FILE)),
        }

    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_FILE
    log_handle = open(log_path, "a", encoding="utf-8")
    log_handle.write(
        f"\n--- asc web started at {time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"({host}:{port}, cwd={os.getcwd()}) ---\n"
    )
    log_handle.flush()

    env = os.environ.copy()
    env["ASC_WEB_HOST"] = host
    env["ASC_WEB_PORT"] = str(port)

    try:
        proc = subprocess.Popen(
            _uvicorn_cmd(host, port),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=os.getcwd(),
            start_new_session=True,
            env=env,
        )
    except OSError as exc:
        log_handle.close()
        return {"status": "error", "message": str(exc)}

    url = _open_url(host, port)
    state = {
        "pid": proc.pid,
        "host": host,
        "port": port,
        "cwd": os.getcwd(),
        "log": str(log_path),
        "url": url,
    }
    write_state(state)
    return {
        "status": "started",
        "pid": proc.pid,
        "url": url,
        "log": str(log_path),
    }


def _signal_pid(pid: int, sig: signal.Signals) -> None:
    """Send *sig* to *pid*, preferring the process group when *pid* is the leader.

    Background Web UI processes are started with ``start_new_session=True``, so
    their PID equals the process-group ID. Only then is ``killpg`` safe; for a
    foreground server that shares the shell's process group we signal the PID
    alone so we do not tear down the user's terminal.
    """
    try:
        pgid = os.getpgid(pid)
    except OSError:
        pgid = None
    if pgid is not None and pgid == pid:
        os.killpg(pid, sig)
        return
    os.kill(pid, sig)


def stop(timeout: float = 5.0, *, pid: int | None = None) -> dict[str, Any]:
    """Stop the Web UI process recorded in state (or an explicit *pid*)."""
    if pid is not None:
        target_pid = int(pid)
        if not is_process_alive(target_pid):
            clear_state()
            return {"status": "not_running"}
    else:
        current = get_status()
        if not current.get("running"):
            clear_state()
            return {"status": "not_running"}
        target_pid = int(current["pid"])

    try:
        _signal_pid(target_pid, signal.SIGTERM)
    except OSError as exc:
        clear_state()
        return {"status": "error", "message": str(exc)}

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_process_alive(target_pid):
            clear_state()
            return {"status": "stopped", "pid": target_pid}
        time.sleep(0.1)

    try:
        _signal_pid(target_pid, signal.SIGKILL)
    except OSError:
        pass

    clear_state()
    if is_process_alive(target_pid):
        return {"status": "error", "message": f"无法停止进程 {target_pid}"}
    return {"status": "stopped", "pid": target_pid, "forced": True}


def _wait_port_free(host: str, port: int, timeout: float = 10.0) -> bool:
    """Return True once *host*:*port* accepts no listener (or timeout)."""
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        try:
            # Empty host / 0.0.0.0 → probe loopback where clients connect.
            probe_host = "127.0.0.1" if host in {"0.0.0.0", "", "::"} else host
            if sock.connect_ex((probe_host, int(port))) != 0:
                return True
        except OSError:
            return True
        finally:
            sock.close()
        time.sleep(0.15)
    return False


def schedule_restart(*, delay: float = 2.0) -> dict[str, Any]:
    """Detach a helper that stops then restarts the Web UI after ``delay`` seconds.

    Used after a successful ``asc`` package update so the running server loads
    the newly installed code. The helper is a separate process and survives
    the current uvicorn shutdown.

    Always pins ``os.getpid()`` (this server process) as the stop target so a
    stale ``web.json`` cannot leave the old UI running after an update.
    """
    current = get_status()
    if current.get("running"):
        host = str(current["host"])
        port = int(current["port"])
        cwd = str(current.get("cwd") or os.getcwd())
    else:
        host = os.environ.get("ASC_WEB_HOST", "127.0.0.1")
        port = int(os.environ.get("ASC_WEB_PORT", "8080"))
        cwd = os.getcwd()
    target_pid = os.getpid()

    # Refresh state so stop() / the helper always aim at this live process.
    write_state(
        {
            "pid": target_pid,
            "host": host,
            "port": port,
            "cwd": cwd,
            "log": str(LOG_FILE),
            "url": _open_url(host, port),
        }
    )

    # Explicit pid + port-wait + retry start: survives stale state and TIME_WAIT.
    helper_code = (
        "import os, time\n"
        f"time.sleep({float(delay)!r})\n"
        "from asc.web import daemon\n"
        f"target_pid = {int(target_pid)}\n"
        f"host = {host!r}\n"
        f"port = {int(port)}\n"
        f"cwd = {cwd!r}\n"
        "daemon.write_state({\n"
        "    'pid': target_pid, 'host': host, 'port': port, 'cwd': cwd,\n"
        "    'log': str(daemon.LOG_FILE), 'url': daemon._open_url(host, port),\n"
        "})\n"
        "print(daemon.stop(timeout=10.0, pid=target_pid))\n"
        "daemon._wait_port_free(host, port, timeout=15.0)\n"
        "os.chdir(cwd)\n"
        "result = None\n"
        "for attempt in range(8):\n"
        "    result = daemon.start_background(host, port)\n"
        "    print(result)\n"
        "    status = result.get('status')\n"
        "    if status == 'started':\n"
        "        break\n"
        "    if status == 'already_running' and result.get('pid') != target_pid:\n"
        "        break\n"
        "    time.sleep(0.5)\n"
        "print(result)\n"
    )
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = open(LOG_FILE, "a", encoding="utf-8")
    log_handle.write(
        f"\n--- asc web restart scheduled at {time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"(delay={delay}s, pid={target_pid}, {host}:{port}) ---\n"
    )
    log_handle.flush()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", helper_code],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        log_handle.close()
        return {"status": "error", "message": str(exc)}

    return {
        "status": "scheduled",
        "helper_pid": proc.pid,
        "target_pid": target_pid,
        "host": host,
        "port": port,
        "delay": delay,
        "url": _open_url(host, port),
    }
