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


def _ps_single_quoted(literal: str) -> str:
    assert literal.startswith("'") and literal.endswith("'"), literal
    return literal[1:-1].replace("''", "'")


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
    assert "--silent" in uninstall
    assert "--accept-source-agreements" in uninstall
    assert "accept-package-agreements" not in uninstall
    assert "'-e'" in uninstall
    assert "Python.Python.3.12" in uninstall
    install_id = _function_body(text, "Install-AscWingetId")
    assert "--accept-package-agreements" in install_id
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
    assert "搜到的路径" in missing
    assert "第一层子目录" in missing
    assert r"%LOCALAPPDATA%\Programs\Python" in missing


def test_install_ps1_locates_python_after_successful_install():
    text = _text()
    search = _function_body(text, "Get-AscPyCandidates")
    assert r"Python312\python.exe" in search
    assert r"Launcher\py.exe" in search
    assert "Add-AscChildPythonExe $pyList $pythonList $localRoot 2 ''" in search
    assert "Add-AscPythonFromInstallLogs" in search
    assert search.index("Add-AscPythonFromInstallLogs") < search.index("where.exe python")
    assert "Add-AscUninstallPythonCandidates" in search
    assert "ExecutablePath" in search
    assert "InstallLocation" in _function_body(text, "Add-AscUninstallPythonCandidates")
    assert "InstallPath" in search
    assert "Add-AscGlobExe $pythonList" not in search
    logs = _function_body(text, "Add-AscPythonFromInstallLogs")
    assert "ascPyLogPath" in logs
    assert "Python 3.12*.log" in logs
    assert "TargetDir" in logs
    assert "InstallPath" in logs
    assert "安装目录" in logs
    patterns = [
        _ps_single_quoted(item)
        for item in re.findall(r"(?m)^            ('(?:''|[^'])*'),?$", logs)
    ]
    assert len(patterns) >= 5
    samples = {
        "Setting string variable 'TargetDir' to value 'C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python312\\'": r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312",
        "Variable: InstallPath = C:\\Program Files\\Python312\\": r"C:\Program Files\Python312",
        "Property(S): TARGETDIR = C:\\Program Files\\Python312\\": r"C:\Program Files\Python312",
        "安装目录: C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python312\\": r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312",
    }
    for line, expected in samples.items():
        found = []
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                found.append(match.group(1).rstrip("\\"))
        assert expected in found, (line, found, patterns)
    probe = _function_body(text, "Test-AscPyCandidate")
    assert "$info.FileName = $full" in probe
    assert "$info.WorkingDirectory = $work" in probe
    assert "Invoke-AscCaptured" not in probe
    assert "Microsoft Store" in probe
    assert "Python was not found" in probe
    finder = _function_body(text, "Find-AscPy")
    assert "$script:ascPyFoundPaths = New-Object" in finder
    assert "$script:ascPyRejections = New-Object" in finder
    assert finder.index("if (-not $tested.Ok)") < finder.index("$bestRank = $rank")
    assert re.findall(r"(?m)^\s*return\b.*", finder) == ["        return $best"]
    assert "Update-AscProcessPath" in _function_body(text, "Install-AscOfficialScope")
    scope = _function_body(text, "Install-AscOfficialScope")
    assert scope.index("Update-AscProcessPath") < scope.index("Find-AscPy")


def test_install_ps1_runs_platform_check_from_a_file():
    text = _text()
    marker = "$platformCode = @'"
    start = text.index(marker)
    close = text.index("\n'@", start)
    body = text[start + len(marker) + 1:close]
    assert body.startswith("import asc\n")
    assert "import asc.platform as platform" in body
    assert '__version__' in body
    assert 'feature_supported("build")' in body
    assert 'cli_allows("schedule")' in body
    assert 'cli_allows("release")' in body
    assert 'print("ASC_STATUS ok")' in body
    assert "$" not in body
    region = text[start:text.index("if ($ascFails.Count -gt 0)", start)]
    assert '@"' not in region
    assert "ascPyExe -c" not in region
    assert "python -c" not in region
    assert " -c " not in region
    assert "$env:TEMP" in region
    assert "asc-platform-check-" in region
    assert '.py"' in region
    assert "$script:ascPyExe" in region
    assert "RedirectStandardError = $true" in region
    assert "Remove-Item -LiteralPath $platformScript" in region
    assert "Get-AscTail" not in region
    assert "if ($platformExit -ne 0)" in region
    assert "Write-Host $platformErrText.TrimEnd" in region
    assert "$script:ascBranch -eq 'feat/windows-compat'" in region
    assert "$script:ascSourceLabel -eq 'PyPI'" in region
    assert "build False、schedule True、release False" in region


def test_install_ps1_function_cleanup_matches_definitions():
    text = _text()
    defined = set(re.findall(r"(?m)^    function ([A-Za-z0-9-]+)", text))
    start = text.index("foreach ($ascFn")
    end = text.index("foreach ($ascStateName")
    removed = set(re.findall(r"'([A-Za-z0-9-]+)'", text[start:end]))
    assert defined == removed
