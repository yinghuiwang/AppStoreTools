import sys
from pathlib import Path

import plistlib
import pytest

from asc.schedule import (
    ScheduleError,
    SystemHeartbeatBackend,
    bootout_command,
    bootout_not_loaded,
    bootout_service_command,
    bootstrap_already_loaded,
    bootstrap_command,
    heartbeat_status,
    install_heartbeat,
    quote_posix_single,
    render_cron_line,
    render_launch_agent_plist,
    resolve_asc_executable,
    uninstall_heartbeat,
    user_message,
)


class FakeHeartbeat:
    def __init__(self, system: str = "darwin"):
        self._system = system
        self.plist = None
        self.crontab = ""
        self.fail_bootstrap = False
        self.crontab_fail_times = 0
        self.bootouts = []
        self.bootstraps = []
        self._plist_path = Path("/tmp/LaunchAgents/com.asc.schedule.plist")
        self._log_path = Path("/tmp/asc-home/schedule-tick.log")

    def system(self):
        return self._system

    def uid(self):
        return 501

    def plist_path(self):
        return self._plist_path

    def log_path(self):
        return self._log_path

    def read_plist(self):
        return self.plist

    def write_plist(self, data: bytes):
        self.plist = data

    def remove_plist(self):
        self.plist = None

    def bootout(self, domain, plist):
        self.bootouts.append((domain, plist))

    def bootstrap(self, domain, plist):
        self.bootstraps.append((domain, plist))
        if self.fail_bootstrap:
            raise RuntimeError("bootstrap failed")

    def read_crontab(self):
        return self.crontab

    def write_crontab(self, text: str):
        if self.crontab_fail_times:
            self.crontab_fail_times -= 1
            self.crontab = text
            raise RuntimeError("crontab failed")
        self.crontab = text


def test_resolve_rejects_python_module_without_asc_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    module = tmp_path / "__main__.py"
    module.write_text("print('no')\n", encoding="utf-8")
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "argv", [str(module), "web"])
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(ScheduleError) as exc:
        resolve_asc_executable()
    assert exc.value.code == "not_executable"


def test_module_invocation_installs_sibling_asc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bindir = tmp_path / "Scripts"
    bindir.mkdir()
    python = bindir / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    asc = bindir / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    asc.chmod(0o755)
    other_bin = tmp_path / "other"
    other_bin.mkdir()
    foreign = other_bin / "asc"
    foreign.write_text("#!/other/python\n", encoding="utf-8")
    foreign.chmod(0o755)
    module = tmp_path / "pkg" / "__main__.py"
    module.parent.mkdir()
    module.write_text("print('module')\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "argv", [str(module), "web"])
    monkeypatch.setenv("PATH", str(other_bin))

    resolved = resolve_asc_executable()
    backend = FakeHeartbeat()
    install_heartbeat(asc_path=resolved, backend=backend)

    assert resolved == asc.resolve()
    program = plistlib.loads(backend.plist)["ProgramArguments"]
    assert program == [str(asc.resolve()), "schedule", "tick"]


def test_module_invocation_uses_same_interpreter_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    real = tmp_path / "python3.12"
    real.write_text("#!/bin/sh\n", encoding="utf-8")
    bindir = tmp_path / "venv" / "bin"
    bindir.mkdir(parents=True)
    python = bindir / "python3"
    python.symlink_to(real)
    linked = bindir / "python"
    linked.symlink_to(real)
    local_bin = tmp_path / "local" / "bin"
    local_bin.mkdir(parents=True)
    asc = local_bin / "asc"
    asc.write_text(f"#!{linked}\n", encoding="utf-8")
    asc.chmod(0o755)
    module = tmp_path / "__main__.py"
    module.write_text("print('module')\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "argv", [str(module), "web"])
    monkeypatch.setenv("PATH", str(local_bin))

    resolved = resolve_asc_executable()
    backend = FakeHeartbeat(system="linux")
    install_heartbeat(asc_path=resolved, backend=backend)

    absolute = str(asc.resolve())
    assert resolved == asc.resolve()
    assert backend.crontab == f"* * * * * {quote_posix_single(absolute)} schedule tick # asc-schedule\n"


def test_module_invocation_rejects_other_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    other = tmp_path / "other-python"
    other.write_text("#!/bin/sh\n", encoding="utf-8")
    local_bin = tmp_path / "local" / "bin"
    local_bin.mkdir(parents=True)
    asc = local_bin / "asc"
    asc.write_text(f"#!/usr/bin/env python3\n#!{other}\n", encoding="utf-8")
    asc.chmod(0o755)
    module = tmp_path / "__main__.py"
    module.write_text("print('module')\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "argv", [str(module), "web"])
    monkeypatch.setenv("PATH", str(local_bin))
    backend = FakeHeartbeat()

    with pytest.raises(ScheduleError) as exc:
        install_heartbeat(asc_path=resolve_asc_executable(), backend=backend)
    assert exc.value.code == "not_executable"
    assert backend.plist is None
    assert backend.bootouts == []


def test_invoked_asc_executable_wins_over_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    python = bindir / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    sibling = bindir / "asc"
    sibling.write_text("#!/bin/sh\n", encoding="utf-8")
    invoked = tmp_path / "prefix" / "asc"
    invoked.parent.mkdir()
    invoked.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "argv", [str(invoked), "schedule", "install"])

    assert resolve_asc_executable() == invoked.resolve()


def test_plist_contains_absolute_asc_and_log(tmp_path: Path):
    asc = tmp_path / "asc"
    log = tmp_path / "schedule-tick.log"
    xml = render_launch_agent_plist(asc, log)
    data = plistlib.loads(xml.encode("utf-8"))
    assert data["Label"] == "com.asc.schedule"
    assert data["ProgramArguments"] == [str(asc), "schedule", "tick"]
    assert data["StartInterval"] == 60
    assert data["RunAtLoad"] is False
    assert data["StandardOutPath"] == str(log)
    assert data["StandardErrorPath"] == str(log)
    assert "~" not in xml


def test_cron_line_quotes_spaces_and_marks_schedule():
    asc = Path("/tmp/it's a/asc")
    line = render_cron_line(asc)
    assert line == "* * * * * '/tmp/it'\\''s a/asc' schedule tick # asc-schedule"
    assert line.endswith("# asc-schedule")
    assert quote_posix_single("/tmp/it's a/asc") == "'/tmp/it'\\''s a/asc'"


def test_launchctl_commands_are_pure():
    plist = Path("/Users/me/Library/LaunchAgents/com.asc.schedule.plist")
    assert bootout_command(501, plist) == [
        "launchctl", "bootout", "gui/501", str(plist)
    ]
    assert bootout_service_command(501) == [
        "launchctl", "bootout", "gui/501/com.asc.schedule"
    ]
    assert bootstrap_command(501, plist) == [
        "launchctl", "bootstrap", "gui/501", str(plist)
    ]
    assert bootout_not_loaded("Boot-out failed: 3: No such process")
    assert bootout_not_loaded("Boot-out failed: 5: Input/output error")
    assert bootout_not_loaded(
        "Boot-out failed: 5: Input/output error\n"
        "Try re-running the command as root for richer errors."
    )
    assert bootout_not_loaded("", 5)
    assert bootout_not_loaded("Could not find specified service")
    assert not bootout_not_loaded("Operation not permitted")
    assert not bootout_not_loaded(
        "Boot-out failed: 125: Domain does not support specified action",
        125,
    )
    assert bootstrap_already_loaded("Bootstrap failed: 17: File exists")
    assert bootstrap_already_loaded("service already bootstrapped")
    assert bootstrap_already_loaded("Bootstrap failed: 5: Input/output error", 5)
    assert not bootstrap_already_loaded("Operation not permitted", 1)


def test_install_darwin_bootstraps_and_repeat_overwrites(tmp_path: Path):
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    backend = FakeHeartbeat()
    install_heartbeat(asc_path=asc.resolve(), backend=backend)
    first = plistlib.loads(backend.plist)
    assert first["ProgramArguments"][0] == str(asc.resolve())
    assert backend.bootouts[0][0] == "gui/501"
    newer = tmp_path / "bin" / "asc"
    newer.parent.mkdir()
    newer.write_text("#!/bin/sh\n", encoding="utf-8")
    install_heartbeat(asc_path=newer.resolve(), backend=backend)
    second = plistlib.loads(backend.plist)
    assert second["ProgramArguments"][0] == str(newer.resolve())


def test_bootstrap_failure_restores_previous_plist(tmp_path: Path):
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    backend = FakeHeartbeat()
    backend.plist = b"OLD"
    backend.fail_bootstrap = True
    with pytest.raises(ScheduleError) as exc:
        install_heartbeat(asc_path=asc.resolve(), backend=backend)
    assert exc.value.code == "install_failed"
    assert backend.plist == b"OLD"


def test_bootstrap_failure_removes_plist_when_none_existed(tmp_path: Path):
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    backend = FakeHeartbeat()
    backend.fail_bootstrap = True
    with pytest.raises(ScheduleError):
        install_heartbeat(asc_path=asc.resolve(), backend=backend)
    assert backend.plist is None


def test_cron_install_keeps_other_lines_and_one_marker(tmp_path: Path):
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    backend = FakeHeartbeat(system="linux")
    backend.crontab = "0 0 * * * echo keep\n* * * * * /old/asc schedule tick # asc-schedule\n"
    install_heartbeat(asc_path=asc.resolve(), backend=backend)
    lines = [line for line in backend.crontab.splitlines() if line]
    assert lines[0] == "0 0 * * * echo keep"
    assert sum(line.rstrip().endswith("# asc-schedule") for line in lines) == 1
    assert str(asc.resolve()) in lines[1]


def test_cron_write_failure_restores_original(tmp_path: Path):
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    backend = FakeHeartbeat(system="linux")
    backend.crontab = "0 0 * * * echo keep\n"
    original = backend.crontab
    backend.crontab_fail_times = 1
    with pytest.raises(ScheduleError) as exc:
        install_heartbeat(asc_path=asc.resolve(), backend=backend)
    assert exc.value.code == "install_failed"
    assert backend.crontab == original


def test_uninstall_missing_is_success_and_removes_markers(tmp_path: Path):
    backend = FakeHeartbeat(system="linux")
    assert uninstall_heartbeat(backend=backend) is False
    backend.crontab = "0 0 * * * echo keep\necho hi # asc-schedule\n# asc-schedule-other\n"
    assert uninstall_heartbeat(backend=backend) is True
    assert backend.crontab.splitlines() == ["0 0 * * * echo keep", "# asc-schedule-other"]


def test_not_executable_does_not_touch_backend(tmp_path: Path):
    backend = FakeHeartbeat()
    backend.crontab = "keep\n"
    missing = tmp_path / "asc"
    with pytest.raises(ScheduleError):
        install_heartbeat(asc_path=missing, backend=backend)
    assert backend.plist is None
    assert backend.crontab == "keep\n"
    assert backend.bootouts == []


class _Proc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_NOT_LOADED = (
    "Boot-out failed: 5: Input/output error\n"
    "Try re-running the command as root for richer errors.\n"
)
_ROOT_HINT = "Try re-running the command as root for richer errors."


class UserAgentBackend(SystemHeartbeatBackend):
    def __init__(self, root: Path):
        self._root = root

    def system(self):
        return "darwin"

    def uid(self):
        return 501

    def plist_path(self):
        return self._root / "Library" / "LaunchAgents" / "com.asc.schedule.plist"

    def log_path(self):
        return self._root / ".config" / "asc" / "schedule-tick.log"


def _write_asc(tmp_path: Path) -> Path:
    asc = tmp_path / "asc"
    asc.write_text("#!/bin/sh\n", encoding="utf-8")
    return asc


def _patch_launchctl(monkeypatch: pytest.MonkeyPatch, script):
    calls = []
    pending = list(script)

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if not pending:
            raise AssertionError(cmd)
        return pending.pop(0)

    monkeypatch.setattr("asc.schedule.subprocess.run", fake_run)
    monkeypatch.setattr("asc.schedule.os.geteuid", lambda: 501)
    return calls


def _gui_commands(plist: Path):
    absolute = str(plist)
    return [
        ["launchctl", "bootout", "gui/501", absolute],
        ["launchctl", "bootstrap", "gui/501", absolute],
    ]


def test_backend_uid_is_process_uid(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("asc.schedule.os.getuid", lambda: 4242)
    assert SystemHeartbeatBackend().uid() == 4242


def test_unloaded_bootout_io_error_then_bootstrap_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    asc = _write_asc(tmp_path)
    backend = UserAgentBackend(tmp_path)
    calls = _patch_launchctl(monkeypatch, [_Proc(5, stderr=_NOT_LOADED), _Proc(0)])

    install_heartbeat(asc_path=asc.resolve(), backend=backend)

    plist = backend.plist_path()
    assert plist.is_file()
    assert plist.is_absolute()
    assert plistlib.loads(plist.read_bytes())["ProgramArguments"][0] == str(asc.resolve())
    assert calls == _gui_commands(plist)
    assert all(cmd[0] == "launchctl" for cmd in calls)
    assert all("system" not in cmd and "sudo" not in cmd for cmd in calls)


def test_root_install_fails_before_launchctl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    asc = _write_asc(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        raise AssertionError("launchctl called")

    monkeypatch.setattr("asc.schedule.subprocess.run", fake_run)
    monkeypatch.setattr("asc.schedule.os.geteuid", lambda: 0)
    monkeypatch.setattr("asc.i18n.LANG", "zh")
    backend = UserAgentBackend(tmp_path)

    with pytest.raises(ScheduleError) as exc:
        install_heartbeat(asc_path=asc.resolve(), backend=backend)

    assert exc.value.code == "user_agent"
    message = user_message(exc.value.code)
    assert "不要使用 sudo" in message
    assert "root" not in message.lower()
    assert calls == []
    assert not backend.plist_path().exists()

    with pytest.raises(ScheduleError) as uninstall_exc:
        uninstall_heartbeat(backend=backend)
    assert uninstall_exc.value.code == "user_agent"
    assert calls == []


def test_bootstrap_failure_after_unloaded_bootout_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    asc = _write_asc(tmp_path)
    backend = UserAgentBackend(tmp_path)
    plist = backend.plist_path()
    plist.parent.mkdir(parents=True)
    plist.write_bytes(b"OLD")
    failure = "Bootstrap failed: 1: Operation not permitted\n" + _ROOT_HINT + "\n"
    calls = _patch_launchctl(
        monkeypatch,
        [
            _Proc(5, stderr=_NOT_LOADED),
            _Proc(1, stderr=failure),
            _Proc(1, stderr=failure),
        ],
    )

    with pytest.raises(ScheduleError) as exc:
        install_heartbeat(asc_path=asc.resolve(), backend=backend)

    assert exc.value.code == "install_failed"
    reason = exc.value.params["reason"]
    assert "Operation not permitted" in reason
    assert "re-running the command as root" not in reason
    assert plist.read_bytes() == b"OLD"
    assert plist.is_absolute()
    assert calls == [
        ["launchctl", "bootout", "gui/501", str(plist)],
        ["launchctl", "bootstrap", "gui/501", str(plist)],
        ["launchctl", "bootstrap", "gui/501", str(plist)],
    ]
    assert all("system" not in cmd and "sudo" not in cmd for cmd in calls)


def test_already_bootstrapped_reloads_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    asc = _write_asc(tmp_path)
    backend = UserAgentBackend(tmp_path)
    already = "Bootstrap failed: 5: Input/output error\n" + _ROOT_HINT + "\n"
    calls = _patch_launchctl(
        monkeypatch,
        [
            _Proc(5, stderr=_NOT_LOADED),
            _Proc(5, stderr=already),
            _Proc(0),
            _Proc(0),
        ],
    )

    install_heartbeat(asc_path=asc.resolve(), backend=backend)

    plist = backend.plist_path()
    assert calls == [
        ["launchctl", "bootout", "gui/501", str(plist)],
        ["launchctl", "bootstrap", "gui/501", str(plist)],
        ["launchctl", "bootout", "gui/501/com.asc.schedule"],
        ["launchctl", "bootstrap", "gui/501", str(plist)],
    ]


def test_second_bootstrap_failure_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    asc = _write_asc(tmp_path)
    backend = UserAgentBackend(tmp_path)
    plist = backend.plist_path()
    plist.parent.mkdir(parents=True)
    plist.write_bytes(b"OLD")
    already = "Bootstrap failed: 5: Input/output error\n" + _ROOT_HINT + "\n"
    failure = "Bootstrap failed: 1: Operation not permitted\n" + _ROOT_HINT + "\n"
    _patch_launchctl(
        monkeypatch,
        [
            _Proc(5, stderr=_NOT_LOADED),
            _Proc(5, stderr=already),
            _Proc(0),
            _Proc(1, stderr=failure),
            _Proc(1, stderr=failure),
        ],
    )

    with pytest.raises(ScheduleError) as exc:
        install_heartbeat(asc_path=asc.resolve(), backend=backend)

    assert exc.value.code == "install_failed"
    assert "re-running the command as root" not in exc.value.params["reason"]
    assert plist.read_bytes() == b"OLD"


def test_uninstall_not_loaded_bootout_removes_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    backend = UserAgentBackend(tmp_path)
    plist = backend.plist_path()
    plist.parent.mkdir(parents=True)
    plist.write_bytes(b"OLD")
    calls = _patch_launchctl(monkeypatch, [_Proc(5, stderr=_NOT_LOADED)])

    assert uninstall_heartbeat(backend=backend) is True
    assert not plist.exists()
    assert calls == [["launchctl", "bootout", "gui/501", str(plist)]]


def test_status_uses_file_not_launchctl_probe():
    darwin = FakeHeartbeat()
    assert heartbeat_status(backend=darwin) == {"installed": False, "path": ""}
    darwin.plist = render_launch_agent_plist(Path("/usr/local/bin/asc"), darwin.log_path()).encode()
    assert heartbeat_status(backend=darwin) == {
        "installed": True,
        "path": "/usr/local/bin/asc",
    }
    darwin.plist = b"not a plist"
    assert heartbeat_status(backend=darwin) == {"installed": True, "path": ""}
    linux = FakeHeartbeat(system="linux")
    linux.crontab = "* * * * * '/usr/local/bin/asc' schedule tick # asc-schedule\n"
    assert heartbeat_status(backend=linux)["installed"] is True
    assert heartbeat_status(backend=linux)["path"] == "/usr/local/bin/asc"
