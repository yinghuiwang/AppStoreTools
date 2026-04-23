# Build / Deploy / Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `asc build`、`asc deploy`、`asc release` 三条命令，实现从 Xcode 源码构建到 App Store / TestFlight 上传的完整发布流程。

**Architecture:** 所有核心逻辑集中在 `src/asc/commands/build.py`，通过可 mock 的函数边界隔离 `xcodebuild` 和 `xcrun` 系统调用，方便测试。`asc release` 直接调用 `build_core()` 和 `deploy_core()`，不重复实现逻辑。

**Tech Stack:** Python 3.9+, typer, subprocess, plistlib, pytest + unittest.mock

---

## 文件清单

| 文件 | 操作 |
|------|------|
| `src/asc/commands/build.py` | 新建（全部核心逻辑） |
| `src/asc/config.py` | 修改：新增 `[build]` section 属性 |
| `src/asc/cli.py` | 修改：导入并注册三条新命令 |
| `tests/test_build.py` | 新建（TDD 测试） |

---

## Task 1：`config.py` 新增 `[build]` section 属性

**Files:**
- Modify: `src/asc/config.py`
- Test: `tests/test_build.py`

- [ ] **Step 1：写入失败测试**

新建 `tests/test_build.py`：

```python
"""Tests for build/deploy/release commands."""
from __future__ import annotations

import sys
import plistlib
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import pytest
from typer.testing import CliRunner

from asc.cli import app
from asc.config import Config

runner = CliRunner()


# ── Config tests ──

def test_config_build_project(tmp_path, monkeypatch):
    """Config reads build.project from local config.toml."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".asc").mkdir()
    (tmp_path / ".asc" / "config.toml").write_text(
        '[build]\nproject = "MyApp.xcworkspace"\n'
    )
    cfg = Config()
    assert cfg.build_project == "MyApp.xcworkspace"


def test_config_build_defaults(tmp_path, monkeypatch):
    """Config returns None for build fields when not configured."""
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    assert cfg.build_project is None
    assert cfg.build_scheme is None
    assert cfg.build_output == "build"
    assert cfg.build_signing == "auto"
```

- [ ] **Step 2：运行，确认失败**

```bash
pytest tests/test_build.py::test_config_build_project tests/test_build.py::test_config_build_defaults -v
```

预期：FAILED — `Config` 没有 `build_project` 属性

- [ ] **Step 3：在 `src/asc/config.py` 末尾追加属性**

在 `screenshots_path` 属性之后、`list_apps` 方法之前插入：

```python
    @property
    def build_project(self) -> str | None:
        return self.get("project", section="build")

    @property
    def build_scheme(self) -> str | None:
        return self.get("scheme", section="build")

    @property
    def build_output(self) -> str:
        return self.get("output", default="build", section="build")

    @property
    def build_signing(self) -> str:
        return self.get("signing", default="auto", section="build")
```

- [ ] **Step 4：运行，确认通过**

```bash
pytest tests/test_build.py::test_config_build_project tests/test_build.py::test_config_build_defaults -v
```

预期：2 个 PASSED

- [ ] **Step 5：Commit**

```bash
git add src/asc/config.py tests/test_build.py
git commit -m "feat: add [build] section properties to Config"
```

---

## Task 2：`detect_project` 和 `list_schemes`

**Files:**
- Create: `src/asc/commands/build.py`
- Test: `tests/test_build.py`

- [ ] **Step 1：写入失败测试**

在 `tests/test_build.py` 末尾追加：

```python
# ── detect_project tests ──

def test_detect_project_workspace(tmp_path):
    """Prefers .xcworkspace over .xcodeproj."""
    from asc.commands.build import detect_project
    ws = tmp_path / "MyApp.xcworkspace"
    ws.mkdir()
    proj = tmp_path / "MyApp.xcodeproj"
    proj.mkdir()
    path, kind = detect_project(str(tmp_path))
    assert path == str(ws)
    assert kind == "workspace"


def test_detect_project_xcodeproj(tmp_path):
    """Falls back to .xcodeproj when no workspace."""
    from asc.commands.build import detect_project
    proj = tmp_path / "MyApp.xcodeproj"
    proj.mkdir()
    path, kind = detect_project(str(tmp_path))
    assert path == str(proj)
    assert kind == "project"


def test_detect_project_explicit_path(tmp_path):
    """Explicit path is returned as-is (workspace)."""
    from asc.commands.build import detect_project
    ws = tmp_path / "MyApp.xcworkspace"
    ws.mkdir()
    path, kind = detect_project(str(ws))
    assert path == str(ws)
    assert kind == "workspace"


def test_detect_project_not_found(tmp_path):
    """Raises ValueError when no Xcode project found."""
    from asc.commands.build import detect_project
    with pytest.raises(ValueError, match="No Xcode project"):
        detect_project(str(tmp_path))


# ── list_schemes tests ──

def test_list_schemes_parses_output():
    """Parses scheme names from xcodebuild -list output."""
    from asc.commands.build import list_schemes
    fake_output = """
Information about project "MyApp":
    Schemes:
        MyApp
        MyAppTests
        MyAppUITests
"""
    with patch("asc.commands.build.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=fake_output, returncode=0)
        schemes = list_schemes("/path/to/MyApp.xcworkspace", "workspace")
    assert schemes == ["MyApp", "MyAppTests", "MyAppUITests"]
```

- [ ] **Step 2：运行，确认失败**

```bash
pytest tests/test_build.py -k "detect_project or list_schemes" -v
```

预期：FAILED — `cannot import name 'detect_project'`

- [ ] **Step 3：创建 `src/asc/commands/build.py`**

```python
"""Build, deploy, and release commands for asc CLI."""
from __future__ import annotations

import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import typer

from asc.config import Config
from asc.utils import make_api_from_config


def _require_macos() -> None:
    if sys.platform != "darwin":
        typer.echo("❌ 此命令仅支持 macOS", err=True)
        raise typer.Exit(2)


def detect_project(path: str) -> tuple[str, str]:
    """Return (project_path, kind) where kind is 'workspace' or 'project'.

    If path points directly to a .xcworkspace or .xcodeproj, return it.
    Otherwise search the directory for one, preferring .xcworkspace.
    """
    p = Path(path)

    if p.suffix == ".xcworkspace":
        return str(p), "workspace"
    if p.suffix == ".xcodeproj":
        return str(p), "project"

    # Search directory
    workspaces = list(p.glob("*.xcworkspace"))
    if workspaces:
        return str(workspaces[0]), "workspace"

    projects = list(p.glob("*.xcodeproj"))
    if projects:
        return str(projects[0]), "project"

    raise ValueError(f"No Xcode project or workspace found in: {path}")


def list_schemes(project_path: str, kind: str) -> list[str]:
    """Return list of scheme names from xcodebuild -list."""
    flag = "-workspace" if kind == "workspace" else "-project"
    result = subprocess.run(
        ["xcodebuild", flag, project_path, "-list"],
        capture_output=True, text=True,
    )
    schemes: list[str] = []
    in_schemes = False
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped == "Schemes:":
            in_schemes = True
            continue
        if in_schemes:
            if stripped and not stripped.endswith(":"):
                schemes.append(stripped)
            elif stripped.endswith(":") and stripped != "Schemes:":
                break
    return schemes
```

- [ ] **Step 4：运行，确认通过**

```bash
pytest tests/test_build.py -k "detect_project or list_schemes" -v
```

预期：6 个 PASSED

- [ ] **Step 5：Commit**

```bash
git add src/asc/commands/build.py tests/test_build.py
git commit -m "feat: add detect_project and list_schemes"
```

---

## Task 3：`generate_export_options`

**Files:**
- Modify: `src/asc/commands/build.py`
- Test: `tests/test_build.py`

- [ ] **Step 1：写入失败测试**

在 `tests/test_build.py` 末尾追加：

```python
# ── generate_export_options tests ──

def test_generate_export_options_auto_appstore(tmp_path):
    """Auto signing, appstore destination generates correct plist."""
    from asc.commands.build import generate_export_options
    plist_path = generate_export_options(
        signing="auto",
        destination="appstore",
        profile=None,
        certificate=None,
        output_dir=str(tmp_path),
    )
    with open(plist_path, "rb") as f:
        opts = plistlib.load(f)
    assert opts["method"] == "app-store-connect"
    assert opts["signingStyle"] == "automatic"
    assert "provisioningProfiles" not in opts


def test_generate_export_options_manual(tmp_path):
    """Manual signing generates provisioningProfiles and signingCertificate."""
    from asc.commands.build import generate_export_options
    plist_path = generate_export_options(
        signing="manual",
        destination="testflight",
        profile="/path/to/profile.mobileprovision",
        certificate="iPhone Distribution: ACME Corp",
        output_dir=str(tmp_path),
    )
    with open(plist_path, "rb") as f:
        opts = plistlib.load(f)
    assert opts["method"] == "app-store-connect"
    assert opts["signingStyle"] == "manual"
    assert opts["signingCertificate"] == "iPhone Distribution: ACME Corp"


def test_generate_export_options_testflight(tmp_path):
    """testflight destination uses app-store-connect method."""
    from asc.commands.build import generate_export_options
    plist_path = generate_export_options(
        signing="auto",
        destination="testflight",
        profile=None,
        certificate=None,
        output_dir=str(tmp_path),
    )
    with open(plist_path, "rb") as f:
        opts = plistlib.load(f)
    assert opts["method"] == "app-store-connect"
```

- [ ] **Step 2：运行，确认失败**

```bash
pytest tests/test_build.py -k "generate_export_options" -v
```

预期：FAILED — `cannot import name 'generate_export_options'`

- [ ] **Step 3：在 `build.py` 中追加函数**

在 `list_schemes` 函数之后追加：

```python
def generate_export_options(
    signing: str,
    destination: str,
    profile: str | None,
    certificate: str | None,
    output_dir: str,
) -> str:
    """Generate ExportOptions.plist and return its path."""
    opts: dict = {
        "method": "app-store-connect",
        "signingStyle": "automatic" if signing == "auto" else "manual",
    }
    if signing == "manual":
        if certificate:
            opts["signingCertificate"] = certificate
        if profile:
            opts["provisioningProfiles"] = {"": profile}

    plist_path = Path(output_dir) / "ExportOptions.plist"
    with open(plist_path, "wb") as f:
        plistlib.dump(opts, f)
    return str(plist_path)
```

- [ ] **Step 4：运行，确认通过**

```bash
pytest tests/test_build.py -k "generate_export_options" -v
```

预期：3 个 PASSED

- [ ] **Step 5：Commit**

```bash
git add src/asc/commands/build.py tests/test_build.py
git commit -m "feat: add generate_export_options"
```

---

## Task 4：`run_xcodebuild_archive` 和 `run_xcodebuild_export`

**Files:**
- Modify: `src/asc/commands/build.py`
- Test: `tests/test_build.py`

- [ ] **Step 1：写入失败测试**

在 `tests/test_build.py` 末尾追加：

```python
# ── run_xcodebuild_archive / export tests ──

def test_run_xcodebuild_archive_calls_correct_command(tmp_path):
    """Calls xcodebuild archive with correct flags."""
    from asc.commands.build import run_xcodebuild_archive
    archive_path = tmp_path / "MyApp.xcarchive"

    with patch("asc.commands.build.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        # Simulate archive dir creation
        archive_path.mkdir()
        result = run_xcodebuild_archive(
            project="/path/MyApp.xcworkspace",
            kind="workspace",
            scheme="MyApp",
            configuration="Release",
            archive_path=str(archive_path),
        )

    cmd = mock_run.call_args[0][0]
    assert "xcodebuild" in cmd
    assert "archive" in cmd
    assert "-workspace" in cmd
    assert "-scheme" in cmd
    assert "MyApp" in cmd


def test_run_xcodebuild_archive_raises_on_failure(tmp_path):
    """Raises RuntimeError when xcodebuild returns non-zero."""
    from asc.commands.build import run_xcodebuild_archive
    with patch("asc.commands.build.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="Build FAILED")
        with pytest.raises(RuntimeError, match="xcodebuild archive failed"):
            run_xcodebuild_archive(
                project="/path/MyApp.xcworkspace",
                kind="workspace",
                scheme="MyApp",
                configuration="Release",
                archive_path=str(tmp_path / "MyApp.xcarchive"),
            )


def test_run_xcodebuild_export_calls_correct_command(tmp_path):
    """Calls xcodebuild -exportArchive with correct flags."""
    from asc.commands.build import run_xcodebuild_export
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    ipa = export_dir / "MyApp.ipa"
    ipa.write_bytes(b"fake")

    with patch("asc.commands.build.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = run_xcodebuild_export(
            archive_path=str(tmp_path / "MyApp.xcarchive"),
            export_options_path="/tmp/ExportOptions.plist",
            output_dir=str(export_dir),
        )

    cmd = mock_run.call_args[0][0]
    assert "-exportArchive" in cmd
    assert "-exportOptionsPlist" in cmd
    assert result == str(ipa)
```

- [ ] **Step 2：运行，确认失败**

```bash
pytest tests/test_build.py -k "run_xcodebuild" -v
```

预期：FAILED — `cannot import name 'run_xcodebuild_archive'`

- [ ] **Step 3：在 `build.py` 中追加两个函数**

在 `generate_export_options` 之后追加：

```python
def run_xcodebuild_archive(
    project: str,
    kind: str,
    scheme: str,
    configuration: str,
    archive_path: str,
) -> str:
    """Run xcodebuild archive. Return archive_path on success."""
    flag = "-workspace" if kind == "workspace" else "-project"
    cmd = [
        "xcodebuild",
        flag, project,
        "-scheme", scheme,
        "-configuration", configuration,
        "-archivePath", archive_path,
        "archive",
        "-allowProvisioningUpdates",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"xcodebuild archive failed:\n{result.stderr}")
    return archive_path


def run_xcodebuild_export(
    archive_path: str,
    export_options_path: str,
    output_dir: str,
) -> str:
    """Run xcodebuild -exportArchive. Return path to .ipa file."""
    cmd = [
        "xcodebuild",
        "-exportArchive",
        "-archivePath", archive_path,
        "-exportOptionsPlist", export_options_path,
        "-exportPath", output_dir,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"xcodebuild exportArchive failed:\n{result.stderr}")

    ipas = list(Path(output_dir).glob("*.ipa"))
    if not ipas:
        raise RuntimeError(f"No .ipa found in {output_dir} after export")
    return str(ipas[0])
```

- [ ] **Step 4：运行，确认通过**

```bash
pytest tests/test_build.py -k "run_xcodebuild" -v
```

预期：3 个 PASSED

- [ ] **Step 5：Commit**

```bash
git add src/asc/commands/build.py tests/test_build.py
git commit -m "feat: add run_xcodebuild_archive and run_xcodebuild_export"
```

---

## Task 5：`build_core` 和 `cmd_build`

**Files:**
- Modify: `src/asc/commands/build.py`
- Test: `tests/test_build.py`

- [ ] **Step 1：写入失败测试**

在 `tests/test_build.py` 末尾追加：

```python
# ── build_core / cmd_build tests ──

def test_build_core_dry_run(tmp_path, monkeypatch, capsys):
    """build_core with dry_run=True prints command info without running."""
    from asc.commands.build import build_core
    monkeypatch.chdir(tmp_path)
    ws = tmp_path / "MyApp.xcworkspace"
    ws.mkdir()

    ipa_path = build_core(
        project=str(ws),
        scheme="MyApp",
        configuration="Release",
        output=str(tmp_path / "build"),
        signing="auto",
        profile=None,
        certificate=None,
        destination="appstore",
        dry_run=True,
    )
    assert ipa_path is None
    captured = capsys.readouterr()
    assert "MyApp" in captured.out
    assert "[预览]" in captured.out or "dry" in captured.out.lower()


def test_cmd_build_non_macos():
    """asc build on non-macOS exits with code 2."""
    with patch("asc.commands.build.sys") as mock_sys:
        mock_sys.platform = "linux"
        result = runner.invoke(app, ["build", "--scheme", "MyApp"])
    assert result.exit_code == 2
```

- [ ] **Step 2：运行，确认失败**

```bash
pytest tests/test_build.py -k "build_core or cmd_build" -v
```

预期：FAILED

- [ ] **Step 3：在 `build.py` 中追加 `build_core` 和 `cmd_build`**

在 `run_xcodebuild_export` 之后追加：

```python
def build_core(
    project: str | None,
    scheme: str | None,
    configuration: str,
    output: str,
    signing: str,
    profile: str | None,
    certificate: str | None,
    destination: str,
    dry_run: bool,
) -> str | None:
    """Core build logic. Returns .ipa path, or None if dry_run."""
    project_path, kind = detect_project(project or ".")
    typer.echo(f"\n{'='*56}")
    typer.echo("  asc build")
    typer.echo(f"{'='*56}")
    typer.echo(f"  项目: {project_path}")

    if not scheme:
        schemes = list_schemes(project_path, kind)
        if not schemes:
            typer.echo("❌ 未找到任何 Scheme", err=True)
            raise typer.Exit(1)
        if len(schemes) == 1:
            scheme = schemes[0]
        else:
            typer.echo("可用 Scheme：")
            for s in schemes:
                typer.echo(f"  • {s}")
            scheme = typer.prompt("请选择 Scheme")

    typer.echo(f"  Scheme: {scheme}")
    typer.echo(f"  配置: {configuration}")
    typer.echo(f"  签名: {signing}")
    typer.echo(f"  目标: {destination}")

    output_dir = Path(output)
    archive_path = str(output_dir / f"{scheme}.xcarchive")
    export_dir = str(output_dir / "export")

    if dry_run:
        typer.echo("\n[预览] 将运行：")
        typer.echo(f"  xcodebuild archive → {archive_path}")
        typer.echo(f"  xcodebuild -exportArchive → {export_dir}/*.ipa")
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    Path(export_dir).mkdir(parents=True, exist_ok=True)

    typer.echo("\n  ── 步骤 1/3：生成 ExportOptions.plist ──")
    export_options = generate_export_options(
        signing=signing,
        destination=destination,
        profile=profile,
        certificate=certificate,
        output_dir=str(output_dir),
    )

    typer.echo("  ── 步骤 2/3：构建 Archive ──")
    run_xcodebuild_archive(project_path, kind, scheme, configuration, archive_path)
    typer.echo(f"  ✅ Archive: {archive_path}")

    typer.echo("  ── 步骤 3/3：导出 IPA ──")
    ipa_path = run_xcodebuild_export(archive_path, export_options, export_dir)
    typer.echo(f"  ✅ IPA: {ipa_path}")
    return ipa_path


def cmd_build(
    project: Optional[str] = typer.Option(None, "--project", help="Xcode 项目路径（.xcodeproj 或 .xcworkspace）"),
    scheme: Optional[str] = typer.Option(None, "--scheme", help="Xcode Scheme 名称"),
    configuration: str = typer.Option("Release", "--configuration", help="构建配置"),
    output: Optional[str] = typer.Option(None, "--output", help="输出目录（默认 ./build）"),
    signing: str = typer.Option("auto", "--signing", help="签名方式：auto 或 manual"),
    profile: Optional[str] = typer.Option(None, "--profile", help="手动签名：Provisioning Profile 路径"),
    certificate: Optional[str] = typer.Option(None, "--certificate", help="手动签名：证书名称"),
    destination: str = typer.Option("appstore", "--destination", help="导出类型：appstore 或 testflight"),
    app: Optional[str] = typer.Option(None, "--app", help="App profile 名称"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预览命令但不执行"),
):
    """构建 Xcode 项目并导出 .ipa 文件。

    \b
    Example:
        asc build --scheme MyApp
        asc build --project MyApp.xcworkspace --scheme MyApp --destination testflight
        asc build --signing manual --certificate "iPhone Distribution: ACME" --profile path/to/profile
    """
    _require_macos()
    config = Config(app)
    ipa = build_core(
        project=project or config.build_project,
        scheme=scheme or config.build_scheme,
        configuration=configuration,
        output=output or config.build_output,
        signing=signing or config.build_signing,
        profile=profile,
        certificate=certificate,
        destination=destination,
        dry_run=dry_run,
    )
    if ipa:
        typer.echo(f"\n✅ 构建完成: {ipa}")
```

- [ ] **Step 4：运行，确认通过**

```bash
pytest tests/test_build.py -k "build_core or cmd_build" -v
```

预期：2 个 PASSED

- [ ] **Step 5：Commit**

```bash
git add src/asc/commands/build.py tests/test_build.py
git commit -m "feat: add build_core and cmd_build"
```

---

## Task 6：`upload_ipa`、`deploy_core` 和 `cmd_deploy`

**Files:**
- Modify: `src/asc/commands/build.py`
- Test: `tests/test_build.py`

- [ ] **Step 1：写入失败测试**

在 `tests/test_build.py` 末尾追加：

```python
# ── upload_ipa / deploy_core / cmd_deploy tests ──

def test_upload_ipa_uses_notarytool(tmp_path):
    """upload_ipa calls xcrun notarytool when available."""
    from asc.commands.build import upload_ipa
    ipa = tmp_path / "MyApp.ipa"
    ipa.write_bytes(b"fake")

    with patch("asc.commands.build.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        upload_ipa(
            ipa_path=str(ipa),
            issuer_id="issuer-123",
            key_id="key-456",
            key_file="/path/to/key.p8",
            destination="testflight",
        )

    cmd = mock_run.call_args[0][0]
    assert "xcrun" in cmd
    # notarytool or altool
    assert "notarytool" in cmd or "altool" in cmd


def test_upload_ipa_raises_on_failure(tmp_path):
    """upload_ipa raises RuntimeError on non-zero returncode."""
    from asc.commands.build import upload_ipa
    ipa = tmp_path / "MyApp.ipa"
    ipa.write_bytes(b"fake")

    with patch("asc.commands.build.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="Upload failed")
        with pytest.raises(RuntimeError, match="Upload failed"):
            upload_ipa(
                ipa_path=str(ipa),
                issuer_id="issuer-123",
                key_id="key-456",
                key_file="/path/to/key.p8",
                destination="testflight",
            )


def test_cmd_deploy_non_macos():
    """asc deploy on non-macOS exits with code 2."""
    with patch("asc.commands.build.sys") as mock_sys:
        mock_sys.platform = "linux"
        result = runner.invoke(app, ["deploy", "--ipa", "MyApp.ipa"])
    assert result.exit_code == 2


def test_deploy_core_dry_run(tmp_path, capsys):
    """deploy_core with dry_run=True prints info without uploading."""
    from asc.commands.build import deploy_core
    ipa = tmp_path / "MyApp.ipa"
    ipa.write_bytes(b"fake")

    deploy_core(
        ipa_path=str(ipa),
        issuer_id="issuer-123",
        key_id="key-456",
        key_file="/path/to/key.p8",
        destination="testflight",
        dry_run=True,
    )
    captured = capsys.readouterr()
    assert "MyApp.ipa" in captured.out
    assert "[预览]" in captured.out or "dry" in captured.out.lower()
```

- [ ] **Step 2：运行，确认失败**

```bash
pytest tests/test_build.py -k "upload_ipa or deploy_core or cmd_deploy" -v
```

预期：FAILED — `cannot import name 'upload_ipa'`

- [ ] **Step 3：在 `build.py` 中追加三个函数**

在 `cmd_build` 之后追加：

```python
def upload_ipa(
    ipa_path: str,
    issuer_id: str,
    key_id: str,
    key_file: str,
    destination: str,
) -> None:
    """Upload .ipa using xcrun notarytool (preferred) or altool."""
    cmd = [
        "xcrun", "notarytool", "submit", ipa_path,
        "--issuer-id", issuer_id,
        "--key-id", key_id,
        "--key", key_file,
        "--wait",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback to altool
        alt_cmd = [
            "xcrun", "altool", "--upload-app",
            "-f", ipa_path,
            "--apiKey", key_id,
            "--apiIssuer", issuer_id,
            "-t", "ios",
        ]
        alt_result = subprocess.run(alt_cmd, capture_output=True, text=True)
        if alt_result.returncode != 0:
            raise RuntimeError(f"Upload failed:\n{alt_result.stderr}")


def deploy_core(
    ipa_path: str,
    issuer_id: str,
    key_id: str,
    key_file: str,
    destination: str,
    dry_run: bool,
) -> None:
    """Core deploy logic."""
    typer.echo(f"\n{'='*56}")
    typer.echo("  asc deploy")
    typer.echo(f"{'='*56}")
    typer.echo(f"  IPA: {ipa_path}")
    typer.echo(f"  目标: {destination}")

    if not Path(ipa_path).exists():
        typer.echo(f"❌ IPA 文件不存在: {ipa_path}", err=True)
        raise typer.Exit(1)

    if dry_run:
        typer.echo("\n[预览] 将上传：")
        typer.echo(f"  xcrun notarytool submit {ipa_path} --wait")
        return

    typer.echo("\n  正在上传...")
    upload_ipa(ipa_path, issuer_id, key_id, key_file, destination)
    typer.echo("  ✅ 上传成功")


def cmd_deploy(
    ipa: str = typer.Option(..., "--ipa", help=".ipa 文件路径"),
    destination: str = typer.Option("testflight", "--destination", help="上传目标：testflight 或 appstore"),
    app: Optional[str] = typer.Option(None, "--app", help="App profile 名称"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预览但不实际上传"),
):
    """上传 .ipa 到 TestFlight 或 App Store。

    \b
    Example:
        asc deploy --ipa build/export/MyApp.ipa
        asc deploy --ipa MyApp.ipa --destination appstore
        asc deploy --ipa MyApp.ipa --dry-run
    """
    _require_macos()
    config = Config(app)

    issuer_id = config.issuer_id
    key_id = config.key_id
    key_file = config.key_file

    if not all([issuer_id, key_id, key_file]):
        typer.echo("❌ 缺少 API 凭证，请运行 asc app add 配置", err=True)
        raise typer.Exit(1)

    try:
        deploy_core(
            ipa_path=ipa,
            issuer_id=issuer_id,
            key_id=key_id,
            key_file=key_file,
            destination=destination,
            dry_run=dry_run,
        )
    except RuntimeError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(1)
```

- [ ] **Step 4：运行，确认通过**

```bash
pytest tests/test_build.py -k "upload_ipa or deploy_core or cmd_deploy" -v
```

预期：4 个 PASSED

- [ ] **Step 5：Commit**

```bash
git add src/asc/commands/build.py tests/test_build.py
git commit -m "feat: add upload_ipa, deploy_core, and cmd_deploy"
```

---

## Task 7：`cmd_release` 和 CLI 注册

**Files:**
- Modify: `src/asc/commands/build.py`
- Modify: `src/asc/cli.py`
- Test: `tests/test_build.py`

- [ ] **Step 1：写入失败测试**

在 `tests/test_build.py` 末尾追加：

```python
# ── cmd_release tests ──

def test_cmd_release_non_macos():
    """asc release on non-macOS exits with code 2."""
    with patch("asc.commands.build.sys") as mock_sys:
        mock_sys.platform = "linux"
        result = runner.invoke(app, ["release", "--scheme", "MyApp"])
    assert result.exit_code == 2


def test_release_calls_build_and_deploy(tmp_path, monkeypatch):
    """asc release calls build_core then deploy_core."""
    from asc.commands import build as build_mod
    monkeypatch.chdir(tmp_path)
    ws = tmp_path / "MyApp.xcworkspace"
    ws.mkdir()

    with patch.object(build_mod, "build_core", return_value="/tmp/MyApp.ipa") as mock_build, \
         patch.object(build_mod, "deploy_core") as mock_deploy, \
         patch.object(build_mod, "sys") as mock_sys:
        mock_sys.platform = "darwin"
        result = runner.invoke(app, [
            "release",
            "--project", str(ws),
            "--scheme", "MyApp",
            "--destination", "testflight",
        ])

    assert mock_build.called
    assert mock_deploy.called


def test_asc_help_shows_build_deploy_release():
    """asc --help lists build, deploy, release commands."""
    result = runner.invoke(app, ["--help"])
    assert "build" in result.output
    assert "deploy" in result.output
    assert "release" in result.output
```

- [ ] **Step 2：运行，确认失败**

```bash
pytest tests/test_build.py -k "cmd_release or asc_help_shows" -v
```

預期：FAILED

- [ ] **Step 3：在 `build.py` 末尾追加 `cmd_release`**

```python
def cmd_release(
    project: Optional[str] = typer.Option(None, "--project", help="Xcode 项目路径"),
    scheme: Optional[str] = typer.Option(None, "--scheme", help="Xcode Scheme 名称"),
    destination: str = typer.Option("testflight", "--destination", help="发布目标：testflight 或 appstore"),
    signing: str = typer.Option("auto", "--signing", help="签名方式：auto 或 manual"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Provisioning Profile 路径"),
    certificate: Optional[str] = typer.Option(None, "--certificate", help="证书名称"),
    output: Optional[str] = typer.Option(None, "--output", help="输出目录（默认 ./build）"),
    app: Optional[str] = typer.Option(None, "--app", help="App profile 名称"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预览但不执行"),
):
    """一键构建并发布到 TestFlight 或 App Store。

    \b
    Example:
        asc release --scheme MyApp
        asc release --destination appstore
        asc release --dry-run
    """
    _require_macos()
    config = Config(app)

    issuer_id = config.issuer_id
    key_id = config.key_id
    key_file = config.key_file

    if not dry_run and not all([issuer_id, key_id, key_file]):
        typer.echo("❌ 缺少 API 凭证，请运行 asc app add 配置", err=True)
        raise typer.Exit(1)

    try:
        ipa_path = build_core(
            project=project or config.build_project,
            scheme=scheme or config.build_scheme,
            configuration="Release",
            output=output or config.build_output,
            signing=signing or config.build_signing,
            profile=profile,
            certificate=certificate,
            destination=destination,
            dry_run=dry_run,
        )

        if ipa_path:
            deploy_core(
                ipa_path=ipa_path,
                issuer_id=issuer_id or "",
                key_id=key_id or "",
                key_file=key_file or "",
                destination=destination,
                dry_run=dry_run,
            )
    except RuntimeError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(1)

    if not dry_run:
        typer.echo("\n🎉 发布完成！")
```

- [ ] **Step 4：在 `src/asc/cli.py` 中注册三条命令**

找到：
```python
from asc.commands.app_config import cmd_app_add, cmd_app_list, cmd_app_remove, cmd_app_default, cmd_install
```

在其后添加：
```python
from asc.commands.build import cmd_build, cmd_deploy, cmd_release
```

在文件末尾追加：
```python
app.command("build")(cmd_build)
app.command("deploy")(cmd_deploy)
app.command("release")(cmd_release)
```

- [ ] **Step 5：运行全部测试**

```bash
pytest tests/ -v
```

预期：全部 PASSED（含之前所有测试）

- [ ] **Step 6：验证帮助输出**

```bash
asc --help
```

预期输出包含 `build`、`deploy`、`release` 三行。

- [ ] **Step 7：Commit**

```bash
git add src/asc/commands/build.py src/asc/cli.py tests/test_build.py
git commit -m "feat: add cmd_release and register build/deploy/release commands"
```

---

## Task 8：更新 README 和 CLAUDE.md

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1：在 README.md 用法章节新增构建与发布**

在 `## 用法` 的 `# ── 安装与初始化 ──` 块之后、完整上传之前插入：

```bash
# ── 构建与发布 ──

# 构建 .xcarchive + 导出 .ipa
asc build --scheme MyApp
asc build --project MyApp.xcworkspace --scheme MyApp --destination testflight

# 上传已有 .ipa 到 TestFlight
asc deploy --ipa build/export/MyApp.ipa
asc deploy --ipa MyApp.ipa --destination appstore

# 一键构建 + 发布
asc release --scheme MyApp --destination testflight
asc release --dry-run

```

- [ ] **Step 2：在 README.md 新增构建配置章节**

在"设置默认 App"章节之后插入：

```markdown
### 构建配置（`.asc/config.toml`）

可在 `.asc/config.toml` 中保存构建默认值，避免每次重复输入：

```toml
[build]
project = "MyApp.xcworkspace"
scheme = "MyApp"
output = "build"
signing = "auto"
```

配置后最短用法：

```bash
asc release --destination testflight
```
```

- [ ] **Step 3：更新 CLAUDE.md 中的命令列表**

在 `asc --app myapp check` 行之后追加：

```
asc build --scheme MyApp                                  # Build .xcarchive + export .ipa
asc deploy --ipa build/export/MyApp.ipa                  # Upload .ipa to TestFlight/App Store
asc release --scheme MyApp --destination testflight      # Build + upload in one step
```

- [ ] **Step 4：Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: add build/deploy/release usage to README and CLAUDE.md"
```

---

## Task 9：推送

- [ ] **Step 1：运行全部测试确认通过**

```bash
pytest tests/ -q
```

预期：全部 PASSED，无 warning

- [ ] **Step 2：推送**

```bash
git push
```
