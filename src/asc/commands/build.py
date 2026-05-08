"""Build, deploy, and release commands for asc CLI."""
from __future__ import annotations
from typing import Optional

import plistlib
import subprocess
import sys
from pathlib import Path

import typer

from asc.config import Config
from asc.guard import Guard, GuardViolationError
from asc.i18n import t, HELP

from asc.commands.build_inputs import (
    BuildInputsCLI,
    detect_project,
    detect_versions,
    find_matching_archive,
    list_schemes,
    prepare_build_inputs,
    prompt_reuse_archive,
    resolve_interactive,
    ResolvedInputs,
    scan_archives,
)


def _require_macos() -> None:
    if sys.platform != "darwin":
        typer.echo("❌ 此命令仅支持 macOS", err=True)
        raise typer.Exit(2)


def parse_bundle_id_from_profile(profile_path: str) -> str:
    """Extract the bundle identifier from a .mobileprovision file.

    Reads `Entitlements.application-identifier` (e.g. "TEAMID.com.example.app")
    and strips the TeamID prefix.
    """
    cms = subprocess.run(
        ["security", "cms", "-D", "-i", profile_path],
        capture_output=True,
    )
    if cms.returncode != 0 or not cms.stdout:
        raise RuntimeError(
            f"Failed to decode provisioning profile {profile_path}:\n"
            f"{cms.stderr.decode('utf-8', errors='replace')}"
        )

    try:
        plist = plistlib.loads(cms.stdout)
    except Exception as e:
        raise RuntimeError(f"Provisioning profile is not a valid plist: {e}")

    app_id = (plist.get("Entitlements") or {}).get("application-identifier")
    if not app_id or "." not in app_id:
        raise RuntimeError(
            "Provisioning profile is missing Entitlements.application-identifier "
            "or its value is malformed"
        )
    # "TEAMID.com.example.app" -> "com.example.app"
    return app_id.split(".", 1)[1]


def generate_export_options(
    signing: str,
    destination: str,
    profile: Optional[str],
    certificate: Optional[str],
    output_dir: str,
    bundle_id: Optional[str] = None,
) -> str:
    """Generate ExportOptions.plist and return its path.

    Args:
        signing: "auto" or "manual"
        destination: "appstore" or "testflight" (reserved for future use; both currently use app-store-connect method)
        profile: Provisioning profile path (required for manual signing)
        certificate: Certificate name (optional for manual signing)
        output_dir: Directory to write ExportOptions.plist
        bundle_id: Bundle identifier override. If provided and signing is manual,
            uses this instead of parsing from the profile file.

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
            bid = bundle_id or parse_bundle_id_from_profile(profile)
            opts["provisioningProfiles"] = {bid: profile}

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
    resolved: "ResolvedInputs",
    output: str,
    *,
    configuration: str = "Release",
    dry_run: bool = False,
    reuse_archive: Optional[bool] = None,
    interactive: bool = False,
) -> Optional[str]:
    """Core build logic. Returns .ipa path, or None if dry_run."""
    typer.echo(f"\n{'='*56}")
    typer.echo("  asc build")
    typer.echo(f"{'='*56}")
    typer.echo(f"  项目: {resolved.project_path}")
    typer.echo(f"  Scheme: {resolved.scheme}")
    typer.echo(f"  配置: {configuration}")
    typer.echo(f"  签名: {resolved.signing}")
    typer.echo(f"  目标: {resolved.destination}")
    if resolved.signing == "manual":
        typer.echo(f"  Bundle ID: {resolved.bundle_id}")
        typer.echo(f"  证书: {resolved.certificate}")
        typer.echo(f"  描述文件: {resolved.profile}")

    output_dir = Path(output)
    archive_path = str(output_dir / f"{resolved.scheme}.xcarchive")
    export_dir = str(output_dir / "export")

    if dry_run:
        typer.echo("\n[预览] 将运行：")
        typer.echo(f"  xcodebuild archive → {archive_path}")
        typer.echo(f"  xcodebuild -exportArchive → {export_dir}/*.ipa")
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    Path(export_dir).mkdir(parents=True, exist_ok=True)

    # === Step 0: archive reuse check ===
    reuse_path: Optional[str] = None
    if reuse_archive is not False:  # explicit False = forced rebuild
        versions = detect_versions(resolved.project_path, resolved.project_kind, resolved.scheme)
        if versions:
            mv, bn = versions
            archives = scan_archives(output, resolved.scheme)
            match = find_matching_archive(
                archives,
                bundle_id=resolved.bundle_id,
                marketing_version=mv,
                build_number=bn,
            )
            if match:
                if reuse_archive is True:
                    reuse_path = match.path
                    typer.echo(f"\n♻️  复用 archive: {reuse_path}")
                else:
                    if prompt_reuse_archive(match, interactive=interactive):
                        reuse_path = match.path

    typer.echo("\n  ── 步骤 1/3：生成 ExportOptions.plist ──")
    export_options = generate_export_options(
        signing=resolved.signing, destination=resolved.destination,
        profile=resolved.profile, certificate=resolved.certificate,
        output_dir=str(output_dir), bundle_id=resolved.bundle_id,
    )

    if reuse_path:
        archive_path = reuse_path
        typer.echo(f"  ── 步骤 2/3：跳过 archive（复用: {archive_path}） ──")
    else:
        typer.echo("  ── 步骤 2/3：构建 Archive ──")
        run_xcodebuild_archive(
            resolved.project_path, resolved.project_kind, resolved.scheme,
            configuration, archive_path,
        )
        typer.echo(f"  ✅ Archive: {archive_path}")

    typer.echo("  ── 步骤 3/3：导出 IPA ──")
    ipa_path = run_xcodebuild_export(archive_path, export_options, export_dir)
    typer.echo(f"  ✅ IPA: {ipa_path}")
    return ipa_path


def cmd_build(
    project: Optional[str] = typer.Option(None, "--project", "-p", help=t(HELP['project_path'])),
    scheme: Optional[str] = typer.Option(None, "--scheme", "-s", help=t(HELP['scheme_name'])),
    configuration: Optional[str] = typer.Option(None, "--configuration", "-c", help=t(HELP['configuration'])),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=t(HELP['output_dir'])),
    signing: Optional[str] = typer.Option(None, "--signing", help=t(HELP['signing_method'])),
    profile: Optional[str] = typer.Option(None, "--profile", help=t(HELP['profile_path'])),
    certificate: Optional[str] = typer.Option(None, "--certificate", help=t(HELP['certificate_name'])),
    destination: Optional[str] = typer.Option(None, "--destination", help=t(HELP['destination'])),
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['preview_command'])),
    interactive: Optional[bool] = typer.Option(
        None, "--interactive/--no-interactive",
        help="强制开/关交互；不传则按 TTY 自动判断",
    ),
    reuse_archive: Optional[bool] = typer.Option(
        None, "--reuse-archive/--rebuild",
        help="复用同版本 archive / 强制重打；不传则在交互模式下询问",
    ),
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
    cli = BuildInputsCLI(
        project=project, scheme=scheme, signing=signing,
        profile=profile, certificate=certificate, destination=destination,
    )
    try:
        resolved = prepare_build_inputs(
            cli, config, interactive=resolve_interactive(interactive),
        )
    except RuntimeError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(1)

    try:
        ipa = build_core(
            resolved,
            output=output or config.build_output,
            configuration=configuration or "Release",
            dry_run=dry_run,
            reuse_archive=reuse_archive,
            interactive=resolve_interactive(interactive),
        )
    except RuntimeError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(1)

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

    Note: xcrun notarytool is for notarizing macOS binaries, not iOS IPA uploads.
    xcrun altool --upload-app is the correct tool for iOS App Store Connect submissions.
    Note: destination parameter is reserved for future use (both TestFlight and App Store
    use the same altool upload path; App Store Connect routes the build based on version state).
    """
    cmd = [
        "xcrun", "altool", "--upload-app",
        "-f", ipa_path,
        "--apiKey", key_id,
        "--apiIssuer", issuer_id,
        "--p8-file-path", key_file,
        "-t", "ios",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr
    if result.returncode != 0 or "UPLOAD FAILED" in output or "ERROR:" in output:
        raise RuntimeError(f"Upload failed:\n{output}")
    if result.stdout.strip():
        typer.echo(result.stdout.strip())


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
    ipa: str = typer.Option(..., "--ipa", "-i", help=t(HELP['ipa_path'])),
    destination: Optional[str] = typer.Option(None, "--destination", help=t(HELP['upload_destination'])),
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['preview_without_actual_upload'])),
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
    guard = Guard()
    if guard.is_enabled():
        try:
            guard.check_and_enforce(
                app_id=config.app_id or "",
                app_name=app or "",
                key_id=config.key_id or "",
                issuer_id=config.issuer_id or "",
            )
        except GuardViolationError as e:
            typer.echo(f"❌ {e}", err=True)
            raise typer.Exit(1)

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


def cmd_release(
    project: Optional[str] = typer.Option(None, "--project", "-p", help=t(HELP['project_path'])),
    scheme: Optional[str] = typer.Option(None, "--scheme", "-s", help=t(HELP['scheme_name'])),
    destination: Optional[str] = typer.Option(None, "--destination", help=t(HELP['release_destination'])),
    signing: Optional[str] = typer.Option(None, "--signing", help=t(HELP['signing_method'])),
    profile: Optional[str] = typer.Option(None, "--profile", help=t(HELP['profile_path'])),
    certificate: Optional[str] = typer.Option(None, "--certificate", help=t(HELP['certificate_name'])),
    output: Optional[str] = typer.Option(None, "--output", "-o", help=t(HELP['output_dir'])),
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['preview_without_execute'])),
    interactive: Optional[bool] = typer.Option(
        None, "--interactive/--no-interactive",
        help="强制开/关交互；不传则按 TTY 自动判断",
    ),
    reuse_archive: Optional[bool] = typer.Option(
        None, "--reuse-archive/--rebuild",
        help="复用同版本 archive / 强制重打；不传则在交互模式下询问",
    ),
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
    guard = Guard()
    if guard.is_enabled():
        try:
            guard.check_and_enforce(
                app_id=config.app_id or "",
                app_name=app or "",
                key_id=config.key_id or "",
                issuer_id=config.issuer_id or "",
            )
        except GuardViolationError as e:
            typer.echo(f"❌ {e}", err=True)
            raise typer.Exit(1)

    issuer_id = config.issuer_id
    key_id = config.key_id
    key_file = config.key_file

    # Release defaults to testflight if nothing is specified anywhere
    effective_destination = destination or config.build_destination or "testflight"
    cli = BuildInputsCLI(
        project=project, scheme=scheme, signing=signing,
        profile=profile, certificate=certificate,
        destination=effective_destination,
    )
    try:
        resolved = prepare_build_inputs(
            cli, config, interactive=resolve_interactive(interactive),
        )
    except RuntimeError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(1)

    try:
        ipa_path = build_core(
            resolved,
            output=output or config.build_output,
            configuration="Release",
            dry_run=dry_run,
            reuse_archive=reuse_archive,
            interactive=resolve_interactive(interactive),
        )
        if ipa_path:
            deploy_core(
                ipa_path=ipa_path,
                issuer_id=issuer_id or "",
                key_id=key_id or "",
                key_file=key_file or "",
                destination=resolved.destination,
                dry_run=dry_run,
            )
    except RuntimeError as e:
        typer.echo(f"❌ {e}", err=True)
        raise typer.Exit(1)

    if not dry_run:
        typer.echo("\n🎉 发布完成！")
