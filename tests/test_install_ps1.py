"""Static checks for the Windows install.ps1 Python repair flow."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "install.ps1"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _function_body(text: str, name: str) -> str:
    match = re.search(rf"(?m)^    function {re.escape(name)}\b", text)
    assert match, name
    rest = text[match.end():]
    nxt = re.search(r"(?m)^    function ", rest)
    body = rest[: nxt.start()] if nxt else rest
    return body


def test_install_ps1_keeps_unrelated_windows_behavior():
    text = _text()
    assert "ASC_INSTALL_BRANCH" in text
    assert "[System.Text.Encoding]::UTF8" in text
    assert "Microsoft\\WindowsApps" in text
    assert "跳过安装" in text
    assert "Include_launcher=1" in text
    assert "Include_pip=1" in text
    assert "PrependPath=1" in text


def test_install_ps1_repairs_broken_python_registration():
    text = _text()
    assert "python-3.12.7" not in text
    assert "https://www.python.org/ftp/python/$version/$fileName" in text
    assert "return '3.12.10'" in text
    for key in (
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ):
        assert key in text
    uninstall = _function_body(text, "Uninstall-AscWingetPythonUser")
    assert "--scope', 'user'" in uninstall
    assert "--disable-interactivity" in uninstall
    assert "--accept-source-agreements" in uninstall
    repair = _function_body(text, "Repair-AscUserPythonOnce")
    assert repair.index("Uninstall-AscWingetPythonUser") < repair.index("Install-AscWingetId")
    assert "ascPyRepairDone" in repair
    official = _function_body(text, "Install-AscPythonOfficial")
    assert official.index("Install-AscOfficialScope $dest $fileName 0") < official.index(
        "Install-AscOfficialScope $dest $fileName 1"
    )
    install = _function_body(text, "Install-AscPython312")
    stale = install.index("这是残留登记，先卸载再安装，不改用机器范围。")
    repair_at = install.index("Repair-AscUserPythonOnce", stale)
    machine_at = install.index("Install-AscPythonMachineOnce", repair_at)
    assert stale < repair_at < machine_at
    assert "winget 机器范围退出码 1603" in text
    assert "不再换更旧的安装包" in text
    missing = _function_body(text, "Stop-AscPythonMissing")
    assert "残留登记" in missing
    assert "已尝试卸载残留" in missing
    assert "最后安装包版本" in missing
    assert "Get-AscTail" not in missing
    assert "WiX" not in missing


def test_install_ps1_function_cleanup_matches_definitions():
    text = _text()
    defined = set(re.findall(r"(?m)^    function ([A-Za-z0-9-]+)", text))
    start = text.index("foreach ($ascFn")
    end = text.index("foreach ($ascStateName")
    removed = set(re.findall(r"'([A-Za-z0-9-]+)'", text[start:end]))
    assert defined == removed
