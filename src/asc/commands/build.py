"""Build, deploy, and release commands for asc CLI."""
from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

import typer

from asc.config import Config


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
    if result.returncode != 0:
        raise RuntimeError(f"xcodebuild -list failed:\n{result.stderr}")

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


def generate_export_options(
    signing: str,
    destination: str,
    profile: str | None,
    certificate: str | None,
    output_dir: str,
) -> str:
    """Generate ExportOptions.plist and return its path.

    Args:
        signing: "auto" or "manual"
        destination: "appstore" or "testflight" (reserved for future use; both currently use app-store-connect method)
        profile: Provisioning profile path (required for manual signing)
        certificate: Certificate name (optional for manual signing)
        output_dir: Directory to write ExportOptions.plist

    Returns:
        Path to generated ExportOptions.plist

    Raises:
        ValueError: If signing is "manual" but profile is None
    """
    if signing == "manual" and not profile:
        raise ValueError("Manual signing requires a provisioning profile")

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
    project: str | None = typer.Option(None, "--project", help="Xcode 项目路径（.xcodeproj 或 .xcworkspace）"),
    scheme: str | None = typer.Option(None, "--scheme", help="Xcode Scheme 名称"),
    configuration: str | None = typer.Option(None, "--configuration", help="构建配置（默认 Release）"),
    output: str | None = typer.Option(None, "--output", help="输出目录（默认 ./build）"),
    signing: str | None = typer.Option(None, "--signing", help="签名方式：auto 或 manual（默认 auto）"),
    profile: str | None = typer.Option(None, "--profile", help="手动签名：Provisioning Profile 路径"),
    certificate: str | None = typer.Option(None, "--certificate", help="手动签名：证书名称"),
    destination: str | None = typer.Option(None, "--destination", help="导出类型：appstore 或 testflight（默认 appstore）"),
    app: str | None = typer.Option(None, "--app", help="App profile 名称"),
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
        configuration=configuration or "Release",
        output=output or config.build_output,
        signing=signing or config.build_signing,
        profile=profile,
        certificate=certificate,
        destination=destination or "appstore",
        dry_run=dry_run,
    )
    if ipa:
        typer.echo(f"\n✅ 构建完成: {ipa}")


def upload_ipa(
    ipa_path: str,
    issuer_id: str,
    key_id: str,
    key_file: str,
    destination: str,
) -> None:
    """Upload .ipa using xcrun altool.

    Note: destination parameter is reserved for future use.
    Currently both testflight and appstore use the same upload method.
    """
    cmd = [
        "xcrun", "altool", "--upload-app",
        "-f", ipa_path,
        "--apiKey", key_id,
        "--apiIssuer", issuer_id,
        "-t", "ios",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Upload failed:\n{result.stderr}")


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
        typer.echo(f"  xcrun altool --upload-app -f {ipa_path}")
        return

    typer.echo("\n  正在上传...")
    upload_ipa(ipa_path, issuer_id, key_id, key_file, destination)
    typer.echo("  ✅ 上传成功")


def cmd_deploy(
    ipa: str = typer.Option(..., "--ipa", help=".ipa 文件路径"),
    destination: str | None = typer.Option(None, "--destination", help="上传目标：testflight 或 appstore（默认 testflight）"),
    app: str | None = typer.Option(None, "--app", help="App profile 名称"),
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
            destination=destination or "testflight",
            dry_run=dry_run,
        )
    except RuntimeError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(1)
