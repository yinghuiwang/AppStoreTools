# App Store Connect Tools — Windows installer.
# Run in the current process. Do not Set-ExecutionPolicy.
# Download this branch as UTF-8, then Invoke-Expression. Do not pipe irm to iex.
# Default (no ASC_INSTALL_BRANCH) installs the PyPI package asc-appstore-tools.
# The script URL stays on this branch because Python auto-install is not on main:
#   $wc = New-Object System.Net.WebClient
#   $wc.Encoding = [System.Text.Encoding]::UTF8
#   Invoke-Expression $wc.DownloadString('https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/feat/windows-compat/install.ps1')
# This branch (script + CLI). Set ASC_INSTALL_BRANCH; it is not forwarded as an argument:
#   $env:ASC_INSTALL_BRANCH='feat/windows-compat'
#   $wc = New-Object System.Net.WebClient
#   $wc.Encoding = [System.Text.Encoding]::UTF8
#   Invoke-Expression $wc.DownloadString('https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/feat/windows-compat/install.ps1')
# Local editable install from a cloned repo root:
#   $env:ASC_INSTALL_BRANCH='local'
#   $wc = New-Object System.Net.WebClient
#   $wc.Encoding = [System.Text.Encoding]::UTF8
#   Invoke-Expression $wc.DownloadString('https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/feat/windows-compat/install.ps1')
# File execution also accepts a positional branch, -Branch, or --branch.
# The Microsoft Store python/python3 alias is treated as not installed.
# Usable Python does not require py.exe. Prefer a real py.exe, then python.exe
# from the registry and usual directories. Skip Microsoft\WindowsApps stubs.
# Run that absolute path for pip and asc. Search before winget or the official installer.
# Missing or older than 3.9: install Python 3.12 with winget, then the official installer.
# Exit 1638 / 0x666 and winget -1978335189 / 0x8A15002B mean the product is already installed.
# This script does not install Xcode, signing tools, or altool, and it does not create scheduled tasks.

$ascSavedExit = $global:LASTEXITCODE
try { chcp 65001 | Out-Null } catch { }
$global:LASTEXITCODE = $ascSavedExit
try {
    $OutputEncoding = New-Object System.Text.UTF8Encoding $false
    [Console]::OutputEncoding = $OutputEncoding
} catch { }

$ascSavedEap = $ErrorActionPreference
$ErrorActionPreference = 'Stop'
$ascHadNative = $false
$ascSavedNative = $null
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $ascHadNative = $true
    $ascSavedNative = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
}
try {
    $script:ascSummaryShown = $false
    $script:ascFailed = ''
    $script:ascInstalled = @()
    $script:ascPyVer = ''
    $script:ascPipVer = ''
    $script:ascPath = ''
    $script:ascSourceLabel = 'PyPI'
    $script:ascBranch = ''
    $script:ascLocalRoot = ''
    $script:ascPyExe = ''
    $script:ascPyLog = New-Object System.Collections.Generic.List[string]
    $script:ascPyTail = ''
    $script:ascPySearchNotes = New-Object System.Collections.Generic.List[string]
    $script:ascPyAlreadyInstalled = $false
    $script:ascPyFromExisting = $false

    function Write-AscOk([string]$Message) { Write-Host "[OK] $Message" -ForegroundColor Green }
    function Write-AscWarn([string]$Message) { Write-Host "[!] $Message" -ForegroundColor Yellow }
    function Write-AscErr([string]$Message) { Write-Host "[X] $Message" -ForegroundColor Red }

    function Show-AscSummary {
        if ($script:ascSummaryShown) { return }
        $script:ascSummaryShown = $true
        $installedText = '无'
        if ($script:ascInstalled.Count -gt 0) {
            $installedText = ($script:ascInstalled -join '、')
        }
        $failedText = '无'
        if (-not [string]::IsNullOrWhiteSpace($script:ascFailed)) {
            $failedText = $script:ascFailed
        }
        $pyText = $script:ascPyVer
        if ([string]::IsNullOrWhiteSpace($pyText)) { $pyText = '未知' }
        $pipText = $script:ascPipVer
        if ([string]::IsNullOrWhiteSpace($pipText)) { $pipText = '未知' }
        $ascText = $script:ascPath
        if ([string]::IsNullOrWhiteSpace($ascText)) { $ascText = '未找到' }
        Write-Host ""
        Write-Host "========== 安装摘要 =========="
        Write-Host "Python 版本: $pyText"
        Write-Host "pip 版本: $pipText"
        Write-Host "asc 路径: $ascText"
        Write-Host "安装来源: $($script:ascSourceLabel)"
        Write-Host "本次自动安装: $installedText"
        Write-Host "失败: $failedText"
        Write-Host "定时任务依赖任务计划程序，用户需保持登录。"
    }

    function Stop-AscInstall([string]$Message) {
        Write-AscErr $Message
        $script:ascFailed = $Message
        Show-AscSummary
        $global:LASTEXITCODE = 1
        if ($PSCommandPath) { exit 1 }
        throw $Message
    }

    function Show-AscHelp {
        Write-Host "App Store Connect Tools — Windows 安装程序"
        Write-Host ""
        Write-Host "默认安装 PyPI 包 asc-appstore-tools："
        Write-Host "  `$wc = New-Object System.Net.WebClient"
        Write-Host "  `$wc.Encoding = [System.Text.Encoding]::UTF8"
        Write-Host "  Invoke-Expression `$wc.DownloadString('https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/feat/windows-compat/install.ps1')"
        Write-Host ""
        Write-Host "安装 GitHub 分支（先设置环境变量，再按 UTF-8 下载该分支上的脚本）："
        Write-Host "  `$env:ASC_INSTALL_BRANCH='feat/windows-compat'"
        Write-Host "  `$wc = New-Object System.Net.WebClient"
        Write-Host "  `$wc.Encoding = [System.Text.Encoding]::UTF8"
        Write-Host "  Invoke-Expression `$wc.DownloadString('https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/feat/windows-compat/install.ps1')"
        Write-Host ""
        Write-Host "没有 Python 3.9+，或只有 Microsoft Store 占位程序时，脚本会自动安装 Python 3.12。"
        Write-Host "已经安装的 py.exe 或 python.exe（3.9 或更高，且不在 Microsoft\WindowsApps）会直接使用，不再重装。"
        Write-Host ""
        Write-Host "在已 clone 的仓库根目录安装本地源码："
        Write-Host "  `$env:ASC_INSTALL_BRANCH='local'"
        Write-Host "  `$wc = New-Object System.Net.WebClient"
        Write-Host "  `$wc.Encoding = [System.Text.Encoding]::UTF8"
        Write-Host "  Invoke-Expression `$wc.DownloadString('https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/feat/windows-compat/install.ps1')"
        Write-Host ""
        Write-Host "直接运行脚本时也可以传参（优先于环境变量）："
        Write-Host "  .\install.ps1"
        Write-Host "  .\install.ps1 feat/windows-compat"
        Write-Host "  .\install.ps1 -Branch local"
    }

    function Add-AscUserPath([string]$Dir) {
        if ([string]::IsNullOrWhiteSpace($Dir) -or -not (Test-Path -LiteralPath $Dir)) {
            Write-AscWarn "未找到目录，跳过 PATH：$Dir"
            return
        }
        $full = [System.IO.Path]::GetFullPath($Dir).TrimEnd('\')
        $key = $full.Replace('/', '\').TrimEnd('\').ToLowerInvariant()

        $inProc = $false
        foreach ($item in ($env:Path -split ';')) {
            if ([string]::IsNullOrWhiteSpace($item)) { continue }
            $itemKey = $item.Trim().Trim('"').Replace('/', '\').TrimEnd('\').ToLowerInvariant()
            if ($itemKey -eq $key) { $inProc = $true; break }
        }
        if (-not $inProc) {
            if ([string]::IsNullOrEmpty($env:Path)) { $env:Path = $full } else { $env:Path = "$full;$env:Path" }
            Write-AscOk "已加入当前进程 PATH: $full"
        }

        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        if ($null -eq $userPath) { $userPath = '' }
        $inUser = $false
        foreach ($item in ($userPath -split ';')) {
            if ([string]::IsNullOrWhiteSpace($item)) { continue }
            $itemKey = $item.Trim().Trim('"').Replace('/', '\').TrimEnd('\').ToLowerInvariant()
            if ($itemKey -eq $key) { $inUser = $true; break }
        }
        if (-not $inUser) {
            if ([string]::IsNullOrWhiteSpace($userPath)) { $newUser = $full } else { $newUser = "$full;$userPath" }
            [Environment]::SetEnvironmentVariable('Path', $newUser, 'User')
            Write-AscOk "已写入用户 PATH: $full"
        } else {
            Write-AscOk "用户 PATH 已包含: $full"
        }
    }

    function Update-AscProcessPath {
        $chunks = @(
            [Environment]::GetEnvironmentVariable('Path', 'User'),
            [Environment]::GetEnvironmentVariable('Path', 'Machine')
        )
        $parts = New-Object System.Collections.Generic.List[string]
        $seen = @{}
        foreach ($chunk in $chunks) {
            if ([string]::IsNullOrWhiteSpace($chunk)) { continue }
            foreach ($item in ($chunk -split ';')) {
                if ([string]::IsNullOrWhiteSpace($item)) { continue }
                $full = $item.Trim().Trim('"')
                $key = $full.Replace('/', '\').TrimEnd('\').ToLowerInvariant()
                if ($seen.ContainsKey($key)) { continue }
                $seen[$key] = $true
                $parts.Add($full)
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            $launcher = Join-Path $env:LOCALAPPDATA 'Programs\Python\Launcher'
            $pyExe = Join-Path $launcher 'py.exe'
            if (Test-Path -LiteralPath $pyExe) {
                $key = $launcher.Replace('/', '\').TrimEnd('\').ToLowerInvariant()
                if (-not $seen.ContainsKey($key)) {
                    $parts.Insert(0, $launcher)
                } else {
                    $kept = New-Object System.Collections.Generic.List[string]
                    $kept.Add($launcher)
                    foreach ($item in $parts) {
                        $itemKey = $item.Replace('/', '\').TrimEnd('\').ToLowerInvariant()
                        if ($itemKey -ne $key) { $kept.Add($item) }
                    }
                    $parts = $kept
                }
            }
        }
        if ($parts.Count -gt 0) {
            $env:Path = ($parts -join ';')
        }
        Write-AscOk "已按用户和系统环境变量刷新当前进程 PATH"
    }

    function Read-AscTagged([object]$Raw) {
        $map = @{}
        foreach ($line in @($Raw)) {
            $text = "$line".Trim()
            if ($text -match '^(ASC_[A-Z_]+) (.*)$') {
                $map[$Matches[1]] = $Matches[2].Trim()
            }
        }
        return $map
    }

    function Test-AscWindowsAppsPath([string]$Path) {
        if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
        return $Path.Replace('/', '\').ToLowerInvariant().Contains('\microsoft\windowsapps\')
    }

    function Test-AscStoreText([string]$Text) {
        if ([string]::IsNullOrWhiteSpace($Text)) { return $false }
        return (($Text -match 'Python was not found') -or ($Text -match 'Microsoft Store'))
    }

    function Get-AscTail([string]$Text, [int]$Count = 12) {
        if ([string]::IsNullOrWhiteSpace($Text)) { return '（无输出）' }
        $lines = @($Text -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if ($lines.Count -eq 0) { return '（无输出）' }
        if ($lines.Count -le $Count) { return ($lines -join "`n") }
        $start = $lines.Count - $Count
        return ($lines[$start..($lines.Count - 1)] -join "`n")
    }

    function Add-AscUniquePath([System.Collections.Generic.List[string]]$List, [string]$Path) {
        if ([string]::IsNullOrWhiteSpace($Path)) { return }
        $text = $Path.Trim().Trim('"')
        if (Test-AscWindowsAppsPath $text) { return }
        $key = $text.Replace('/', '\').TrimEnd('\').ToLowerInvariant()
        foreach ($item in $List) {
            $itemKey = $item.Replace('/', '\').TrimEnd('\').ToLowerInvariant()
            if ($itemKey -eq $key) { return }
        }
        $List.Add($text) | Out-Null
    }

    function Add-AscPyLog([string]$Message) {
        if ($null -eq $script:ascPyLog) {
            $script:ascPyLog = New-Object System.Collections.Generic.List[string]
        }
        $script:ascPyLog.Add($Message) | Out-Null
    }

    function ConvertTo-AscVersion([string]$Text) {
        if ([string]::IsNullOrWhiteSpace($Text)) { return -1 }
        $match = [regex]::Match($Text, '(\d+)\.(\d+)(?:\.(\d+))?')
        if (-not $match.Success) { return -1 }
        $micro = 0
        if ($match.Groups[3].Success -and -not [string]::IsNullOrWhiteSpace($match.Groups[3].Value)) {
            $micro = [int]$match.Groups[3].Value
        }
        return ([int]$match.Groups[1].Value * 1000000 + [int]$match.Groups[2].Value * 1000 + $micro)
    }

    function Invoke-AscCaptured {
        param(
            [Parameter(Mandatory = $true)][string]$Exe,
            [string[]]$ArgumentList,
            [switch]$Stream
        )
        if ($null -eq $ArgumentList) { $ArgumentList = @() }
        $lines = New-Object System.Collections.Generic.List[string]
        $saved = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $code = 1
        try {
            & $Exe @ArgumentList 2>&1 | ForEach-Object {
                $text = "$_"
                if ($Stream -and -not [string]::IsNullOrEmpty($text)) { Write-Host $text }
                if (-not [string]::IsNullOrEmpty($text)) { $lines.Add($text) | Out-Null }
            }
            if ($null -ne $LASTEXITCODE) { $code = $LASTEXITCODE }
        } catch {
            $lines.Add([string]$_.Exception.Message) | Out-Null
            $code = 1
        } finally {
            $ErrorActionPreference = $saved
        }
        $joined = [string]($lines -join "`n")
        return @{ ExitCode = $code; Text = $joined; Tail = (Get-AscTail $joined) }
    }

    function Get-AscWherePaths([string]$Name) {
        $list = New-Object System.Collections.Generic.List[string]
        $saved = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $code = 1
        $out = @()
        try {
            $out = @(& where.exe $Name 2>&1)
            $code = $LASTEXITCODE
        } catch {
            $code = 1
        } finally {
            $ErrorActionPreference = $saved
        }
        if ($code -eq 0) {
            foreach ($item in $out) {
                $text = "$item".Trim()
                if ([string]::IsNullOrWhiteSpace($text)) { continue }
                if ($text -match '(?i)^INFO:') { continue }
                if (Test-AscStoreText $text) { continue }
                Add-AscUniquePath $list $text
            }
        }
        $cmds = @(Get-Command $Name -All -ErrorAction SilentlyContinue)
        foreach ($cmd in $cmds) {
            if ($null -eq $cmd) { continue }
            $src = [string]$cmd.Source
            if ([string]::IsNullOrWhiteSpace($src)) { $src = [string]$cmd.Path }
            Add-AscUniquePath $list $src
        }
        return @($list.ToArray())
    }

    function Add-AscLauncherFromRegistry([System.Collections.Generic.List[string]]$List) {
        $keys = @(
            'HKCU:\Software\Python\Launcher',
            'HKLM:\Software\Python\Launcher',
            'HKCU:\Software\Python\PyLauncher',
            'HKLM:\Software\Python\PyLauncher',
            'HKLM:\SOFTWARE\WOW6432Node\Python\Launcher',
            'HKLM:\SOFTWARE\WOW6432Node\Python\PyLauncher'
        )
        foreach ($key in $keys) {
            if (-not (Test-Path -Path $key)) { continue }
            try {
                $regItem = Get-Item -Path $key -ErrorAction Stop
            } catch {
                continue
            }
            foreach ($valueName in @($regItem.GetValueNames())) {
                $raw = $regItem.GetValue($valueName)
                if ($null -eq $raw) { continue }
                $val = ([string]$raw).Trim().Trim('"')
                if ([string]::IsNullOrWhiteSpace($val)) { continue }
                try {
                    if ($val -match '(?i)(^|[\\/])py\.exe$') {
                        Add-AscUniquePath $List $val
                        continue
                    }
                    if ($val -match '^[A-Za-z]:\\' -or $val.StartsWith('\\')) {
                        $leaf = Join-Path $val 'py.exe'
                        if (Test-Path -LiteralPath $leaf -PathType Leaf) {
                            Add-AscUniquePath $List $leaf
                        }
                    }
                } catch {
                    continue
                }
            }
        }
    }

    function Test-AscAlreadyInstalledExit($Code) {
        if ($null -eq $Code) { return $false }
        $text = ("$Code").Trim()
        if ($text -match '^(?i)0x0*666$') { return $true }
        if ($text -match '^(?i)0x0*8[Aa]15002[Bb]$') { return $true }
        if ($text -eq '1638' -or $text -eq '-1978335189' -or $text -eq '2316632107') { return $true }
        return $false
    }

    function Add-AscPySearchNote([string]$Note) {
        if ($null -eq $script:ascPySearchNotes) {
            $script:ascPySearchNotes = New-Object System.Collections.Generic.List[string]
        }
        if ([string]::IsNullOrWhiteSpace($Note)) { return }
        foreach ($item in $script:ascPySearchNotes) {
            if ($item -eq $Note) { return }
        }
        $script:ascPySearchNotes.Add($Note) | Out-Null
    }

    function Add-AscClassifiedExe {
        param(
            [System.Collections.Generic.List[string]]$PyList,
            [System.Collections.Generic.List[string]]$PythonList,
            [string]$Path
        )
        if ([string]::IsNullOrWhiteSpace($Path)) { return }
        $leaf = [System.IO.Path]::GetFileName($Path.Trim().Trim('"'))
        if ($leaf -match '^(?i)py\.exe$') {
            Add-AscUniquePath $PyList $Path
        } else {
            Add-AscUniquePath $PythonList $Path
        }
    }

    function Add-AscGlobExe {
        param(
            [System.Collections.Generic.List[string]]$List,
            [string]$Pattern,
            [string]$Note
        )
        Add-AscPySearchNote $Note
        if ([string]::IsNullOrWhiteSpace($Pattern)) { return }
        if ($Pattern.Contains('*')) {
            $items = @()
            try {
                $items = @(Get-ChildItem -Path $Pattern -File -ErrorAction SilentlyContinue)
            } catch {
                $items = @()
            }
            foreach ($item in $items) {
                if ($null -eq $item) { continue }
                Add-AscUniquePath $List $item.FullName
            }
            return
        }
        Add-AscUniquePath $List $Pattern
    }

    function Add-AscRegistryPythonCore {
        param(
            [System.Collections.Generic.List[string]]$PyList,
            [System.Collections.Generic.List[string]]$PythonList,
            [string]$HiveName,
            [string]$ViewName,
            [string]$SubKey
        )
        $hive = [Microsoft.Win32.RegistryHive]::LocalMachine
        if ($HiveName -eq 'HKCU') { $hive = [Microsoft.Win32.RegistryHive]::CurrentUser }
        $view = [Microsoft.Win32.RegistryView]::Registry64
        if ($ViewName -eq '32') { $view = [Microsoft.Win32.RegistryView]::Registry32 }
        if ($ViewName -eq 'Default') { $view = [Microsoft.Win32.RegistryView]::Default }
        $base = $null
        $root = $null
        try {
            try {
                $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
            } catch {
                $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, [Microsoft.Win32.RegistryView]::Default)
            }
            $root = $base.OpenSubKey($SubKey)
            if ($null -eq $root) { return }
            foreach ($name in @($root.GetSubKeyNames())) {
                $install = $null
                try {
                    $install = $root.OpenSubKey(($name + '\InstallPath'))
                    if ($null -eq $install) { continue }
                    $exe = $install.GetValue('ExecutablePath')
                    if ($null -ne $exe -and -not [string]::IsNullOrWhiteSpace([string]$exe)) {
                        Add-AscClassifiedExe $PyList $PythonList (([string]$exe).Trim().Trim('"'))
                    }
                    $dir = $install.GetValue('')
                    if ($null -ne $dir -and -not [string]::IsNullOrWhiteSpace([string]$dir)) {
                        $pythonExe = Join-Path (([string]$dir).Trim().Trim('"').TrimEnd('\')) 'python.exe'
                        Add-AscClassifiedExe $PyList $PythonList $pythonExe
                    }
                } catch {
                    continue
                } finally {
                    if ($null -ne $install) { $install.Close() }
                }
            }
        } catch {
            return
        } finally {
            if ($null -ne $root) { $root.Close() }
            if ($null -ne $base) { $base.Close() }
        }
    }

    function Get-AscPyCandidates {
        $script:ascPySearchNotes = New-Object System.Collections.Generic.List[string]
        $pyList = New-Object System.Collections.Generic.List[string]
        $pythonList = New-Object System.Collections.Generic.List[string]

        Add-AscPySearchNote 'HKCU\Software\Python\PythonCore\*\InstallPath'
        Add-AscPySearchNote 'HKLM\Software\Python\PythonCore\*\InstallPath'
        Add-AscPySearchNote 'HKLM\Software\WOW6432Node\Python\PythonCore\*\InstallPath'
        Add-AscPySearchNote '注册表 ExecutablePath'
        Add-AscRegistryPythonCore $pyList $pythonList 'HKCU' 'Default' 'Software\Python\PythonCore'
        Add-AscRegistryPythonCore $pyList $pythonList 'HKLM' '64' 'Software\Python\PythonCore'
        Add-AscRegistryPythonCore $pyList $pythonList 'HKLM' '64' 'Software\WOW6432Node\Python\PythonCore'

        if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            $localRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
            Add-AscGlobExe $pythonList (Join-Path $localRoot 'Python*\python.exe') (Join-Path $localRoot 'Python*')
            Add-AscGlobExe $pyList (Join-Path $localRoot 'Launcher\py.exe') (Join-Path $localRoot 'Launcher')
        } else {
            Add-AscPySearchNote '%LOCALAPPDATA%\Programs\Python\Python*'
            Add-AscPySearchNote '%LOCALAPPDATA%\Programs\Python\Launcher'
        }

        Add-AscGlobExe $pythonList 'C:\Program Files\Python*\python.exe' 'C:\Program Files\Python*'
        Add-AscGlobExe $pythonList 'C:\Program Files (x86)\Python*\python.exe' 'C:\Program Files (x86)\Python*'
        if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
            $pfPattern = Join-Path $env:ProgramFiles 'Python*\python.exe'
            if ($pfPattern.Replace('/', '\').ToLowerInvariant() -ne 'c:\program files\python*\python.exe') {
                Add-AscGlobExe $pythonList $pfPattern (Join-Path $env:ProgramFiles 'Python*')
            }
        }
        if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
            $pf86Pattern = Join-Path ${env:ProgramFiles(x86)} 'Python*\python.exe'
            if ($pf86Pattern.Replace('/', '\').ToLowerInvariant() -ne 'c:\program files (x86)\python*\python.exe') {
                Add-AscGlobExe $pythonList $pf86Pattern (Join-Path ${env:ProgramFiles(x86)} 'Python*')
            }
        }

        $windowsPy = 'C:\Windows\py.exe'
        Add-AscGlobExe $pyList $windowsPy $windowsPy
        if (-not [string]::IsNullOrWhiteSpace($env:SystemRoot)) {
            $sysPy = Join-Path $env:SystemRoot 'py.exe'
            if ($sysPy.Replace('/', '\').TrimEnd('\').ToLowerInvariant() -ne 'c:\windows\py.exe') {
                Add-AscGlobExe $pyList $sysPy $sysPy
            }
        }

        Add-AscPySearchNote 'HKCU\Software\Python\Launcher'
        Add-AscPySearchNote 'HKLM\Software\Python\Launcher'
        Add-AscPySearchNote 'HKLM\Software\WOW6432Node\Python\Launcher'
        Add-AscLauncherFromRegistry $pyList

        Add-AscPySearchNote 'where.exe python'
        foreach ($path in @(Get-AscWherePaths 'python')) {
            Add-AscClassifiedExe $pyList $pythonList ([string]$path)
        }
        Add-AscPySearchNote 'where.exe py'
        foreach ($path in @(Get-AscWherePaths 'py')) {
            Add-AscClassifiedExe $pyList $pythonList ([string]$path)
        }

        $all = New-Object System.Collections.Generic.List[string]
        foreach ($item in $pyList) { Add-AscUniquePath $all $item }
        foreach ($item in $pythonList) { Add-AscUniquePath $all $item }
        return @($all.ToArray())
    }

    function Test-AscPyCandidate([string]$Exe) {
        if (Test-AscWindowsAppsPath $Exe) { return $null }
        if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { return $null }
        $full = ''
        try {
            $full = [System.IO.Path]::GetFullPath($Exe)
        } catch {
            return $null
        }
        if (Test-AscWindowsAppsPath $full) { return $null }
        $detectCode = 'import sys; print(sys.version_info); print("ASC_EXE " + sys.executable); print("ASC_VER %d.%d.%d" % sys.version_info[:3]); raise SystemExit(0 if sys.version_info >= (3, 9) else 2)'
        $ran = Invoke-AscCaptured -Exe $full -ArgumentList @('-c', $detectCode)
        if (Test-AscStoreText $ran.Text) { return $null }
        $lines = @([string]$ran.Text -split "`r?`n")
        $tags = Read-AscTagged $lines
        $reported = [string]$tags['ASC_EXE']
        $ver = [string]$tags['ASC_VER']
        if (Test-AscWindowsAppsPath $reported) { return $null }
        if ([string]::IsNullOrWhiteSpace($ver)) { return $null }
        $ok = ($ran.ExitCode -eq 0)
        return @{ Executable = $full; Version = $ver; Ok = [bool]$ok; ExitCode = $ran.ExitCode }
    }

    function Find-AscPy {
        $bestOk = $null
        $bestOkRank = -1
        $bestOkIsPy = $false
        $bestLow = $null
        $bestLowRank = -1
        foreach ($candidate in @(Get-AscPyCandidates)) {
            if ([string]::IsNullOrWhiteSpace([string]$candidate)) { continue }
            $tested = Test-AscPyCandidate ([string]$candidate)
            if ($null -eq $tested) { continue }
            $rank = ConvertTo-AscVersion ([string]$tested.Version)
            if ($rank -lt 0) { $rank = 0 }
            $isPy = ([System.IO.Path]::GetFileName([string]$tested.Executable) -match '^(?i)py\.exe$')
            if ($tested.Ok) {
                $better = $false
                if ($rank -gt $bestOkRank) { $better = $true }
                elseif ($rank -eq $bestOkRank -and $isPy -and -not $bestOkIsPy) { $better = $true }
                if ($better) {
                    $bestOk = $tested
                    $bestOkRank = $rank
                    $bestOkIsPy = [bool]$isPy
                }
            } elseif ($rank -gt $bestLowRank) {
                $bestLow = $tested
                $bestLowRank = $rank
            }
        }
        if ($null -ne $bestOk) { return $bestOk }
        return $bestLow
    }

    function Write-AscIgnoredStoreAliases {
        foreach ($name in @('python', 'python3', 'py')) {
            $saved = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            $code = 1
            $out = @()
            try {
                $out = @(& where.exe $name 2>&1)
                $code = $LASTEXITCODE
            } catch {
                $code = 1
            } finally {
                $ErrorActionPreference = $saved
            }
            if ($code -ne 0) { continue }
            foreach ($item in $out) {
                $text = "$item".Trim()
                if (Test-AscWindowsAppsPath $text) {
                    Write-AscWarn "检测到 Microsoft Store 占位程序，已忽略，不把它当成已安装的 ${name}：$text"
                }
            }
        }
    }

    function Test-AscElevated {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        return [bool]$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    }

    function Get-AscWingetPath {
        $cmd = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $cmd) { return $null }
        $src = [string]$cmd.Source
        if ([string]::IsNullOrWhiteSpace($src)) { $src = [string]$cmd.Path }
        if ([string]::IsNullOrWhiteSpace($src)) { return $null }
        $probe = Invoke-AscCaptured -Exe $src -ArgumentList @('--version')
        if (Test-AscStoreText $probe.Text) { return $null }
        if ($probe.ExitCode -ne 0) { return $null }
        if ($probe.Text -notmatch '\d+\.\d+') { return $null }
        return $src
    }

    function Add-AscPyLauncherPath([string]$PyExe) {
        if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            $known = Join-Path $env:LOCALAPPDATA 'Programs\Python\Launcher'
            if (Test-Path -LiteralPath (Join-Path $known 'py.exe')) {
                Add-AscUserPath $known
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($PyExe)) {
            if (Test-AscWindowsAppsPath $PyExe) { return }
            $dir = [string](Split-Path -Parent $PyExe)
            if ([string]::IsNullOrWhiteSpace($dir)) { return }
            if ($dir -match '(?i)\\(Python[0-9.]+|Launcher)$') {
                Add-AscUserPath $dir
            }
        }
    }

    function Install-AscWingetId {
        param(
            [Parameter(Mandatory = $true)][string]$Winget,
            [Parameter(Mandatory = $true)][string]$Id,
            [Parameter(Mandatory = $true)][string]$Scope
        )
        Write-Host "正在用 winget 安装 $Id（$Scope 范围）..."
        return Invoke-AscCaptured -Exe $Winget -ArgumentList @(
            'install', '-e', '--id', $Id, '--scope', $Scope,
            '--accept-package-agreements', '--accept-source-agreements',
            '--disable-interactivity', '--silent'
        ) -Stream
    }

    function Get-AscRecentPythonLogTail([datetime]$Since) {
        if ([string]::IsNullOrWhiteSpace($env:TEMP) -or -not (Test-Path -LiteralPath $env:TEMP)) {
            return ''
        }
        $files = @(Get-ChildItem -LiteralPath $env:TEMP -Filter '*.log' -ErrorAction SilentlyContinue | Where-Object {
            $_.Name -match 'python' -and $_.LastWriteTime -ge $Since.AddMinutes(-2)
        } | Sort-Object LastWriteTime -Descending)
        if ($files.Count -eq 0) { return '' }
        $raw = @(Get-Content -LiteralPath $files[0].FullName -Tail 12 -ErrorAction SilentlyContinue)
        if ($raw.Count -eq 0) { return '' }
        return ($raw -join "`n")
    }

    function Install-AscPythonExe([string]$Installer, [int]$AllUsers) {
        $since = Get-Date
        $argList = @(
            '/quiet',
            "InstallAllUsers=$AllUsers",
            'PrependPath=1',
            'Include_launcher=1',
            'Include_pip=1',
            'Include_test=0'
        )
        $saved = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $exit = 1
        $startError = ''
        try {
            $proc = Start-Process -FilePath $Installer -ArgumentList $argList -Wait -PassThru -WindowStyle Hidden -ErrorAction Stop
            if ($null -ne $proc -and $null -ne $proc.ExitCode) { $exit = $proc.ExitCode }
        } catch {
            $startError = [string]$_.Exception.Message
            $exit = 1
        } finally {
            $ErrorActionPreference = $saved
        }
        $tail = Get-AscRecentPythonLogTail $since
        if (-not [string]::IsNullOrWhiteSpace($startError)) {
            if ([string]::IsNullOrWhiteSpace($tail)) { $tail = $startError } else { $tail = $startError + "`n" + $tail }
        }
        if ([string]::IsNullOrWhiteSpace($tail)) { $tail = '（安装程序无控制台输出）' }
        return @{ ExitCode = $exit; Text = $tail; Tail = (Get-AscTail $tail) }
    }

    function Install-AscPythonOfficial {
        $fileName = 'python-3.12.7-amd64.exe'
        $url = 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe'
        $dest = Join-Path $env:TEMP $fileName
        $savedProgress = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        try {
            if (Test-Path -LiteralPath $dest) {
                Remove-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
            }
            try {
                [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            } catch {
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            }
            Write-Host "正在下载官方安装包 $url ..."
            $null = Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
            if (-not (Test-Path -LiteralPath $dest)) {
                Add-AscPyLog '下载官方安装包失败：文件不存在'
                $script:ascPyTail = '（无输出）'
                return $null
            }
            $length = (Get-Item -LiteralPath $dest).Length
            if ($length -lt 1000000) {
                Add-AscPyLog "下载官方安装包失败：文件只有 $length 字节"
                $script:ascPyTail = "文件大小 $length"
                return $null
            }
            Unblock-File -LiteralPath $dest -ErrorAction SilentlyContinue
            $elevated = Test-AscElevated
            Write-Host "正在静默安装 Python 3.12.7（InstallAllUsers=1）..."
            $first = Install-AscPythonExe $dest 1
            $firstNote = ''
            if ($first.ExitCode -eq 3010) { $firstNote = '（3010 通常表示已安装，可能需要重新登录）' }
            if (Test-AscAlreadyInstalledExit $first.ExitCode) {
                $script:ascPyAlreadyInstalled = $true
                $firstNote = '（1638 / 0x666 表示同一产品已经安装）'
            }
            Add-AscPyLog "官方安装包 $fileName InstallAllUsers=1 退出码 $($first.ExitCode)$firstNote"
            $script:ascPyTail = [string]$first.Tail
            Update-AscProcessPath
            Add-AscPyLauncherPath ''
            $found = Find-AscPy
            if ($found -and $found.Ok) {
                if (Test-AscAlreadyInstalledExit $first.ExitCode) { $script:ascPyFromExisting = $true }
                return $found
            }
            if (-not $elevated) {
                if (Test-AscAlreadyInstalledExit $first.ExitCode) {
                    Write-AscWarn "InstallAllUsers=1 退出码 $($first.ExitCode) 表示已经安装，但未找到 3.9 或更高的解释器。当前进程未提升，改为 InstallAllUsers=0。"
                } else {
                    Write-AscWarn "InstallAllUsers=1 未得到可用的 Python 3.9 或更高版本（退出码 $($first.ExitCode)）。当前进程未提升，改为 InstallAllUsers=0。"
                }
                Write-Host "正在静默安装 Python 3.12.7（InstallAllUsers=0）..."
                $second = Install-AscPythonExe $dest 0
                $secondNote = ''
                if ($second.ExitCode -eq 3010) { $secondNote = '（3010 通常表示已安装，可能需要重新登录）' }
                if (Test-AscAlreadyInstalledExit $second.ExitCode) {
                    $script:ascPyAlreadyInstalled = $true
                    $secondNote = '（1638 / 0x666 表示同一产品已经安装）'
                }
                Add-AscPyLog "官方安装包 $fileName InstallAllUsers=0 退出码 $($second.ExitCode)$secondNote"
                $script:ascPyTail = [string]$second.Tail
                if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
                    $launcher = Join-Path $env:LOCALAPPDATA 'Programs\Python\Launcher'
                    if (Test-Path -LiteralPath (Join-Path $launcher 'py.exe')) {
                        Add-AscUserPath $launcher
                    }
                }
                Update-AscProcessPath
                Add-AscPyLauncherPath ''
                $found = Find-AscPy
                if ($found -and $found.Ok) {
                    if (Test-AscAlreadyInstalledExit $second.ExitCode) { $script:ascPyFromExisting = $true }
                    return $found
                }
            }
            if ($found -and -not [string]::IsNullOrWhiteSpace([string]$found.Version)) {
                Add-AscPyLog "官方安装包结束后解释器仍是 $($found.Version)，低于 3.9"
            } else {
                Add-AscPyLog '官方安装包结束后仍未找到可用的 python.exe 或 py.exe'
            }
            return $null
        } catch {
            Add-AscPyLog "官方安装包失败：$($_.Exception.Message)"
            $script:ascPyTail = Get-AscTail ([string]$_.Exception.Message)
            return $null
        } finally {
            $ProgressPreference = $savedProgress
            if (-not [string]::IsNullOrWhiteSpace($dest)) {
                Remove-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
            }
        }
    }

    function Stop-AscPythonMissing {
        $tried = '无'
        if ($null -ne $script:ascPyLog -and $script:ascPyLog.Count -gt 0) {
            $tried = ($script:ascPyLog -join '；')
        }
        $tail = [string]$script:ascPyTail
        if ([string]::IsNullOrWhiteSpace($tail)) { $tail = '（无输出）' }
        $extra = ''
        if (-not [string]::IsNullOrWhiteSpace($env:PY_PYTHON)) {
            $extra = " 当前 PY_PYTHON=$($env:PY_PYTHON)。若它指向旧版本，请改为 3.12 或删除后再运行。"
        }
        $searched = '无'
        if ($null -ne $script:ascPySearchNotes -and $script:ascPySearchNotes.Count -gt 0) {
            $searched = ($script:ascPySearchNotes -join '；')
        }
        if ($script:ascPyAlreadyInstalled) {
            Stop-AscInstall ("Python 已经安装，但没有找到 3.9 或更高版本的解释器（已忽略 Microsoft\WindowsApps）。已搜索：$searched。已尝试：$tried。$extra`n最后输出：`n$tail")
        }
        Stop-AscInstall ("未能安装可用的 Python 3.9 或更高版本（需要 python.exe 或 py.exe 能运行，且不在 Microsoft\WindowsApps）。已搜索：$searched。已尝试：$tried。$extra`n最后输出：`n$tail")
    }

    function Install-AscPython312 {
        $script:ascPyLog = New-Object System.Collections.Generic.List[string]
        $script:ascPyTail = '（无输出）'
        $script:ascPyFromExisting = $false
        $winget = Get-AscWingetPath
        $elevated = Test-AscElevated
        if ($winget) {
            $userResult = Install-AscWingetId -Winget $winget -Id 'Python.Python.3.12' -Scope 'user'
            $alreadyUser = Test-AscAlreadyInstalledExit $userResult.ExitCode
            if ($alreadyUser) { $script:ascPyAlreadyInstalled = $true }
            Add-AscPyLog "winget Python.Python.3.12 --scope user 退出码 $($userResult.ExitCode)"
            if ($alreadyUser) {
                Add-AscPyLog "winget 用户范围退出码 $($userResult.ExitCode) 视为已经安装（-1978335189 / 0x8A15002B，或 1638 / 0x666）"
            }
            $script:ascPyTail = [string]$userResult.Tail
            Update-AscProcessPath
            Add-AscPyLauncherPath ''
            $found = Find-AscPy
            if ($found -and $found.Ok) {
                Add-AscPyLauncherPath ([string]$found.Executable)
                if ($userResult.ExitCode -eq 0) {
                    $script:ascInstalled += 'Python 3.12'
                    Write-AscOk "已安装 Python $($found.Version)（winget 用户范围）"
                } elseif ($alreadyUser) {
                    $script:ascPyFromExisting = $true
                    Write-AscWarn "winget 用户范围退出码 $($userResult.ExitCode) 表示已经安装。找到 Python $($found.Version)：$($found.Executable)。继续安装命令行工具。"
                } else {
                    Write-AscWarn "winget 用户范围退出码为 $($userResult.ExitCode)。已找到 Python $($found.Version)：$($found.Executable)，继续安装。"
                }
                return $found
            }
            if ($elevated) {
                if ($alreadyUser) {
                    Write-AscWarn "winget 用户范围表示 Python 已经安装，但还没有找到 3.9 或更高的解释器。当前进程已提升，改为机器范围后再搜索。"
                } else {
                    Write-AscWarn "用户范围安装后仍没有可用的 Python 3.9 或更高版本。当前进程已提升，改为机器范围。"
                }
                $machineResult = Install-AscWingetId -Winget $winget -Id 'Python.Python.3.12' -Scope 'machine'
                $alreadyMachine = Test-AscAlreadyInstalledExit $machineResult.ExitCode
                if ($alreadyMachine) { $script:ascPyAlreadyInstalled = $true }
                Add-AscPyLog "winget Python.Python.3.12 --scope machine 退出码 $($machineResult.ExitCode)"
                if ($alreadyMachine) {
                    Add-AscPyLog "winget 机器范围退出码 $($machineResult.ExitCode) 视为已经安装（-1978335189 / 0x8A15002B，或 1638 / 0x666）"
                }
                $script:ascPyTail = [string]$machineResult.Tail
                Update-AscProcessPath
                Add-AscPyLauncherPath ''
                $found = Find-AscPy
                if ($found -and $found.Ok) {
                    Add-AscPyLauncherPath ([string]$found.Executable)
                    if ($machineResult.ExitCode -eq 0) {
                        $script:ascInstalled += 'Python 3.12'
                        Write-AscOk "已安装 Python $($found.Version)（winget 机器范围）"
                    } elseif ($alreadyMachine) {
                        $script:ascPyFromExisting = $true
                        Write-AscWarn "winget 机器范围退出码 $($machineResult.ExitCode) 表示已经安装。找到 Python $($found.Version)：$($found.Executable)。继续安装命令行工具。"
                    } else {
                        Write-AscWarn "winget 机器范围退出码为 $($machineResult.ExitCode)。已找到 Python $($found.Version)：$($found.Executable)，继续安装。"
                    }
                    return $found
                }
            } else {
                Add-AscPyLog '当前进程未提升，跳过 winget --scope machine'
            }
            Write-AscWarn "winget 结束后仍没有可用的 Python 3.9 或更高版本。改为官方安装包。"
        } else {
            Add-AscPyLog 'winget 不可用'
            Write-AscWarn "未找到可用的 winget。改为下载官方 Python 3.12.7 安装包。"
        }
        $found = Install-AscPythonOfficial
        if ($found -and $found.Ok) {
            Add-AscPyLauncherPath ([string]$found.Executable)
            if ($script:ascPyFromExisting) {
                Write-AscWarn "安装包报告 Python 已经安装。找到 $($found.Version)：$($found.Executable)。继续安装命令行工具。"
            } else {
                $script:ascInstalled += 'Python 3.12.7'
                Write-AscOk "已安装 Python $($found.Version)（官方安装包）"
            }
            return $found
        }
        if ($found -and -not [string]::IsNullOrWhiteSpace([string]$found.Version)) {
            Add-AscPyLog "安装后解释器仍是 $($found.Version)，低于 3.9"
        }
        Stop-AscPythonMissing
    }

    function Resolve-AscPython {
        Write-AscIgnoredStoreAliases
        $found = Find-AscPy
        if ($found -and $found.Ok) {
            $script:ascPyExe = [string]$found.Executable
            Write-AscOk "已找到 Python $($found.Version)：$($found.Executable)。跳过安装。"
            return $found
        }
        if ($found -and -not [string]::IsNullOrWhiteSpace([string]$found.Version)) {
            Write-AscWarn "找到的 Python 为 $($found.Version)，低于 3.9。开始自动安装 Python 3.12。"
        } else {
            Write-AscWarn "未找到可用的 Python 3.9 或更高版本（已忽略 Microsoft Store 占位程序）。开始自动安装 Python 3.12。"
        }
        $installed = Install-AscPython312
        $script:ascPyExe = [string]$installed.Executable
        return $installed
    }

    function Find-AscGitExe {
        $list = New-Object System.Collections.Generic.List[string]
        $roots = @(
            $env:ProgramFiles,
            ${env:ProgramFiles(x86)},
            $(if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { Join-Path $env:LOCALAPPDATA 'Programs' })
        )
        foreach ($root in $roots) {
            if ([string]::IsNullOrWhiteSpace([string]$root)) { continue }
            Add-AscUniquePath $list (Join-Path ([string]$root) 'Git\cmd\git.exe')
        }
        foreach ($path in @(Get-AscWherePaths 'git')) {
            Add-AscUniquePath $list $path
        }
        foreach ($path in @($list.ToArray())) {
            if ([string]::IsNullOrWhiteSpace([string]$path)) { continue }
            if (-not (Test-Path -LiteralPath ([string]$path) -PathType Leaf)) { continue }
            $probe = Invoke-AscCaptured -Exe ([string]$path) -ArgumentList @('--version')
            if (Test-AscStoreText $probe.Text) { continue }
            if ($probe.ExitCode -eq 0 -and $probe.Text -match 'git version') {
                return [string]$path
            }
        }
        return $null
    }

    function Use-AscGitExe([string]$GitExe) {
        $dir = Split-Path -Parent $GitExe
        if ([string]::IsNullOrWhiteSpace($dir)) { return }
        $full = [System.IO.Path]::GetFullPath($dir).TrimEnd('\')
        $key = $full.Replace('/', '\').TrimEnd('\').ToLowerInvariant()
        foreach ($item in ($env:Path -split ';')) {
            if ([string]::IsNullOrWhiteSpace($item)) { continue }
            $itemKey = $item.Trim().Trim('"').Replace('/', '\').TrimEnd('\').ToLowerInvariant()
            if ($itemKey -eq $key) { return }
        }
        Add-AscUserPath $full
    }

    function Ensure-AscGit {
        $found = Find-AscGitExe
        if ($found) {
            Use-AscGitExe $found
            return
        }
        Write-AscWarn "安装 git 分支需要 Git，但未找到可用的 git。已忽略 Microsoft Store 占位，改为用 winget 安装 Git.Git。"
        $winget = Get-AscWingetPath
        if (-not $winget) {
            Stop-AscInstall "安装 git 分支需要 Git，但未找到 git，也没有可用的 winget。请安装 Git for Windows 后重新打开 PowerShell。不要使用 Microsoft Store。"
        }
        $scopeList = @('user')
        if (Test-AscElevated) { $scopeList += 'machine' }
        foreach ($scope in $scopeList) {
            $result = Install-AscWingetId -Winget $winget -Id 'Git.Git' -Scope $scope
            Update-AscProcessPath
            $found = Find-AscGitExe
            if ($found) {
                Use-AscGitExe $found
                $script:ascInstalled += 'Git'
                if ($result.ExitCode -eq 0) {
                    Write-AscOk "已安装 Git（winget $scope 范围）"
                } else {
                    Write-AscWarn "winget 安装 Git.Git 退出码为 $($result.ExitCode)。git 已可用，继续安装。"
                }
                return
            }
            if ($scope -eq 'user' -and $scopeList.Count -gt 1) {
                Write-AscWarn "用户范围安装后仍未找到 git.exe（退出码 $($result.ExitCode)）。当前进程已提升，改为机器范围。"
                continue
            }
            Stop-AscInstall "winget 安装 Git.Git 失败（--scope $scope，退出码 $($result.ExitCode)）。最后输出：$($result.Tail)"
        }
    }

    function Find-AscRepoRoot {
        $dirs = New-Object System.Collections.Generic.List[string]
        if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
            $dirs.Add($PSScriptRoot)
        }
        try {
            $dirs.Add((Get-Location).ProviderPath)
        } catch {
            $dirs.Add((Get-Location).Path)
        }
        $seen = @{}
        foreach ($dir in $dirs) {
            if ([string]::IsNullOrWhiteSpace($dir)) { continue }
            $full = [System.IO.Path]::GetFullPath($dir)
            $key = $full.TrimEnd('\').ToLowerInvariant()
            if ($seen.ContainsKey($key)) { continue }
            $seen[$key] = $true
            $toml = Join-Path $full 'pyproject.toml'
            if (-not (Test-Path -LiteralPath $toml)) { continue }
            $text = Get-Content -LiteralPath $toml -Raw -ErrorAction SilentlyContinue
            if ($text -and ($text -match '(?m)^\s*name\s*=\s*[''"]asc-appstore-tools[''"]\s*(#.*)?$')) {
                return $full
            }
        }
        return ''
    }

    if ($env:OS -ne 'Windows_NT') {
        Stop-AscInstall "install.ps1 只适用于 Windows。macOS / Linux 请使用 install.sh。"
    }

    $ascBranchArg = $null
    $ascWantHelp = $false
    if ($PSCommandPath) {
        $ascArgList = @($args)
        for ($i = 0; $i -lt $ascArgList.Count; $i++) {
            $token = [string]$ascArgList[$i]
            if ($token -eq '-h' -or $token -eq '--help' -or $token -eq '-?' -or $token -eq '/?') {
                $ascWantHelp = $true
                continue
            }
            if ($token -eq '-Branch' -or $token -eq '--branch') {
                if (($i + 1) -ge $ascArgList.Count) {
                    Stop-AscInstall "-Branch 需要分支名，或 local。"
                }
                $ascBranchArg = [string]$ascArgList[$i + 1]
                $i++
                continue
            }
            if ($token.StartsWith('-')) {
                Stop-AscInstall "未知参数：$token。可运行 .\install.ps1 --help。"
            }
            if ($null -ne $ascBranchArg) {
                Stop-AscInstall "多余参数：$token"
            }
            $ascBranchArg = $token
        }
    }
    if ($ascWantHelp) {
        Show-AscHelp
        if ($PSCommandPath) { exit 0 }
        return
    }

    if (-not [string]::IsNullOrWhiteSpace($ascBranchArg)) {
        $script:ascBranch = $ascBranchArg.Trim()
    } elseif (-not [string]::IsNullOrWhiteSpace($env:ASC_INSTALL_BRANCH)) {
        $script:ascBranch = $env:ASC_INSTALL_BRANCH.Trim()
    }

    if ([string]::IsNullOrWhiteSpace($script:ascBranch)) {
        $script:ascSourceLabel = 'PyPI'
    } elseif ($script:ascBranch -eq 'local') {
        $script:ascSourceLabel = 'local'
    } else {
        if ($script:ascBranch -notmatch '^[A-Za-z0-9_./-]+$') {
            Stop-AscInstall "分支名无效：$($script:ascBranch)。只允许字母、数字、下划线、点、斜杠和横线。"
        }
        $script:ascSourceLabel = "git 分支 $($script:ascBranch)"
    }

    if ($script:ascBranch -eq 'local') {
        $script:ascLocalRoot = [string](Find-AscRepoRoot)
        if ([string]::IsNullOrWhiteSpace($script:ascLocalRoot)) {
            Stop-AscInstall "已指定 local，但脚本所在目录和当前目录都没有 name 为 asc-appstore-tools 的 pyproject.toml。请先 cd 到仓库根目录再运行。"
        }
    } elseif (-not [string]::IsNullOrWhiteSpace($script:ascBranch)) {
        Ensure-AscGit
    }

    Write-Host "================================================"
    Write-Host "  App Store Connect Tools — 安装程序 (Windows)"
    Write-Host "================================================"
    Write-Host ""
    Write-Host "安装来源: $($script:ascSourceLabel)"
    Write-Host ""

    $ascPy = Resolve-AscPython
    $script:ascPyExe = [string]$ascPy.Executable
    if ([string]::IsNullOrWhiteSpace($script:ascPyExe) -or (Test-AscWindowsAppsPath $script:ascPyExe)) {
        Stop-AscInstall "Python 解释器路径无效。"
    }
    $script:ascPyVer = [string]$ascPy.Version
    Write-AscOk "Python: $($script:ascPyExe) ($($script:ascPyVer))"

    & $script:ascPyExe -m pip --version
    if ($LASTEXITCODE -ne 0) {
        Write-AscWarn "pip 不可用，尝试 ensurepip ..."
        & $script:ascPyExe -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) {
            Stop-AscInstall "ensurepip 失败，pip 仍不可用。请查看上方输出后重新运行本脚本。"
        }
        & $script:ascPyExe -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) {
            Stop-AscInstall "pip 升级失败。请查看上方输出后重新运行本脚本。"
        }
        $script:ascInstalled += 'pip'
    }
    $pipLine = & $script:ascPyExe -m pip --version
    if ($LASTEXITCODE -ne 0) {
        Stop-AscInstall "pip 安装后仍不可用。请查看上方输出后重新运行本脚本。"
    }
    $script:ascPipVer = ("$pipLine").Trim()
    Write-AscOk "pip: $($script:ascPipVer)"

    Write-Host ""
    if ([string]::IsNullOrWhiteSpace($script:ascBranch)) {
        Write-Host "正在从 PyPI 安装 asc-appstore-tools ..."
        & $script:ascPyExe -m pip install --user --upgrade asc-appstore-tools
        if ($LASTEXITCODE -ne 0) {
            Stop-AscInstall "pip 安装失败。请查看上方输出。"
        }
        $script:ascInstalled += 'asc-appstore-tools (PyPI)'
        Write-AscOk "asc-appstore-tools 安装成功（--user / PyPI）"
    } elseif ($script:ascBranch -eq 'local') {
        Write-Host "正在从本地仓库安装（editable）：$($script:ascLocalRoot)"
        Push-Location -LiteralPath $script:ascLocalRoot
        try {
            & $script:ascPyExe -m pip install --user -e .
            if ($LASTEXITCODE -ne 0) {
                Stop-AscInstall "本地 editable 安装失败。请查看上方 pip 输出。"
            }
        } finally {
            Pop-Location
        }
        $script:ascInstalled += 'asc-appstore-tools (local)'
        Write-AscOk "asc-appstore-tools 安装成功（--user -e / local）"
    } else {
        $ascGitUrl = "git+https://github.com/yinghuiwang/AppStoreTools.git@$($script:ascBranch)"
        Write-Host "正在从 GitHub 安装 $($script:ascBranch) ..."
        & $script:ascPyExe -m pip install --user --upgrade $ascGitUrl
        if ($LASTEXITCODE -ne 0) {
            Stop-AscInstall "GitHub 分支安装失败。请查看上方 pip 输出。"
        }
        $script:ascInstalled += "asc-appstore-tools (git $($script:ascBranch))"
        Write-AscOk "asc-appstore-tools 安装成功（--user / git 分支 $($script:ascBranch)）"
    }

    $ascScriptsRaw = & $script:ascPyExe -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user') or '')"
    $ascScripts = ''
    foreach ($ascScriptsLine in @($ascScriptsRaw)) {
        $ascScriptsText = "$ascScriptsLine".Trim()
        if (-not [string]::IsNullOrWhiteSpace($ascScriptsText)) { $ascScripts = $ascScriptsText }
    }
    Add-AscUserPath $ascScripts

    Write-Host ""
    $ascFails = New-Object System.Collections.Generic.List[string]

    Write-Host "验证: $($script:ascPyExe) -m asc --help"
    & $script:ascPyExe -m asc --help
    if ($LASTEXITCODE -eq 0) {
        Write-AscOk "$($script:ascPyExe) -m asc --help 通过"
    } else {
        Write-AscErr "$($script:ascPyExe) -m asc --help 失败"
        $ascFails.Add("$($script:ascPyExe) -m asc --help")
    }

    Write-Host ""
    $whereOut = & where.exe asc
    if ($LASTEXITCODE -eq 0) {
        $script:ascPath = [string](@($whereOut) | Select-Object -First 1)
        $script:ascPath = $script:ascPath.Trim()
        Write-AscOk "where.exe asc 通过: $($script:ascPath)"
    } else {
        Write-AscErr "where.exe asc 失败"
        $ascFails.Add('where.exe asc')
    }

    Write-Host ""
    $platformCode = @'
import asc
print("ASC_VERSION " + str(getattr(asc, "__version__", "unknown")))
try:
    import asc.platform as platform
except Exception:
    print("ASC_STATUS no-api")
    raise SystemExit(0)
print("ASC_PLATFORM " + str(platform.__file__))
if not (hasattr(platform, "feature_supported") and hasattr(platform, "cli_allows")):
    print("ASC_STATUS no-api")
    raise SystemExit(0)
build = bool(platform.feature_supported("build"))
schedule = bool(platform.cli_allows("schedule"))
release = bool(platform.cli_allows("release"))
print("ASC_BUILD " + ("True" if build else "False"))
print("ASC_SCHEDULE " + ("True" if schedule else "False"))
print("ASC_RELEASE " + ("True" if release else "False"))
print("ASC_STATUS ok")
'@
    $platformRaw = & $script:ascPyExe -c $platformCode
    $platformExit = $LASTEXITCODE
    $platformTags = Read-AscTagged $platformRaw
    $platformStatus = [string]$platformTags['ASC_STATUS']
    $enforceBranch = $false
    if ($script:ascBranch -eq 'feat/windows-compat') {
        $enforceBranch = $true
    } elseif ($script:ascBranch -eq 'local' -and $platformStatus -eq 'ok') {
        $enforceBranch = $true
    }

    if ($platformStatus -eq 'no-api') {
        if ($script:ascSourceLabel -eq 'PyPI') {
            Write-AscWarn "当前是 PyPI 发布版，没有 Windows 分支检查"
        } elseif ($script:ascBranch -eq 'feat/windows-compat') {
            Write-AscErr "feat/windows-compat 缺少 feature_supported / cli_allows"
            $ascFails.Add('Windows 分支检查')
        } else {
            Write-AscWarn "当前安装没有 feature_supported / cli_allows，跳过 Windows 分支期望"
        }
    } elseif ($platformStatus -eq 'ok') {
        $buildValue = [string]$platformTags['ASC_BUILD']
        $scheduleValue = [string]$platformTags['ASC_SCHEDULE']
        $releaseValue = [string]$platformTags['ASC_RELEASE']
        Write-Host "版本: $($platformTags['ASC_VERSION'])"
        Write-Host "platform.py: $($platformTags['ASC_PLATFORM'])"
        Write-Host "feature_supported('build') = $buildValue"
        Write-Host "cli_allows('schedule') = $scheduleValue"
        Write-Host "cli_allows('release') = $releaseValue"
        $branchMatch = ($buildValue -eq 'False' -and $scheduleValue -eq 'True' -and $releaseValue -eq 'False')
        if ($enforceBranch) {
            if ($branchMatch) {
                Write-AscOk "Windows 分支检查通过（build False，schedule True，release False）"
            } else {
                Write-AscErr "Windows 分支检查失败：期望 build False、schedule True、release False"
                $ascFails.Add('Windows 分支检查')
            }
        } else {
            Write-AscOk "已打印平台检查结果（不把 Windows 分支期望当作失败）"
        }
    } else {
        Write-AscErr "无法导入 asc.platform（退出码 $platformExit）"
        $ascFails.Add('asc.platform')
    }

    if ($ascFails.Count -gt 0) {
        Stop-AscInstall ("验证失败：" + ($ascFails -join '；'))
    }

    Show-AscSummary
    Write-Host ""
    Write-Host "下一步：在项目目录运行  asc install"
} catch {
    $ascException = $_.Exception
    while ($null -ne $ascException) {
        if ($ascException.GetType().FullName -eq 'System.Management.Automation.ExitException') {
            throw
        }
        $ascException = $ascException.InnerException
    }
    if (-not $script:ascSummaryShown) {
        if ([string]::IsNullOrWhiteSpace($script:ascFailed)) {
            $script:ascFailed = $_.Exception.Message
        }
        Show-AscSummary
    }
    $global:LASTEXITCODE = 1
    if ($PSCommandPath) { exit 1 }
    throw
} finally {
    $ErrorActionPreference = $ascSavedEap
    if ($ascHadNative) {
        $PSNativeCommandUseErrorActionPreference = $ascSavedNative
    }
    foreach ($ascFn in @(
        'Write-AscOk', 'Write-AscWarn', 'Write-AscErr', 'Show-AscSummary', 'Stop-AscInstall', 'Show-AscHelp',
        'Add-AscUserPath', 'Update-AscProcessPath', 'Read-AscTagged', 'Test-AscWindowsAppsPath', 'Test-AscStoreText',
        'Get-AscTail', 'Add-AscUniquePath', 'Add-AscPyLog', 'ConvertTo-AscVersion', 'Invoke-AscCaptured',
        'Get-AscWherePaths', 'Add-AscLauncherFromRegistry', 'Test-AscAlreadyInstalledExit', 'Add-AscPySearchNote',
        'Add-AscClassifiedExe', 'Add-AscGlobExe', 'Add-AscRegistryPythonCore', 'Get-AscPyCandidates', 'Test-AscPyCandidate', 'Find-AscPy',
        'Write-AscIgnoredStoreAliases', 'Test-AscElevated', 'Get-AscWingetPath', 'Add-AscPyLauncherPath',
        'Install-AscWingetId', 'Get-AscRecentPythonLogTail', 'Install-AscPythonExe', 'Install-AscPythonOfficial',
        'Stop-AscPythonMissing', 'Install-AscPython312', 'Resolve-AscPython', 'Find-AscGitExe', 'Use-AscGitExe',
        'Ensure-AscGit', 'Find-AscRepoRoot'
    )) {
        Remove-Item -Path "Function:\$ascFn" -ErrorAction SilentlyContinue
    }
    foreach ($ascStateName in @('ascSummaryShown', 'ascFailed', 'ascInstalled', 'ascPyVer', 'ascPipVer', 'ascPath', 'ascSourceLabel', 'ascBranch', 'ascLocalRoot', 'ascPyExe', 'ascPyLog', 'ascPyTail', 'ascPySearchNotes', 'ascPyAlreadyInstalled', 'ascPyFromExisting')) {
        Remove-Variable -Name $ascStateName -Scope Script -ErrorAction SilentlyContinue
    }
}
