import subprocess
import sys
import xml.etree.ElementTree as ET
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
    render_windows_task_xml,
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


class WindowsScheduler(SystemHeartbeatBackend):
    def system(self):
        return "windows"


def _forbid_posix_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden():
        raise AssertionError("posix identity")

    monkeypatch.setattr("asc.schedule.os.getuid", forbidden)
    monkeypatch.setattr("asc.schedule.os.geteuid", forbidden, raising=False)


def _patch_schtasks(monkeypatch: pytest.MonkeyPatch, fake_run):
    calls = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        assert kwargs.get("stdin") is subprocess.DEVNULL
        assert "crontab" not in cmd
        assert "launchctl" not in cmd
        return fake_run(list(cmd), **kwargs)

    monkeypatch.setattr("asc.schedule.subprocess.run", run)
    return calls


def _task_xml_text(data: bytes) -> str:
    return data.decode("utf-16")


def test_windows_task_xml_is_minute_interactive_user_task(tmp_path: Path):
    from asc.schedule import render_windows_task_xml

    asc = tmp_path / "中文目录" / "asc.exe"
    asc.parent.mkdir()
    asc.write_bytes(b"MZ")
    xml = render_windows_task_xml(asc.resolve(), r"CONTOSO\wang")
    root = ET.fromstring(xml.encode("utf-16"))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.tag == "{http://schemas.microsoft.com/windows/2004/02/mit/task}Task"
    assert root.findtext("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", namespaces=ns) == "PT1M"
    assert root.findtext("t:Triggers/t:TimeTrigger/t:StartBoundary", namespaces=ns)
    assert root.find("t:Triggers/t:TimeTrigger/t:EndBoundary", namespaces=ns) is None
    assert root.find("t:Triggers/t:TimeTrigger/t:Repetition/t:Duration", namespaces=ns) is None
    assert "EndBoundary" not in xml
    assert "<Duration>" not in xml
    assert root.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns) == "InteractiveToken"
    assert root.findtext("t:Principals/t:Principal/t:UserId", namespaces=ns) == r"CONTOSO\wang"
    assert "SYSTEM" not in root.findtext("t:Principals/t:Principal/t:UserId", namespaces=ns)
    assert root.findtext("t:Settings/t:DisallowStartIfOnBatteries", namespaces=ns) == "false"
    assert root.findtext("t:Settings/t:StopIfGoingOnBatteries", namespaces=ns) == "false"
    assert root.findtext("t:Actions/t:Exec/t:Command", namespaces=ns) == str(asc.resolve())
    assert root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns) == "schedule tick"
    assert asc.resolve().is_absolute()


def test_windows_user_id_uses_domain_or_dot_username(monkeypatch: pytest.MonkeyPatch):
    from asc.schedule import windows_task_user_id

    monkeypatch.setenv("USERDOMAIN", "CONTOSO")
    monkeypatch.setenv("USERNAME", "wang")
    assert windows_task_user_id() == r"CONTOSO\wang"
    monkeypatch.delenv("USERDOMAIN", raising=False)
    assert windows_task_user_id() == r".\wang"
    monkeypatch.setenv("USERNAME", r"CONTOSO\wang")
    assert windows_task_user_id() == r"CONTOSO\wang"


def test_windows_install_calls_schtasks_create_with_utf16_xml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    asc = tmp_path / "中文目录" / "asc.exe"
    asc.parent.mkdir()
    asc.write_bytes(b"MZ")
    monkeypatch.setenv("USERDOMAIN", "CONTOSO")
    monkeypatch.setenv("USERNAME", "wang")
    _forbid_posix_identity(monkeypatch)
    seen = {}

    def fake_run(cmd, **kwargs):
        assert cmd[:5] == ["schtasks", "/Create", "/TN", "com.asc.schedule", "/XML"]
        assert cmd[6:] == ["/F"]
        forbidden = {"/RU", "/RP", "/NP", "/RL", "HIGHEST", "SYSTEM"}
        assert forbidden.isdisjoint(cmd)
        xml_path = Path(cmd[5])
        seen["path"] = xml_path
        seen["existed"] = xml_path.is_file()
        seen["data"] = xml_path.read_bytes()
        return _Proc(0, stdout="SUCCESS")

    calls = _patch_schtasks(monkeypatch, fake_run)
    install_heartbeat(asc_path=asc.resolve(), backend=WindowsScheduler())

    assert len(calls) == 1
    assert calls[0][0] == "schtasks"
    assert seen["existed"] is True
    assert seen["data"].startswith((b"\xff\xfe", b"\xfe\xff"))
    assert not seen["path"].exists()
    text = _task_xml_text(seen["data"])
    root = ET.fromstring(seen["data"])
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.findtext("t:Actions/t:Exec/t:Command", namespaces=ns) == str(asc.resolve())
    assert root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns) == "schedule tick"
    assert root.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns) == "InteractiveToken"
    assert root.findtext("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", namespaces=ns) == "PT1M"
    assert "EndBoundary" not in text


def test_windows_create_failure_leaves_no_task_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    asc = tmp_path / "asc.exe"
    asc.write_bytes(b"MZ")
    monkeypatch.setenv("USERNAME", "wang")
    monkeypatch.delenv("USERDOMAIN", raising=False)
    _forbid_posix_identity(monkeypatch)
    seen = {}

    def fake_run(cmd, **kwargs):
        assert cmd[1] == "/Create"
        xml_path = Path(cmd[5])
        seen["path"] = xml_path
        seen["data"] = xml_path.read_bytes()
        return _Proc(1, stderr="ERROR: Access is denied.")

    calls = _patch_schtasks(monkeypatch, fake_run)
    with pytest.raises(ScheduleError) as exc:
        install_heartbeat(asc_path=asc.resolve(), backend=WindowsScheduler())
    assert exc.value.code == "install_failed"
    assert len(calls) == 1
    assert not seen["path"].exists()
    text = _task_xml_text(seen["data"])
    assert r".\wang" in text
    assert "SYSTEM" not in text


def test_windows_not_executable_does_not_call_schtasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def fake_run(cmd, **kwargs):
        raise AssertionError(cmd)

    monkeypatch.setattr("asc.schedule.subprocess.run", fake_run)
    _forbid_posix_identity(monkeypatch)
    with pytest.raises(ScheduleError) as exc:
        install_heartbeat(asc_path=tmp_path / "missing.exe", backend=WindowsScheduler())
    assert exc.value.code == "not_executable"


def test_windows_missing_username_does_not_call_schtasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    asc = tmp_path / "asc.exe"
    asc.write_bytes(b"MZ")
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("USERDOMAIN", raising=False)

    def fake_run(cmd, **kwargs):
        raise AssertionError(cmd)

    monkeypatch.setattr("asc.schedule.subprocess.run", fake_run)
    with pytest.raises(ScheduleError) as exc:
        install_heartbeat(asc_path=asc.resolve(), backend=WindowsScheduler())
    assert exc.value.code == "install_failed"


def test_windows_query_parses_path_and_delete_uses_schtasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from asc.schedule import render_windows_task_xml

    asc = tmp_path / "asc.exe"
    asc.write_bytes(b"MZ")
    xml = render_windows_task_xml(asc.resolve(), r".\wang")

    def fake_run(cmd, **kwargs):
        if cmd[1] == "/Query":
            assert cmd == ["schtasks", "/Query", "/TN", "com.asc.schedule", "/XML"]
            return _Proc(0, stdout=xml)
        if cmd[1] == "/Delete":
            assert cmd == ["schtasks", "/Delete", "/TN", "com.asc.schedule", "/F"]
            return _Proc(0, stdout="SUCCESS")
        raise AssertionError(cmd)

    calls = _patch_schtasks(monkeypatch, fake_run)
    assert heartbeat_status(backend=WindowsScheduler()) == {
        "installed": True,
        "path": str(asc.resolve()),
    }
    assert uninstall_heartbeat(backend=WindowsScheduler()) is True
    assert [cmd[1] for cmd in calls] == ["/Query", "/Query", "/Delete"]


def test_windows_missing_task_uninstall_returns_false(monkeypatch: pytest.MonkeyPatch):
    def fake_run(cmd, **kwargs):
        assert cmd[1] == "/Query"
        return _Proc(1, stderr="ERROR: The system cannot find the file specified.")

    calls = _patch_schtasks(monkeypatch, fake_run)
    assert heartbeat_status(backend=WindowsScheduler()) == {"installed": False, "path": ""}
    assert uninstall_heartbeat(backend=WindowsScheduler()) is False
    assert all(cmd[1] == "/Query" for cmd in calls)
    assert all(cmd[1] != "/Delete" for cmd in calls)


def test_windows_query_permission_is_not_treated_as_missing(monkeypatch: pytest.MonkeyPatch):
    def fake_run(cmd, **kwargs):
        return _Proc(1, stderr="ERROR: Access is denied.")

    _patch_schtasks(monkeypatch, fake_run)
    with pytest.raises(ScheduleError) as status_exc:
        heartbeat_status(backend=WindowsScheduler())
    assert status_exc.value.code == "install_failed"
    with pytest.raises(ScheduleError) as uninstall_exc:
        uninstall_heartbeat(backend=WindowsScheduler())
    assert uninstall_exc.value.code == "uninstall_failed"


def test_windows_query_without_error_token_is_not_missing(monkeypatch: pytest.MonkeyPatch):
    def fake_run(cmd, **kwargs):
        return _Proc(1, stderr="schtasks failed")

    _patch_schtasks(monkeypatch, fake_run)
    with pytest.raises(ScheduleError) as status_exc:
        heartbeat_status(backend=WindowsScheduler())
    assert status_exc.value.code == "install_failed"
    with pytest.raises(ScheduleError) as uninstall_exc:
        uninstall_heartbeat(backend=WindowsScheduler())
    assert uninstall_exc.value.code == "uninstall_failed"


def test_resolve_asc_exe_direct_sibling_scripts_and_foreign_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    direct = tmp_path / "dist" / "ASC.EXE"
    direct.parent.mkdir()
    direct.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(sys, "argv", [str(direct)])
    assert resolve_asc_executable() == direct.resolve()

    bindir = tmp_path / "venv" / "Scripts"
    bindir.mkdir(parents=True)
    python = bindir / "python.exe"
    python.write_bytes(b"MZ")
    sibling = bindir / "Asc.ExE"
    sibling.write_bytes(b"MZ")
    foreign_dir = tmp_path / "other" / "Scripts"
    foreign_dir.mkdir(parents=True)
    foreign = foreign_dir / "asc.exe"
    foreign.write_bytes(b"MZ")
    module = tmp_path / "pkg" / "__main__.py"
    module.parent.mkdir()
    module.write_text("print('module')\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "argv", [str(module)])
    monkeypatch.setenv("PATH", str(foreign_dir))
    assert resolve_asc_executable() == sibling.resolve()

    root = tmp_path / "Python312"
    root.mkdir()
    base_python = root / "python.exe"
    base_python.write_bytes(b"MZ")
    scripts_asc = root / "Scripts" / "asc.exe"
    scripts_asc.parent.mkdir()
    scripts_asc.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "executable", str(base_python))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    assert resolve_asc_executable() == scripts_asc.resolve()

    other_python = tmp_path / "elsewhere" / "python.exe"
    other_python.parent.mkdir()
    other_python.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "executable", str(other_python))
    monkeypatch.setenv("PATH", str(foreign_dir))
    with pytest.raises(ScheduleError) as exc:
        resolve_asc_executable()
    assert exc.value.code == "not_executable"


def _windows_task_action(monkeypatch: pytest.MonkeyPatch, asc_path: Path):
    monkeypatch.setenv("USERNAME", "Administrator")
    monkeypatch.delenv("USERDOMAIN", raising=False)
    _forbid_posix_identity(monkeypatch)
    seen = {}

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "schtasks" and cmd[1] == "/Create"
        xml_path = Path(cmd[5])
        seen["data"] = xml_path.read_bytes()
        return _Proc(0, stdout="SUCCESS")

    calls = _patch_schtasks(monkeypatch, fake_run)
    install_heartbeat(asc_path=asc_path, backend=WindowsScheduler())
    root = ET.fromstring(seen["data"])
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    return (
        calls,
        root.findtext("t:Actions/t:Exec/t:Command", namespaces=ns),
        root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns),
    )


def _pip_user_layout(tmp_path: Path):
    python = (
        tmp_path
        / "AppData"
        / "Local"
        / "Programs"
        / "Python"
        / "Python312"
        / "python.exe"
    )
    scripts = tmp_path / "AppData" / "Roaming" / "Python" / "Python312" / "Scripts"
    python.parent.mkdir(parents=True)
    scripts.mkdir(parents=True)
    python.write_bytes(b"MZ")
    exe = scripts / "asc.exe"
    exe.write_bytes(b"MZ")
    script = scripts / "asc-script.py"
    return python, exe, script


def test_windows_asc_exe_schedules_absolute_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "Python312"
    python = root / "python.exe"
    python.parent.mkdir()
    python.write_bytes(b"MZ")
    scripts = root / "Scripts"
    scripts.mkdir()
    exe = scripts / "ASC.EXE"
    exe.write_bytes(b"MZ")
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "argv", [str(exe), "schedule", "install"])
    monkeypatch.setenv("PATH", str(empty))

    resolved = resolve_asc_executable()
    calls, command, arguments = _windows_task_action(monkeypatch, resolved)

    assert resolved == exe.resolve()
    assert len(calls) == 1
    assert command == str(exe.resolve())
    assert arguments == "schedule tick"
    assert command != str(python.resolve())

    venv_python = scripts / "python.exe"
    venv_python.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "executable", str(venv_python))
    assert resolve_asc_executable() == exe.resolve()


def test_windows_asc_script_schedules_sibling_exe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    python, exe, script = _pip_user_layout(tmp_path)
    script.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "argv", [str(script), "schedule", "install"])
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("PYTHONUSERBASE", raising=False)

    resolved = resolve_asc_executable()
    calls, command, arguments = _windows_task_action(monkeypatch, resolved)

    assert resolved == exe.resolve()
    assert len(calls) == 1
    assert command == str(exe.resolve())
    assert arguments == "schedule tick"
    assert not command.lower().endswith("python.exe")
    assert not command.endswith("asc-script.py")

    quoted = tmp_path / "quoted" / "asc-script.py"
    quoted.parent.mkdir()
    quoted_exe = quoted.parent / "asc.exe"
    quoted_exe.write_bytes(b"MZ")
    quoted.write_text(f'#!"{python}"\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(quoted), "schedule", "install"])
    assert resolve_asc_executable() == quoted_exe.resolve()

    monkeypatch.setattr(sys, "argv", [str(script.parent / "asc"), "schedule", "install"])
    assert resolve_asc_executable() == exe.resolve()


def test_windows_python_module_does_not_schedule_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    python, exe, script = _pip_user_layout(tmp_path)
    script.write_text(f"#!{python}\n", encoding="utf-8")
    module = tmp_path / "site-packages" / "asc" / "__main__.py"
    module.parent.mkdir(parents=True)
    module.write_text("print('module')\n", encoding="utf-8")
    foreign = tmp_path / "other" / "python.exe"
    foreign.parent.mkdir()
    foreign.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "argv", [str(module), "schedule", "install"])
    monkeypatch.setenv("PATH", str(exe.parent))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("PYTHONUSERBASE", raising=False)

    def fake_run(cmd, **kwargs):
        raise AssertionError(cmd)

    monkeypatch.setattr("asc.schedule.subprocess.run", fake_run)
    with pytest.raises(ScheduleError) as exc:
        install_heartbeat(asc_path=resolve_asc_executable(), backend=WindowsScheduler())
    assert exc.value.code == "not_executable"

    stray = tmp_path / "stray" / "asc-script.py"
    stray.parent.mkdir()
    stray_exe = stray.parent / "asc.exe"
    stray_exe.write_bytes(b"MZ")
    stray.write_text(f"#!{foreign}\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(stray), "schedule", "install"])
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    assert resolve_asc_executable() == stray_exe.resolve()


def _administrator_pip_layout(tmp_path: Path):
    """python.org per-user install: Local python.exe, Roaming Scripts asc.exe."""
    root = tmp_path / "Users" / "Administrator" / "AppData"
    python = root / "Local" / "Programs" / "Python" / "Python312" / "python.exe"
    scripts = root / "Roaming" / "Python" / "Python312" / "Scripts"
    site = root / "Roaming" / "Python" / "Python312" / "site-packages" / "asc"
    python.parent.mkdir(parents=True)
    scripts.mkdir(parents=True)
    site.mkdir(parents=True)
    python.write_bytes(b"MZ")
    exe = scripts / "asc.exe"
    exe.write_bytes(b"MZ")
    script = scripts / "asc-script.py"
    module = site / "__main__.py"
    module.write_text("print('module')\n", encoding="utf-8")
    return python, exe, script, module


def _prepare_windows_resolver(monkeypatch: pytest.MonkeyPatch, python: Path, path: Path):
    empty = path
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("PYTHONUSERBASE", raising=False)


def test_windows_local_python_roaming_scripts_schedule_asc_exe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    python, exe, script, module = _administrator_pip_layout(tmp_path)
    script.write_text(f"#!{python}\n", encoding="utf-8")
    empty = tmp_path / "empty-path"
    empty.mkdir()
    _prepare_windows_resolver(monkeypatch, python, empty)

    for argv in (str(exe), str(script)):
        monkeypatch.setattr(sys, "argv", [argv, "schedule", "install"])
        resolved = resolve_asc_executable()
        calls, command, arguments = _windows_task_action(monkeypatch, resolved)
        assert resolved == exe.resolve()
        assert len(calls) == 1
        assert command == str(exe.resolve())
        assert arguments == "schedule tick"
        assert not command.lower().endswith("python.exe")

    monkeypatch.setattr(sys, "argv", [str(exe).replace("/", "\\"), "schedule", "install"])
    assert resolve_asc_executable() == exe.resolve()

    spelled = str(python.resolve()).swapcase().replace("/", "\\")
    script.write_text(f'#!"{spelled}"\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(script).replace("/", "\\"), "schedule", "install"])
    assert resolve_asc_executable() == exe.resolve()

    script.write_text("#!python.exe\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(script), "schedule", "install"])
    assert resolve_asc_executable() == exe.resolve()

    monkeypatch.setattr(sys, "argv", [str(module), "schedule", "install"])
    monkeypatch.setenv("PATH", str(empty))
    assert resolve_asc_executable() == exe.resolve()


def test_windows_other_drive_shebang_does_not_require_same_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    python = tmp_path / "D" / "Tools" / "Python312" / "python.exe"
    scripts = (
        tmp_path
        / "C"
        / "Users"
        / "Administrator"
        / "AppData"
        / "Roaming"
        / "Python"
        / "Python312"
        / "Scripts"
    )
    python.parent.mkdir(parents=True)
    scripts.mkdir(parents=True)
    python.write_bytes(b"MZ")
    exe = scripts / "asc.exe"
    exe.write_bytes(b"MZ")
    script = scripts / "asc-script.py"
    empty = tmp_path / "empty-path"
    empty.mkdir()
    _prepare_windows_resolver(monkeypatch, python, empty)
    assert "Programs" not in python.parts
    assert script.parent not in python.parents
    assert python.parent not in script.parents

    monkeypatch.setattr(sys, "argv", [str(exe).replace("/", "\\"), "schedule", "install"])
    assert resolve_asc_executable() == exe.resolve()

    spelled = str(python.resolve()).swapcase().replace("/", "\\")
    script.write_text(f'#!"{spelled}"\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(script).replace("/", "\\"), "schedule", "install"])
    resolved = resolve_asc_executable()
    calls, command, arguments = _windows_task_action(monkeypatch, resolved)
    assert resolved == exe.resolve()
    assert len(calls) == 1
    assert command == str(exe.resolve())
    assert arguments == "schedule tick"

    script.write_text("#!python.exe\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(script), "schedule", "install"])
    assert resolve_asc_executable() == exe.resolve()
    monkeypatch.setattr(sys, "argv", [str(scripts / "asc"), "schedule", "install"])
    assert resolve_asc_executable() == exe.resolve()


def test_windows_user_install_finds_roaming_asc_exe_without_schtasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """python.org --user: Local python.exe, Roaming site-packages, Roaming Scripts."""
    python, exe, script, module = _administrator_pip_layout(tmp_path)
    package = module.parent
    init = package / "__init__.py"
    init.write_text('__version__ = "0.1.31"\n', encoding="utf-8")
    script.write_text("#!Z:\\\\not\\\\the\\\\running\\\\python.exe\n", encoding="utf-8")
    empty = tmp_path / "empty-path"
    empty.mkdir()
    _prepare_windows_resolver(monkeypatch, python, empty)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("schtasks must not be called")

    monkeypatch.setattr("asc.schedule.subprocess.run", fail_run)
    assert [part.lower() for part in python.parts[-5:]] == [
        "local",
        "programs",
        "python",
        "python312",
        "python.exe",
    ]
    assert [part.lower() for part in exe.parts[-5:]] == [
        "roaming",
        "python",
        "python312",
        "scripts",
        "asc.exe",
    ]
    assert [part.lower() for part in module.parts[-4:]] == [
        "python312",
        "site-packages",
        "asc",
        "__main__.py",
    ]
    assert python.parent not in exe.parents
    assert exe.parent.parent == package.parent.parent

    for argv in (script, exe, module):
        monkeypatch.setattr(sys, "argv", [str(argv).replace("/", "\\"), "schedule", "install"])
        resolved = resolve_asc_executable()
        xml = render_windows_task_xml(resolved, "Administrator")
        assert resolved == exe.resolve()
        assert f"<Command>{resolved}</Command>" in xml
        assert "<Arguments>schedule tick</Arguments>" in xml
        assert not str(resolved).lower().endswith("python.exe")

    import asc

    monkeypatch.setattr(asc, "__file__", str(init))
    unrelated = tmp_path / "Temp" / "run.py"
    unrelated.parent.mkdir()
    unrelated.write_text("print('run')\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(unrelated).replace("/", "\\"), "schedule", "install"])
    assert resolve_asc_executable() == exe.resolve()

    exe.unlink()
    monkeypatch.setattr(sys, "argv", [str(module).replace("/", "\\"), "schedule", "install"])
    with pytest.raises(ScheduleError) as exc:
        resolve_asc_executable()
    assert exc.value.code == "not_executable"
