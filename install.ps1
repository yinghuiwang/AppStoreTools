# App Store Connect Tools — Windows installer.
# Run in the current process (do not Set-ExecutionPolicy):
#   irm https://raw.githubusercontent.com/yinghuiwang/AppStoreTools/main/install.ps1 | iex
# Installs the published PyPI package asc-appstore-tools (currently 0.1.31).
# Windows 定时任务和后台 web 的兼容改动还没发布到 PyPI。构建/上传/发布在 Windows 上不可用。

$ascSavedEap = $ErrorActionPreference
$ErrorActionPreference = 'Stop'
try {
    function Write-AscOk([string]$Message) { Write-Host "[OK] $Message" -ForegroundColor Green }
    function Write-AscWarn([string]$Message) { Write-Host "[!] $Message" -ForegroundColor Yellow }
    function Write-AscErr([string]$Message) { Write-Host "[X] $Message" -ForegroundColor Red }

    function Stop-AscInstall([string]$Message) {
        Write-AscErr $Message
        if ($PSCommandPath) { exit 1 }
        throw $Message
    }

    function Add-AscUserPath([string]$Dir) {
        if ([string]::IsNullOrWhiteSpace($Dir) -or -not (Test-Path -LiteralPath $Dir)) {
            Write-AscWarn "未找到 Scripts 目录，跳过 PATH：$Dir"
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

    Write-Host "================================================"
    Write-Host "  App Store Connect Tools — 安装程序 (Windows)"
    Write-Host "================================================"
    Write-Host ""

    $ascPyExe = $null
    $ascPyArgs = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"
        if ($LASTEXITCODE -eq 0) {
            $ascPyExe = 'py'
            $ascPyArgs = @('-3')
        }
    }
    if (-not $ascPyExe -and (Get-Command python -ErrorAction SilentlyContinue)) {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"
        if ($LASTEXITCODE -eq 0) {
            $ascPyExe = 'python'
            $ascPyArgs = @()
        }
    }
    if (-not $ascPyExe) {
        Stop-AscInstall "未找到 Python 3.9 或更高版本。请先安装 Python（含 py launcher）：https://www.python.org/downloads/"
    }

    $ascPyVer = (& $ascPyExe @ascPyArgs -c "import sys; print(sys.version.split()[0])").Trim()
    Write-AscOk "Python: $ascPyExe $($ascPyArgs -join ' ') ($ascPyVer)"

    & $ascPyExe @ascPyArgs -m pip --version
    if ($LASTEXITCODE -ne 0) {
        Write-AscWarn "pip 未安装，尝试 ensurepip ..."
        & $ascPyExe @ascPyArgs -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) {
            Stop-AscInstall "pip 不可用。请查看上方输出，或手动安装：https://pip.pypa.io/en/stable/installation/"
        }
    }

    Write-Host ""
    Write-Host "正在从 PyPI 安装 asc-appstore-tools ..."
    & $ascPyExe @ascPyArgs -m pip install --user --upgrade asc-appstore-tools
    if ($LASTEXITCODE -ne 0) {
        Stop-AscInstall "pip 安装失败。请查看上方输出。"
    }
    Write-AscOk "asc-appstore-tools 安装成功（--user / PyPI）"

    $ascScripts = (& $ascPyExe @ascPyArgs -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user') or '')").Trim()
    Add-AscUserPath $ascScripts

    Write-Host ""
    Write-Host "验证: $ascPyExe $($ascPyArgs -join ' ') -m asc --help"
    & $ascPyExe @ascPyArgs -m asc --help
    if ($LASTEXITCODE -ne 0) {
        Write-AscWarn "模块验证失败，再试 where.exe asc"
        & where.exe asc
        Stop-AscInstall "安装后未能运行 asc。"
    }
    Write-Host ""
    & where.exe asc
    if ($LASTEXITCODE -eq 0) {
        Write-AscOk "where.exe 已找到 asc"
    } else {
        Write-AscWarn "当前进程里 where.exe 还找不到 asc。用户 PATH 已写入，请新开一个终端再运行 asc。"
    }

    Write-Host ""
    Write-Host "安装完成。装到的是 PyPI 已发布的 asc-appstore-tools（当前为 0.1.31）。"
    Write-Host "Windows 定时任务和后台 web 的兼容改动还没发布到 PyPI。构建/上传/发布在 Windows 上不可用。"
    Write-Host ""
    Write-Host "下一步：在项目目录运行  asc install"
} finally {
    $ErrorActionPreference = $ascSavedEap
    Remove-Item -ErrorAction SilentlyContinue Function:\Write-AscOk, Function:\Write-AscWarn, Function:\Write-AscErr, Function:\Stop-AscInstall, Function:\Add-AscUserPath
}
