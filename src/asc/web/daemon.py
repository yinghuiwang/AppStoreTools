"""Background process management for asc Web UI."""
from __future__ import annotations

import json
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

    try:
        proc = subprocess.Popen(
            _uvicorn_cmd(host, port),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=os.getcwd(),
            start_new_session=True,
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


def stop(timeout: float = 5.0) -> dict[str, Any]:
    current = get_status()
    if not current.get("running"):
        clear_state()
        return {"status": "not_running"}

    pid = int(current["pid"])
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        clear_state()
        return {"status": "error", "message": str(exc)}

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_process_alive(pid):
            clear_state()
            return {"status": "stopped", "pid": pid}
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass

    clear_state()
    if is_process_alive(pid):
        return {"status": "error", "message": f"无法停止进程 {pid}"}
    return {"status": "stopped", "pid": pid, "forced": True}
