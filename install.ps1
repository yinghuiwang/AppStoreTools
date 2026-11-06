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
# Usable Python does not require py.exe. Collect python.exe and py.exe, then use
# the highest 3.9+ version. py.exe is one candidate; a failed probe does not skip python.exe.
# Search the registry, uninstall InstallLocation, and usual directories after PATH refresh.
# Skip Microsoft\WindowsApps stubs. A PATH entry for Python\Launcher is not py.exe.
# Run that absolute path for pip and asc. Search before winget or the official installer.
# Missing or older than 3.9: install Python 3.12 with winget.
# If winget says it is already installed but no 3.9+ interpreter exists, that registration
# is broken: uninstall the user-scope package and install it again. Do not install an older exe.
# The official installer uses the version winget printed, or 3.12.10.
# Exit 1638 / 0x666 means the same or a newer product is already installed.
# winget -1978335189 / 0x8A15002B means no upgrade is available.
# Machine-scope exit 1603 goes back to the user-scope uninstall and reinstall.
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
    $script:ascPyRepairDone = $false
    $script:ascPyRepairInstalled = $false
    $script:ascPyRepairUserResult = $null
    $script:ascPyReportedVersion = ''
    $script:ascPyInstallerVersion = ''
    $script:ascPyLastExit = ''
    $script:ascPyLogPath = ''
    $script:ascPyStale = $false
    $script:ascPyUninstallTried = $false
    $script:ascPyOfficial1638 = $false
    $script:ascLauncherWarnShown = $false
    $script:ascPyFoundPaths = New-Object System.Collections.Generic.List[string]
    $script:ascPyRejections = New-Object System.Collections.Generic.List[string]

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
        if (-not $script:ascLauncherWarnShown -and -not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            $launcherDir = Join-Path $env:LOCALAPPDATA 'Programs\Python\Launcher'
            $launcherExe = Join-Path $launcherDir 'py.exe'
            $launcherKey = $launcherDir.Replace('/', '\').TrimEnd('\').ToLowerInvariant()
            $launcherListed = $false
            foreach ($item in ($env:Path -split ';')) {
                if ([string]::IsNullOrWhiteSpace($item)) { continue }
                $itemKey = $item.Trim().Trim('"').Replace('/', '\').TrimEnd('\').ToLowerInvariant()
                if ($itemKey -eq $launcherKey) { $launcherListed = $true; break }
            }
            if ($launcherListed -and -not (Test-Path -LiteralPath $launcherExe -PathType Leaf)) {
                $script:ascLauncherWarnShown = $true
                Write-AscWarn "PATH 含 $launcherDir，但这里没有 py.exe。目录在 PATH 里不代表解释器已安装。"
            }
        }
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

    function Test-AscExit1638($Code) {
        if ($null -eq $Code) { return $false }
        $text = ("$Code").Trim()
        if ($text -eq '1638') { return $true }
        if ($text -match '^(?i)0x0*666$') { return $true }
        return $false
    }

    function Test-AscResult1638($Result) {
        if ($null -eq $Result) { return $false }
        if (Test-AscExit1638 $Result.ExitCode) { return $true }
        return ([string]$Result.Text -match '(?i)(exit code:?\s*1638\b|0x0*666\b)')
    }

    function Test-AscResult1603($Result) {
        if ($null -eq $Result) { return $false }
        $text = ("$($Result.ExitCode)").Trim()
        if ($text -eq '1603' -or $text -match '^(?i)0x0*643$') { return $true }
        return ([string]$Result.Text -match '(?i)exit code:?\s*1603\b')
    }

    function Test-AscWingetNoUpgrade($Result) {
        if ($null -eq $Result) { return $false }
        $text = ("$($Result.ExitCode)").Trim()
        if ($text -match '^(?i)0x0*8[Aa]15002[Bb]$') { return $true }
        if ($text -eq '-1978335189' -or $text -eq '2316632107') { return $true }
        $body = [string]$Result.Text
        if ($body -match '(?i)already installed') { return $true }
        if ($body -match '(?i)No available upgrade') { return $true }
        return $false
    }

    function Test-AscUserInstallAllowsMachine($Result) {
        if ($null -eq $Result) { return $false }
        if (Test-AscWingetNoUpgrade $Result) { return $false }
        if (Test-AscResult1603 $Result) { return $false }
        if (Test-AscResult1638 $Result) { return $false }
        $code = "$($Result.ExitCode)".Trim()
        if ($code -eq '0' -or $code -eq '3010') { return $false }
        return $true
    }

    function Remember-AscWingetPythonVersion([string]$Text) {
        if ([string]::IsNullOrWhiteSpace($Text)) { return }
        $best = [string]$script:ascPyReportedVersion
        $bestRank = ConvertTo-AscVersion $best
        $found = [regex]::Matches($Text, '(?i)(?:\bVersion\s+|Python\s+)(\d+\.\d+\.\d+)\b')
        foreach ($item in $found) {
            $ver = [string]$item.Groups[1].Value
            if ($ver -notmatch '^\d+\.\d+\.\d+$') { continue }
            if ($ver -notmatch '^3\.(?:9|[1-9]\d)\.\d+$') { continue }
            $rank = ConvertTo-AscVersion $ver
            if ($rank -gt $bestRank) {
                $best = $ver
                $bestRank = $rank
                $script:ascPyReportedVersion = $ver
            }
        }
    }

    function Get-AscOfficialPythonVersion {
        $ver = [string]$script:ascPyReportedVersion
        if ($ver -match '^\d+\.\d+\.\d+$') { return $ver }
        return '3.12.10'
    }

    function Get-AscUninstallPythonEntries {
        $entries = New-Object System.Collections.Generic.List[object]
        $specs = @(
            @{ HiveName = 'HKCU'; ViewName = 'Default'; SubKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall' },
            @{ HiveName = 'HKLM'; ViewName = '64'; SubKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall' },
            @{ HiveName = 'HKLM'; ViewName = '64'; SubKey = 'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall' }
        )
        foreach ($spec in $specs) {
            $hive = [Microsoft.Win32.RegistryHive]::LocalMachine
            if ($spec.HiveName -eq 'HKCU') { $hive = [Microsoft.Win32.RegistryHive]::CurrentUser }
            $view = [Microsoft.Win32.RegistryView]::Registry64
            if ($spec.ViewName -eq 'Default') { $view = [Microsoft.Win32.RegistryView]::Default }
            $base = $null
            $root = $null
            try {
                try {
                    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
                } catch {
                    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, [Microsoft.Win32.RegistryView]::Default)
                }
                $root = $base.OpenSubKey([string]$spec.SubKey)
                if ($null -eq $root) { continue }
                foreach ($name in @($root.GetSubKeyNames())) {
                    $sub = $null
                    try {
                        $sub = $root.OpenSubKey($name)
                        if ($null -eq $sub) { continue }
                        $display = $sub.GetValue('DisplayName')
                        $displayText = ''
                        if ($null -ne $display) { $displayText = ([string]$display).Trim() }
                        if ($displayText -notmatch 'Python 3') { continue }
                        $locText = ''
                        $quietText = ''
                        $uninstallText = ''
                        $verText = ''
                        $loc = $sub.GetValue('InstallLocation')
                        $quiet = $sub.GetValue('QuietUninstallString')
                        $uninstall = $sub.GetValue('UninstallString')
                        $ver = $sub.GetValue('DisplayVersion')
                        if ($null -ne $loc) { $locText = ([string]$loc).Trim().Trim('"') }
                        if ($null -ne $quiet) { $quietText = ([string]$quiet).Trim() }
                        if ($null -ne $uninstall) { $uninstallText = ([string]$uninstall).Trim() }
                        if ($null -ne $ver) { $verText = ([string]$ver).Trim() }
                        $entries.Add(@{
                            Hive = [string]$spec.HiveName
                            DisplayName = $displayText
                            InstallLocation = $locText
                            QuietUninstallString = $quietText
                            UninstallString = $uninstallText
                            DisplayVersion = $verText
                        }) | Out-Null
                    } catch {
                        continue
                    } finally {
                        if ($null -ne $sub) { $sub.Close() }
                    }
                }
            } catch {
                continue
            } finally {
                if ($null -ne $root) { $root.Close() }
                if ($null -ne $base) { $base.Close() }
            }
        }
        return ,$entries
    }

    function Add-AscUninstallPythonCandidates {
        param(
            [System.Collections.Generic.List[string]]$PyList,
            [System.Collections.Generic.List[string]]$PythonList
        )
        Add-AscPySearchNote 'HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\*\InstallLocation'
        Add-AscPySearchNote 'HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\*\InstallLocation'
        Add-AscPySearchNote 'HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*\InstallLocation'
        $uninstallEntries = Get-AscUninstallPythonEntries
        foreach ($entry in $uninstallEntries) {
            $loc = [string]$entry.InstallLocation
            if ([string]::IsNullOrWhiteSpace($loc)) { continue }
            if ($loc -match '(?i)(^|[\\/])python\.exe$') {
                Add-AscClassifiedExe $PyList $PythonList $loc
                continue
            }
            Add-AscClassifiedExe $PyList $PythonList (Join-Path $loc.TrimEnd('\') 'python.exe')
        }
    }

    function Invoke-AscQuietUninstallCommand([string]$Command) {
        $trim = $Command.Trim()
        $exe = ''
        $arg = ''
        if ($trim.StartsWith('"')) {
            $end = $trim.IndexOf('"', 1)
            if ($end -gt 1) {
                $exe = $trim.Substring(1, $end - 1)
                $arg = $trim.Substring($end + 1).Trim()
            }
        }
        if ([string]::IsNullOrWhiteSpace($exe)) {
            $match = [regex]::Match($trim, '^(\S+)\s*(.*)$')
            if ($match.Success) {
                $exe = $match.Groups[1].Value
                $arg = $match.Groups[2].Value.Trim()
            }
        }
        if ([string]::IsNullOrWhiteSpace($exe)) {
            return @{ ExitCode = 1; Text = '无法解析卸载命令' }
        }
        if ($arg -notmatch '(?i)(/quiet|/qn|/qb|/passive|/s(\s|$)|--silent)') {
            if ($exe -match '(?i)msiexec(\.exe)?$') {
                $arg = ("$arg /quiet /norestart").Trim()
            } else {
                $arg = ("$arg /quiet").Trim()
            }
        }
        $saved = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $exit = 1
        $err = ''
        try {
            $info = New-Object System.Diagnostics.ProcessStartInfo
            $info.FileName = $exe
            $info.Arguments = $arg
            $info.UseShellExecute = $true
            $info.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
            $proc = New-Object System.Diagnostics.Process
            $proc.StartInfo = $info
            $null = $proc.Start()
            $proc.WaitForExit()
            if ($null -ne $proc.ExitCode) { $exit = $proc.ExitCode }
        } catch {
            $err = [string]$_.Exception.Message
            $exit = 1
        } finally {
            $ErrorActionPreference = $saved
        }
        return @{ ExitCode = $exit; Text = $err }
    }

    function Invoke-AscRegisteredPythonUninstall {
        $entries = Get-AscUninstallPythonEntries
        $chosen = $null
        foreach ($entry in $entries) {
            $name = [string]$entry.DisplayName
            $ver = [string]$entry.DisplayVersion
            $is312 = ($name -match 'Python 3\.12') -or ($ver -match '^3\.12')
            if (-not $is312) { continue }
            $cmd = [string]$entry.QuietUninstallString
            if ([string]::IsNullOrWhiteSpace($cmd)) { $cmd = [string]$entry.UninstallString }
            if ([string]::IsNullOrWhiteSpace($cmd)) { continue }
            if ($entry.Hive -eq 'HKCU') { $chosen = $entry; break }
            if ($null -eq $chosen) { $chosen = $entry }
        }
        if ($null -eq $chosen) {
            foreach ($entry in $entries) {
                $name = [string]$entry.DisplayName
                if ($name -notmatch '^Python 3') { continue }
                $cmd = [string]$entry.QuietUninstallString
                if ([string]::IsNullOrWhiteSpace($cmd)) { $cmd = [string]$entry.UninstallString }
                if ([string]::IsNullOrWhiteSpace($cmd)) { continue }
                $chosen = $entry
                break
            }
        }
        if ($null -eq $chosen) {
            Add-AscPyLog '卸载登记里没有可执行的 Python 3 卸载命令'
            return $null
        }
        $cmd = [string]$chosen.QuietUninstallString
        $which = 'QuietUninstallString'
        if ([string]::IsNullOrWhiteSpace($cmd)) {
            $cmd = [string]$chosen.UninstallString
            $which = 'UninstallString'
        }
        Write-Host "正在执行卸载登记中的静默卸载（$which）..."
        $ran = Invoke-AscQuietUninstallCommand $cmd
        Add-AscPyLog "卸载登记 $which 退出码 $($ran.ExitCode)"
        $script:ascPyLastExit = "$($ran.ExitCode)"
        return $ran
    }

    function Uninstall-AscWingetPythonUser([string]$Winget) {
        Write-Host "正在用 winget 卸载用户范围的 Python.Python.3.12 ..."
        return Invoke-AscCaptured -Exe $Winget -ArgumentList @(
            'uninstall', '-e', '--id', 'Python.Python.3.12', '--scope', 'user',
            '--accept-source-agreements', '--disable-interactivity', '--silent'
        ) -Stream
    }

    function Publish-AscInstalledPython($Found, [string]$How, $ExitCode, [bool]$Already) {
        Add-AscPyLauncherPath ([string]$Found.Executable)
        $codeText = "$ExitCode".Trim()
        if ($Already -or (Test-AscExit1638 $ExitCode) -or (Test-AscWingetNoUpgrade @{ ExitCode = $ExitCode; Text = '' })) {
            $script:ascPyFromExisting = $true
            Write-AscWarn "$How 之后找到 Python $($Found.Version)：$($Found.Executable)。继续安装命令行工具。"
            return $Found
        }
        if ($codeText -eq '0' -or $codeText -eq '3010') {
            $script:ascInstalled += 'Python 3.12'
            Write-AscOk "已安装 Python $($Found.Version)（$How）"
            return $Found
        }
        Write-AscWarn "$How 退出码为 $codeText。已找到 Python $($Found.Version)：$($Found.Executable)，继续安装。"
        return $Found
    }

    function Install-AscPythonMachineOnce([string]$Winget) {
        Write-Host "正在用 winget 安装 Python.Python.3.12（machine 范围）..."
        $machineResult = Install-AscWingetId -Winget $Winget -Id 'Python.Python.3.12' -Scope 'machine'
        Remember-AscWingetPythonVersion ([string]$machineResult.Text)
        $stale = Test-AscWingetNoUpgrade $machineResult
        $is1603 = Test-AscResult1603 $machineResult
        $is1638 = Test-AscResult1638 $machineResult
        if ($stale -or $is1638) {
            $script:ascPyAlreadyInstalled = $true
            $script:ascPyStale = $true
        }
        Add-AscPyLog "winget Python.Python.3.12 --scope machine 退出码 $($machineResult.ExitCode)"
        if ($is1603) {
            Add-AscPyLog 'winget 机器范围退出码 1603'
            $script:ascPyLastExit = '1603'
            if ($script:ascPyRepairDone) {
                Write-AscWarn "winget 机器范围退出码 1603。卸载再装已经做过一轮，不再重复，也不改用更旧的安装包。"
            } else {
                Write-AscWarn "winget 机器范围退出码 1603。不改用旧的官方安装包，回到用户范围卸载再装。"
            }
        } elseif ($is1638) {
            Add-AscPyLog 'winget 机器范围退出码 1638，不再换更旧的安装包'
            $script:ascPyLastExit = '1638'
        } else {
            $script:ascPyLastExit = "$($machineResult.ExitCode)"
        }
        Update-AscProcessPath
        Add-AscPyLauncherPath ''
        $found = Find-AscPy
        return @{
            Found = $found
            Result = $machineResult
            Is1603 = [bool]$is1603
            Is1638 = [bool]$is1638
            Stale = [bool]$stale
        }
    }

    function Repair-AscUserPythonOnce([string]$Winget) {
        if ($script:ascPyRepairDone) {
            Add-AscPyLog '卸载再装已经做过一轮，不再重复'
            return $null
        }
        $script:ascPyRepairDone = $true
        $script:ascPyUninstallTried = $true
        $script:ascPyRepairInstalled = $false
        if (-not [string]::IsNullOrWhiteSpace($Winget)) {
            $un = Uninstall-AscWingetPythonUser $Winget
            Add-AscPyLog "winget uninstall Python.Python.3.12 --scope user 退出码 $($un.ExitCode)"
            $script:ascPyLastExit = "$($un.ExitCode)"
            if ($un.ExitCode -ne 0) {
                Write-AscWarn "winget 卸载用户范围 Python 3.12 失败（退出码 $($un.ExitCode)）。改为执行卸载登记里的静默卸载。"
                $null = Invoke-AscRegisteredPythonUninstall
            }
        } else {
            $null = Invoke-AscRegisteredPythonUninstall
        }
        Update-AscProcessPath
        Add-AscPyLauncherPath ''
        $found = Find-AscPy
        if ($found -and $found.Ok) { return $found }
        if ([string]::IsNullOrWhiteSpace($Winget)) {
            Add-AscPyLog '卸载后仍没有解释器，且没有可用的 winget 可重新安装'
            return $null
        }
        Write-Host "卸载后仍没有 3.9 或更高的解释器，正在重新安装用户范围的 Python.Python.3.12 ..."
        $user = Install-AscWingetId -Winget $Winget -Id 'Python.Python.3.12' -Scope 'user'
        $script:ascPyRepairUserResult = $user
        Remember-AscWingetPythonVersion ([string]$user.Text)
        Add-AscPyLog "winget 重新安装 Python.Python.3.12 --scope user 退出码 $($user.ExitCode)"
        $script:ascPyLastExit = "$($user.ExitCode)"
        if (Test-AscResult1603 $user) {
            Add-AscPyLog 'winget 用户范围重新安装退出码 1603'
            $script:ascPyLastExit = '1603'
        }
        if (Test-AscResult1638 $user) {
            Add-AscPyLog 'winget 用户范围重新安装退出码 1638，不再换更旧的安装包'
            $script:ascPyAlreadyInstalled = $true
            $script:ascPyLastExit = '1638'
        }
        if (Test-AscWingetNoUpgrade $user) { $script:ascPyAlreadyInstalled = $true }
        Update-AscProcessPath
        Add-AscPyLauncherPath ''
        $found = Find-AscPy
        if ($found -and $found.Ok -and "$($user.ExitCode)".Trim() -eq '0') {
            $script:ascPyRepairInstalled = $true
        }
        if ($found -and $found.Ok) { return $found }
        return $null
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

    function Add-AscPresentExe {
        param(
            [System.Collections.Generic.List[string]]$PyList,
            [System.Collections.Generic.List[string]]$PythonList,
            [string]$Path
        )
        if ([string]::IsNullOrWhiteSpace($Path)) { return }
        $text = $Path.Trim().Trim('"')
        if (Test-AscWindowsAppsPath $text) { return }
        if (-not (Test-Path -LiteralPath $text -PathType Leaf)) { return }
        try {
            $text = [System.IO.Path]::GetFullPath($text)
        } catch {
            return
        }
        if (Test-AscWindowsAppsPath $text) { return }
        Add-AscClassifiedExe $PyList $PythonList $text
    }

    function Add-AscChildPythonExe {
        param(
            [System.Collections.Generic.List[string]]$PyList,
            [System.Collections.Generic.List[string]]$PythonList,
            [string]$Root,
            [int]$Depth,
            [string]$NamePattern
        )
        if ($Depth -lt 1 -or [string]::IsNullOrWhiteSpace($Root)) { return }
        if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return }
        $dirs = @()
        try {
            $dirs = @(Get-ChildItem -LiteralPath $Root -Force -Directory -ErrorAction SilentlyContinue)
        } catch {
            return
        }
        foreach ($dir in $dirs) {
            if ($null -eq $dir) { continue }
            if (-not [string]::IsNullOrWhiteSpace($NamePattern) -and $dir.Name -notmatch $NamePattern) { continue }
            Add-AscPresentExe $PyList $PythonList (Join-Path $dir.FullName 'python.exe')
            if ($Depth -ge 2) {
                Add-AscChildPythonExe $PyList $PythonList $dir.FullName ($Depth - 1) ''
            }
        }
    }

    function Add-AscPythonFromInstallLogs {
        param(
            [System.Collections.Generic.List[string]]$PyList,
            [System.Collections.Generic.List[string]]$PythonList
        )
        $logs = New-Object System.Collections.Generic.List[string]
        if (-not [string]::IsNullOrWhiteSpace([string]$script:ascPyLogPath)) {
            Add-AscUniquePath $logs ([string]$script:ascPyLogPath)
        }
        if (-not [string]::IsNullOrWhiteSpace($env:TEMP) -and (Test-Path -LiteralPath $env:TEMP -PathType Container)) {
            try {
                $foundLogs = @(Get-ChildItem -LiteralPath $env:TEMP -Filter 'Python 3.12*.log' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
                if ($foundLogs.Count -gt 0) {
                    Add-AscUniquePath $logs ([string]$foundLogs[0].FullName)
                    if ([string]::IsNullOrWhiteSpace([string]$script:ascPyLogPath)) {
                        $script:ascPyLogPath = [string]$foundLogs[0].FullName
                    }
                }
            } catch { }
        }
        $patterns = @(
            '(?i)Setting string variable ''TargetDir'' to value ''([^'']+)''',
            '(?i)Setting string variable ''InstallPath'' to value ''([^'']+)''',
            '(?i)TargetDir\s*=\s*[''"]?([A-Za-z]:\\[^''"\r\n]+)',
            '(?i)InstallPath\s*=\s*[''"]?([A-Za-z]:\\[^''"\r\n]+)',
            '安装目录\s*[=:：]\s*[''"]?([A-Za-z]:\\[^''"\r\n]+)'
        )
        foreach ($log in $logs) {
            if ([string]::IsNullOrWhiteSpace([string]$log)) { continue }
            if (-not (Test-Path -LiteralPath ([string]$log) -PathType Leaf)) { continue }
            $text = ''
            try {
                $bytes = [System.IO.File]::ReadAllBytes([string]$log)
                if ($bytes.Length -gt 33554432) { continue }
                if ($bytes.Length -ge 2 -and $bytes[0] -eq 255 -and $bytes[1] -eq 254) {
                    $text = [System.Text.Encoding]::Unicode.GetString($bytes)
                } else {
                    $utf8 = New-Object System.Text.UTF8Encoding $false
                    $text = $utf8.GetString($bytes)
                    if ($text -notmatch '(?i)TargetDir|InstallPath|安装目录' -and $text.Contains([char]0)) {
                        $text = [System.Text.Encoding]::Unicode.GetString($bytes)
                    }
                }
            } catch {
                continue
            }
            if ([string]::IsNullOrWhiteSpace($text)) { continue }
            foreach ($pattern in $patterns) {
                $logMatches = @()
                try {
                    $logMatches = @([regex]::Matches($text, $pattern))
                } catch {
                    continue
                }
                foreach ($item in $logMatches) {
                    if ($null -eq $item -or $item.Groups.Count -lt 2) { continue }
                    $raw = [string]$item.Groups[1].Value
                    $raw = $raw.Trim().Trim('"').Trim("'").Trim()
                    if ([string]::IsNullOrWhiteSpace($raw)) { continue }
                    $exe = $raw
                    if ($raw -notmatch '(?i)(^|[\\/])python\.exe$') {
                        try {
                            $exe = Join-Path $raw.TrimEnd('\', '/') 'python.exe'
                        } catch {
                            continue
                        }
                    }
                    Add-AscPresentExe $PyList $PythonList $exe
                }
            }
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
            Add-AscPySearchNote (Join-Path $localRoot 'Python312\python.exe')
            Add-AscPySearchNote (Join-Path $localRoot '*\python.exe')
            Add-AscPySearchNote (Join-Path $localRoot '*\*\python.exe')
            Add-AscPySearchNote (Join-Path $localRoot 'Launcher\py.exe')
            Add-AscPresentExe $pyList $pythonList (Join-Path $localRoot 'Python312\python.exe')
            Add-AscPresentExe $pyList $pythonList (Join-Path $localRoot 'Launcher\py.exe')
            Add-AscChildPythonExe $pyList $pythonList $localRoot 2 ''
        } else {
            Add-AscPySearchNote '%LOCALAPPDATA%\Programs\Python\Python312\python.exe'
            Add-AscPySearchNote '%LOCALAPPDATA%\Programs\Python\*\python.exe'
            Add-AscPySearchNote '%LOCALAPPDATA%\Programs\Python\*\*\python.exe'
            Add-AscPySearchNote '%LOCALAPPDATA%\Programs\Python\Launcher\py.exe'
        }

        $programRoots = New-Object System.Collections.Generic.List[string]
        Add-AscUniquePath $programRoots 'C:\Program Files'
        Add-AscUniquePath $programRoots 'C:\Program Files (x86)'
        if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
            Add-AscUniquePath $programRoots $env:ProgramFiles
        }
        if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
            Add-AscUniquePath $programRoots ${env:ProgramFiles(x86)}
        }
        foreach ($programRoot in $programRoots) {
            Add-AscPySearchNote (Join-Path $programRoot 'Python312\python.exe')
            Add-AscPySearchNote (Join-Path $programRoot 'Python*\python.exe')
            Add-AscPresentExe $pyList $pythonList (Join-Path $programRoot 'Python312\python.exe')
            Add-AscChildPythonExe $pyList $pythonList $programRoot 1 '^(?i)Python'
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
        Add-AscUninstallPythonCandidates $pyList $pythonList

        $havePython = $false
        foreach ($item in $pythonList) {
            if ([string]::IsNullOrWhiteSpace([string]$item)) { continue }
            if (Test-Path -LiteralPath ([string]$item) -PathType Leaf) {
                $havePython = $true
                break
            }
        }
        if (-not $havePython) {
            try {
                Add-AscPythonFromInstallLogs $pyList $pythonList
            } catch {
                # 日志解析失败不是安装失败。
            }
        }

        Add-AscPySearchNote 'where.exe python'
        foreach ($path in @(Get-AscWherePaths 'python')) {
            Add-AscClassifiedExe $pyList $pythonList ([string]$path)
        }
        Add-AscPySearchNote 'where.exe py'
        foreach ($path in @(Get-AscWherePaths 'py')) {
            Add-AscClassifiedExe $pyList $pythonList ([string]$path)
        }

        $all = New-Object System.Collections.Generic.List[string]
        foreach ($item in $pythonList) { Add-AscUniquePath $all $item }
        foreach ($item in $pyList) { Add-AscUniquePath $all $item }
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
        $detectCode = "import sys; print('ASC_EXE ' + sys.executable); print('ASC_VER %d.%d.%d' % sys.version_info[:3]); raise SystemExit(0 if sys.version_info >= (3, 9) else 2)"
        $exit = 1
        $text = ''
        $timedOut = $false
        try {
            $info = New-Object System.Diagnostics.ProcessStartInfo
            $info.FileName = $full
            $info.Arguments = '-c "' + $detectCode + '"'
            $info.UseShellExecute = $false
            $info.RedirectStandardInput = $true
            $info.RedirectStandardOutput = $true
            $info.RedirectStandardError = $true
            $info.CreateNoWindow = $true
            $work = [System.IO.Path]::GetDirectoryName($full)
            if ([string]::IsNullOrWhiteSpace($work) -or -not (Test-Path -LiteralPath $work -PathType Container)) {
                $work = [Environment]::SystemDirectory
            }
            if (-not [string]::IsNullOrWhiteSpace($work)) {
                $info.WorkingDirectory = $work
            }
            $proc = New-Object System.Diagnostics.Process
            $proc.StartInfo = $info
            $null = $proc.Start()
            try { $proc.StandardInput.Close() } catch { }
            $finished = $proc.WaitForExit(20000)
            if (-not $finished) {
                $timedOut = $true
                try { $proc.Kill() } catch { }
                try { $proc.WaitForExit(2000) } catch { }
            }
            $stdout = ''
            $stderr = ''
            try { $stdout = [string]$proc.StandardOutput.ReadToEnd() } catch { }
            try { $stderr = [string]$proc.StandardError.ReadToEnd() } catch { }
            $text = $stdout + "`n" + $stderr
            if ($timedOut) {
                $exit = 1
            } elseif ($null -ne $proc.ExitCode) {
                $exit = $proc.ExitCode
            }
        } catch {
            $exit = 1
            $msg = ([string]$_.Exception.Message) -replace '\s+', ' '
            if ($msg.Length -gt 120) { $msg = $msg.Substring(0, 120) }
            $text = $msg
        }
        $lines = @($text -split "`r?`n")
        $tags = Read-AscTagged $lines
        $reported = [string]$tags['ASC_EXE']
        $ver = [string]$tags['ASC_VER']
        $reasons = New-Object System.Collections.Generic.List[string]
        if ($timedOut) {
            $reasons.Add('探测超时') | Out-Null
        } elseif ($exit -ne 0) {
            $rank = ConvertTo-AscVersion $ver
            $floor = ConvertTo-AscVersion '3.9'
            if (-not [string]::IsNullOrWhiteSpace($ver) -and $rank -ge 0 -and $floor -ge 0 -and $rank -lt $floor) {
                $reasons.Add("退出码 $exit，版本 $ver 低于 3.9") | Out-Null
            } else {
                $reasons.Add("退出码 $exit") | Out-Null
            }
        }
        if ($text -match 'Microsoft Store') { $reasons.Add('输出含 Microsoft Store') | Out-Null }
        if ($text -match 'Python was not found') { $reasons.Add('输出含 Python was not found') | Out-Null }
        if (Test-AscWindowsAppsPath $reported) { $reasons.Add('实际解释器在 Microsoft\WindowsApps') | Out-Null }
        $ok = ($reasons.Count -eq 0)
        $reason = ''
        if (-not $ok) { $reason = ($reasons.ToArray() -join '；') }
        return @{ Executable = $full; Version = $ver; Ok = [bool]$ok; ExitCode = $exit; Reason = $reason }
    }

    function Find-AscPy {
        $script:ascPyFoundPaths = New-Object System.Collections.Generic.List[string]
        $script:ascPyRejections = New-Object System.Collections.Generic.List[string]
        $best = $null
        $bestRank = -1
        $bestIsPython = $false
        foreach ($candidate in @(Get-AscPyCandidates)) {
            if ([string]::IsNullOrWhiteSpace([string]$candidate)) { continue }
            $tested = Test-AscPyCandidate ([string]$candidate)
            if ($null -eq $tested) { continue }
            Add-AscUniquePath $script:ascPyFoundPaths ([string]$tested.Executable)
            if (-not $tested.Ok) {
                $why = [string]$tested.Reason
                if ([string]::IsNullOrWhiteSpace($why)) { $why = '版本检测未通过' }
                $script:ascPyRejections.Add(([string]$tested.Executable) + '：' + $why) | Out-Null
                continue
            }
            $rank = ConvertTo-AscVersion ([string]$tested.Version)
            if ($rank -lt 0) { $rank = 0 }
            $leaf = [System.IO.Path]::GetFileName([string]$tested.Executable)
            $isPython = ($leaf -match '^(?i)python(\d+(\.\d+)*)?\.exe$')
            $better = $false
            if ($null -eq $best -or $rank -gt $bestRank) { $better = $true }
            elseif ($rank -eq $bestRank -and $isPython -and -not $bestIsPython) { $better = $true }
            if ($better) {
                $best = $tested
                $bestRank = $rank
                $bestIsPython = [bool]$isPython
            }
        }
        return $best
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
        $script:ascPyLogPath = [string]$files[0].FullName
        return [string]$files[0].FullName
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

    function Install-AscOfficialScope([string]$Installer, [string]$FileName, [int]$AllUsers) {
        $label = "InstallAllUsers=$AllUsers"
        Write-Host "正在静默安装 Python $($script:ascPyInstallerVersion)（$label）..."
        $result = Install-AscPythonExe $Installer $AllUsers
        $script:ascPyLastExit = "$($result.ExitCode)"
        $note = ''
        if ($result.ExitCode -eq 3010) { $note = '（3010 通常表示已安装，可能需要重新登录）' }
        $is1638 = Test-AscExit1638 $result.ExitCode
        if ($is1638) {
            $script:ascPyOfficial1638 = $true
            $script:ascPyAlreadyInstalled = $true
            $script:ascPyStale = $true
            $note = '（1638 / 0x666 表示已有相同或更新的产品）'
        }
        Add-AscPyLog "官方安装包 $FileName $label 退出码 $($result.ExitCode)$note"
        Update-AscProcessPath
        Add-AscPyLauncherPath ''
        $found = Find-AscPy
        return @{ Found = $found; ExitCode = $result.ExitCode; Is1638 = [bool]$is1638 }
    }

    function Install-AscPythonOfficial {
        $script:ascPyOfficial1638 = $false
        $version = Get-AscOfficialPythonVersion
        if ($version -notmatch '^\d+\.\d+\.\d+$') { $version = '3.12.10' }
        $script:ascPyInstallerVersion = $version
        $fileName = "python-$version-amd64.exe"
        $url = "https://www.python.org/ftp/python/$version/$fileName"
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
            $userTry = Install-AscOfficialScope $dest $fileName 0
            if ($userTry.Found -and $userTry.Found.Ok) {
                if ($userTry.Is1638) { $script:ascPyFromExisting = $true }
                return $userTry.Found
            }
            if ($userTry.Is1638) {
                Add-AscPyLog "官方安装包 $fileName 退出码 1638，已有相同或更新的产品，不再换更旧的安装包"
                return $null
            }
            $userFailed = ($userTry.ExitCode -ne 0 -and $userTry.ExitCode -ne 3010)
            if ($elevated -and $userFailed) {
                Write-AscWarn "用户范围官方安装包未得到可用的 Python（退出码 $($userTry.ExitCode)）。当前进程已提升，改为 InstallAllUsers=1。"
                $allTry = Install-AscOfficialScope $dest $fileName 1
                if ($allTry.Found -and $allTry.Found.Ok) {
                    if ($allTry.Is1638) { $script:ascPyFromExisting = $true }
                    return $allTry.Found
                }
                if ($allTry.Is1638) {
                    Add-AscPyLog "官方安装包 $fileName InstallAllUsers=1 退出码 1638，不再换更旧的安装包"
                    return $null
                }
            }
            $still = $userTry.Found
            if ($still -and -not [string]::IsNullOrWhiteSpace([string]$still.Version)) {
                Add-AscPyLog "官方安装包结束后解释器仍是 $($still.Version)，低于 3.9"
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
        $parts = New-Object System.Collections.Generic.List[string]
        if ($script:ascPyStale -or $script:ascPyAlreadyInstalled) {
            $parts.Add('残留登记：winget 显示 Python 已安装，但没有 3.9 或更高的解释器。') | Out-Null
        } else {
            $parts.Add('没有找到 3.9 或更高的 Python 解释器（已忽略 Microsoft\WindowsApps）。') | Out-Null
        }
        if ($script:ascPyUninstallTried) {
            $parts.Add('已尝试卸载残留，磁盘上仍然没有可用的 python.exe。') | Out-Null
        }
        $ver = [string]$script:ascPyInstallerVersion
        if ([string]::IsNullOrWhiteSpace($ver)) { $ver = '（未使用官方安装包）' }
        $parts.Add("最后安装包版本：$ver。") | Out-Null
        $parts.Add('卸载或安装后仍未找到 3.9 或更高的 python.exe 或 py.exe。') | Out-Null
        if (-not [string]::IsNullOrWhiteSpace([string]$script:ascPyLastExit)) {
            $parts.Add("安装器退出码：$($script:ascPyLastExit)。") | Out-Null
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$script:ascPyLogPath)) {
            $parts.Add("日志：$($script:ascPyLogPath)") | Out-Null
        }
        if (-not [string]::IsNullOrWhiteSpace($env:PY_PYTHON)) {
            $parts.Add("当前 PY_PYTHON=$($env:PY_PYTHON)。") | Out-Null
        }
        if ($null -ne $script:ascPyLog -and $script:ascPyLog.Count -gt 0) {
            $last = [string]$script:ascPyLog[$script:ascPyLog.Count - 1]
            if (-not [string]::IsNullOrWhiteSpace($last) -and $last.Length -le 180) {
                $parts.Add($last) | Out-Null
            }
        }
        if ($null -ne $script:ascPyFoundPaths -and $script:ascPyFoundPaths.Count -gt 0) {
            $parts.Add('搜到的路径：' + ($script:ascPyFoundPaths -join '；')) | Out-Null
        } else {
            $parts.Add('搜到的路径：（无）') | Out-Null
        }
        if ($null -ne $script:ascPyRejections -and $script:ascPyRejections.Count -gt 0) {
            foreach ($rej in $script:ascPyRejections) {
                $parts.Add([string]$rej) | Out-Null
            }
        } else {
            $parts.Add('拒绝原因：（无）') | Out-Null
        }
        $localRoot = ''
        $localExists = $false
        if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            $localRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
            $localExists = Test-Path -LiteralPath $localRoot -PathType Container
        }
        if ($localExists) {
            $parts.Add('%LOCALAPPDATA%\Programs\Python：存在') | Out-Null
            $dirNames = @()
            try {
                $dirNames = @(Get-ChildItem -LiteralPath $localRoot -Force -Directory -ErrorAction SilentlyContinue | ForEach-Object { [string]$_.Name })
            } catch {
                $dirNames = @()
            }
            if ($dirNames.Count -eq 0) {
                $parts.Add('第一层子目录：（无）') | Out-Null
            } else {
                $parts.Add('第一层子目录：' + ($dirNames -join '、')) | Out-Null
            }
        } else {
            $parts.Add('%LOCALAPPDATA%\Programs\Python：不存在') | Out-Null
            $parts.Add('第一层子目录：（无）') | Out-Null
        }
        Stop-AscInstall (($parts.ToArray()) -join "`n")
    }

    function Install-AscPython312 {
        $script:ascPyLog = New-Object System.Collections.Generic.List[string]
        $script:ascPyTail = ''
        $script:ascPyFromExisting = $false
        $script:ascPyRepairDone = $false
        $script:ascPyRepairInstalled = $false
        $script:ascPyRepairUserResult = $null
        $script:ascPyOfficial1638 = $false
        $script:ascPyStale = $false
        $script:ascPyUninstallTried = $false
        $script:ascPyReportedVersion = ''
        $script:ascPyInstallerVersion = ''
        $script:ascPyLastExit = ''
        $script:ascPyLogPath = ''
        $winget = Get-AscWingetPath
        $elevated = Test-AscElevated
        $triedMachine = $false
        if ($winget) {
            $userResult = Install-AscWingetId -Winget $winget -Id 'Python.Python.3.12' -Scope 'user'
            Remember-AscWingetPythonVersion ([string]$userResult.Text)
            $staleUser = Test-AscWingetNoUpgrade $userResult
            $user1603 = Test-AscResult1603 $userResult
            $user1638 = Test-AscResult1638 $userResult
            if ($staleUser -or $user1638) { $script:ascPyStale = $true }
            if ($staleUser -or $user1638 -or (Test-AscAlreadyInstalledExit $userResult.ExitCode)) {
                $script:ascPyAlreadyInstalled = $true
            }
            Add-AscPyLog "winget Python.Python.3.12 --scope user 退出码 $($userResult.ExitCode)"
            if ($staleUser) {
                Add-AscPyLog 'winget 用户范围已有登记且没有可升级项（-1978335189 / 0x8A15002B）'
            }
            if ($user1603) {
                Add-AscPyLog 'winget 用户范围退出码 1603'
                $script:ascPyLastExit = '1603'
            } else {
                $script:ascPyLastExit = "$($userResult.ExitCode)"
            }
            Update-AscProcessPath
            Add-AscPyLauncherPath ''
            $found = Find-AscPy
            if ($found -and $found.Ok) {
                $already = $staleUser -or $user1638 -or (Test-AscAlreadyInstalledExit $userResult.ExitCode)
                return (Publish-AscInstalledPython $found 'winget 用户范围' $userResult.ExitCode ([bool]$already))
            }
            $needsRepair = $staleUser -or $user1638 -or $user1603
            if ($needsRepair) {
                if ($user1603) {
                    Write-AscWarn "winget 用户范围退出码 1603。这不是改用旧安装包的信号，改为卸载用户范围残留后再安装。"
                } elseif ($user1638) {
                    Write-AscWarn "退出码 1638 表示已有相同或更新的产品。先卸载残留，再安装 winget 报告的版本。"
                } else {
                    Write-AscWarn "winget 登记了用户范围的 Python 3.12，但没有 3.9 或更高的解释器。这是残留登记，先卸载再安装，不改用机器范围。"
                }
                $found = Repair-AscUserPythonOnce $winget
                if ($found -and $found.Ok) {
                    $fromExisting = -not $script:ascPyRepairInstalled
                    return (Publish-AscInstalledPython $found 'winget 用户范围' $script:ascPyLastExit ([bool]$fromExisting))
                }
                $retry = $script:ascPyRepairUserResult
                if ($elevated -and -not $triedMachine -and (Test-AscUserInstallAllowsMachine $retry)) {
                    $triedMachine = $true
                    $machine = Install-AscPythonMachineOnce $winget
                    if ($machine.Found -and $machine.Found.Ok) {
                        return (Publish-AscInstalledPython $machine.Found 'winget 机器范围' $machine.Result.ExitCode ([bool]$machine.Stale))
                    }
                }
            } elseif ($elevated -and (Test-AscUserInstallAllowsMachine $userResult)) {
                $triedMachine = $true
                Write-AscWarn "用户范围安装失败，且不是 1603 或 1638。当前进程已提升，改为机器范围。"
                $machine = Install-AscPythonMachineOnce $winget
                if ($machine.Found -and $machine.Found.Ok) {
                    return (Publish-AscInstalledPython $machine.Found 'winget 机器范围' $machine.Result.ExitCode ([bool]($machine.Stale -or $machine.Is1638)))
                }
                if ($machine.Is1603 -or $machine.Stale -or $machine.Is1638) {
                    if ($machine.Is1603) { $script:ascPyStale = $true }
                    $found = Repair-AscUserPythonOnce $winget
                    if ($found -and $found.Ok) {
                        $fromExisting = -not $script:ascPyRepairInstalled
                        return (Publish-AscInstalledPython $found 'winget 用户范围' $script:ascPyLastExit ([bool]$fromExisting))
                    }
                }
            } else {
                if (-not $elevated) {
                    Add-AscPyLog '当前进程未提升，跳过 winget --scope machine'
                }
                if (-not $script:ascPyRepairDone) {
                    if ("$($userResult.ExitCode)".Trim() -eq '0' -or $script:ascPyAlreadyInstalled) {
                        $script:ascPyStale = $true
                    }
                    Write-AscWarn "用户范围安装后仍没有 3.9 或更高的解释器。先卸载已有登记，再安装用户范围的 Python 3.12。"
                    $found = Repair-AscUserPythonOnce $winget
                    if ($found -and $found.Ok) {
                        $fromExisting = -not $script:ascPyRepairInstalled
                        return (Publish-AscInstalledPython $found 'winget 用户范围' $script:ascPyLastExit ([bool]$fromExisting))
                    }
                }
            }
            $verNote = Get-AscOfficialPythonVersion
            Write-AscWarn "仍没有可用的 Python 3.9 或更高版本。改为官方安装包 $verNote。"
        } else {
            Add-AscPyLog 'winget 不可用'
            Write-AscWarn "未找到可用的 winget。改为下载官方 Python 安装包。"
        }
        $found = Install-AscPythonOfficial
        if ($found -and $found.Ok) {
            Add-AscPyLauncherPath ([string]$found.Executable)
            if ($script:ascPyFromExisting -or $script:ascPyOfficial1638) {
                Write-AscWarn "安装包报告 Python 已经安装。找到 $($found.Version)：$($found.Executable)。继续安装命令行工具。"
            } else {
                $script:ascInstalled += "Python $($found.Version)"
                Write-AscOk "已安装 Python $($found.Version)（官方安装包）"
            }
            return $found
        }
        if ($script:ascPyOfficial1638 -and -not $script:ascPyRepairDone) {
            Write-AscWarn "官方安装包退出码 1638，已有相同或更新的产品。卸载残留后再安装该版本，不再换更旧的安装包。"
            $script:ascPyStale = $true
            $found = Repair-AscUserPythonOnce ([string]$winget)
            if ($found -and $found.Ok) {
                $fromExisting = -not $script:ascPyRepairInstalled
                return (Publish-AscInstalledPython $found 'winget 用户范围' $script:ascPyLastExit ([bool]$fromExisting))
            }
            $found = Install-AscPythonOfficial
            if ($found -and $found.Ok) {
                Add-AscPyLauncherPath ([string]$found.Executable)
                if ($script:ascPyFromExisting -or $script:ascPyOfficial1638) {
                    Write-AscWarn "安装包报告 Python 已经安装。找到 $($found.Version)：$($found.Executable)。继续安装命令行工具。"
                } else {
                    $script:ascInstalled += "Python $($found.Version)"
                    Write-AscOk "已安装 Python $($found.Version)（官方安装包）"
                }
                return $found
            }
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
        & $script:ascPyExe -m pip install --user --upgrade --force-reinstall --no-cache-dir $ascGitUrl
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
    $platformScript = Join-Path -Path $env:TEMP -ChildPath ("asc-platform-check-" + [guid]::NewGuid().ToString("n") + ".py")
    $platformExit = 1
    $platformRaw = @()
    $platformErrText = ""
    $platformProc = $null
    try {
        $platformUtf8 = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($platformScript, $platformCode, $platformUtf8)
        $platformInfo = New-Object System.Diagnostics.ProcessStartInfo
        $platformInfo.FileName = $script:ascPyExe
        $platformInfo.Arguments = '"' + ($platformScript.Replace('"', '\"')) + '"'
        $platformInfo.UseShellExecute = $false
        $platformInfo.RedirectStandardOutput = $true
        $platformInfo.RedirectStandardError = $true
        $platformInfo.CreateNoWindow = $true
        $platformProc = New-Object System.Diagnostics.Process
        $platformProc.StartInfo = $platformInfo
        $null = $platformProc.Start()
        $platformOutTask = $platformProc.StandardOutput.ReadToEndAsync()
        $platformErrTask = $platformProc.StandardError.ReadToEndAsync()
        $null = $platformProc.WaitForExit()
        $platformStdout = [string]$platformOutTask.Result
        $platformErrText = [string]$platformErrTask.Result
        if ($null -ne $platformProc.ExitCode) {
            $platformExit = $platformProc.ExitCode
        }
        $platformRaw = @($platformStdout -split "`r?`n")
    } finally {
        if ($null -ne $platformProc) {
            try { $platformProc.Dispose() } catch { }
        }
        if (-not [string]::IsNullOrWhiteSpace($platformScript) -and (Test-Path -LiteralPath $platformScript)) {
            Remove-Item -LiteralPath $platformScript -Force -ErrorAction SilentlyContinue
        }
    }

    if ($platformExit -ne 0) {
        if (-not [string]::IsNullOrEmpty($platformErrText)) {
            Write-Host $platformErrText.TrimEnd("`r", "`n")
        }
        Write-AscErr "无法导入 asc.platform（退出码 $platformExit）"
        $ascFails.Add('asc.platform')
    } else {
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
        'Get-AscWherePaths', 'Add-AscLauncherFromRegistry', 'Test-AscAlreadyInstalledExit', 'Test-AscExit1638',
        'Test-AscResult1638', 'Test-AscResult1603', 'Test-AscWingetNoUpgrade', 'Test-AscUserInstallAllowsMachine',
        'Remember-AscWingetPythonVersion', 'Get-AscOfficialPythonVersion', 'Get-AscUninstallPythonEntries',
        'Add-AscUninstallPythonCandidates', 'Invoke-AscQuietUninstallCommand', 'Invoke-AscRegisteredPythonUninstall',
        'Uninstall-AscWingetPythonUser', 'Publish-AscInstalledPython', 'Install-AscPythonMachineOnce', 'Repair-AscUserPythonOnce',
        'Add-AscPySearchNote', 'Add-AscClassifiedExe', 'Add-AscGlobExe', 'Add-AscRegistryPythonCore',
        'Add-AscPresentExe', 'Add-AscChildPythonExe', 'Add-AscPythonFromInstallLogs', 'Get-AscPyCandidates',
        'Test-AscPyCandidate', 'Find-AscPy', 'Write-AscIgnoredStoreAliases', 'Test-AscElevated', 'Get-AscWingetPath',
        'Add-AscPyLauncherPath', 'Install-AscWingetId', 'Get-AscRecentPythonLogTail', 'Install-AscPythonExe',
        'Install-AscOfficialScope', 'Install-AscPythonOfficial', 'Stop-AscPythonMissing', 'Install-AscPython312',
        'Resolve-AscPython', 'Find-AscGitExe', 'Use-AscGitExe', 'Ensure-AscGit', 'Find-AscRepoRoot'
    )) {
        Remove-Item -Path "Function:\$ascFn" -ErrorAction SilentlyContinue
    }
    foreach ($ascStateName in @('ascSummaryShown', 'ascFailed', 'ascInstalled', 'ascPyVer', 'ascPipVer', 'ascPath', 'ascSourceLabel', 'ascBranch', 'ascLocalRoot', 'ascPyExe', 'ascPyLog', 'ascPyTail', 'ascPySearchNotes', 'ascPyAlreadyInstalled', 'ascPyFromExisting', 'ascPyRepairDone', 'ascPyRepairInstalled', 'ascPyRepairUserResult', 'ascPyReportedVersion', 'ascPyInstallerVersion', 'ascPyLastExit', 'ascPyLogPath', 'ascPyStale', 'ascPyUninstallTried', 'ascPyOfficial1638', 'ascLauncherWarnShown', 'ascPyFoundPaths', 'ascPyRejections')) {
        Remove-Variable -Name $ascStateName -Scope Script -ErrorAction SilentlyContinue
    }
}
