"""What's New (release notes) upload command"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from asc.config import Config
from asc.guard import Guard, GuardViolationError
from asc.utils import make_api_from_config, resolve_app_profile, resolve_locale
from asc.i18n import t, HELP


def _parse_whats_new_file(file_path: str) -> dict[str, str]:
    """Parse multi-locale whats_new.txt file"""
    content = Path(file_path).read_text(encoding="utf-8-sig").strip()
    entries = {}
    current_locale = None
    current_lines = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if current_locale and current_lines:
                entries[current_locale] = "\n".join(current_lines).strip()
            current_locale = None
            current_lines = []
            continue

        # Detect locale header
        new_locale = None
        new_content = None

        if stripped.endswith(":") and len(stripped[:-1].strip()) < 20 and " " not in stripped[:-1].strip():
            new_locale = stripped[:-1].strip()
        elif ":" in stripped and len(stripped.split(":")[0]) < 20 and " " not in stripped.split(":")[0].strip():
            parts = stripped.split(":", 1)
            new_locale = parts[0].strip()
            new_content = parts[1].strip()

        if new_locale:
            if current_locale and current_lines:
                entries[current_locale] = "\n".join(current_lines).strip()
            current_locale = new_locale
            current_lines = []
            if new_content:
                current_lines.append(new_content)
        elif current_locale:
            current_lines.append(line.rstrip())

    if current_locale and current_lines:
        entries[current_locale] = "\n".join(current_lines).strip()

    return entries


def cmd_whats_new(
    text: Optional[str] = typer.Option(
        None, "--text", "-t", help=t(HELP['release_notes_text'])
    ),
    file: Optional[str] = typer.Option(
        None, "--file", "-f", help=t(HELP['whats_new_file'])
    ),
    locales: Optional[str] = typer.Option(
        None, "--locales", "-l",
        help=t(HELP['whats_new_locales']),
    ),
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['preview_without_upload'])),
):
    """Update What's New (release notes) for the current version.

    You can provide release notes via --text (single text for all locales) or
    --file (multi-locale file with different content per language).

    \b
    File format (whats_new.txt):
    en-US:
    Bug fixes and performance improvements.

    ---
    zh-CN:
    错误修复和性能提升。

    ---
    ja-JP:
    バグ修正とパフォーマンス向上。

    \b
    Alternative format (locale: content on same line):
    en-US: Bug fixes and performance improvements.
    zh-CN: 错误修复和性能提升。

    \b
    Example:
        asc --app myapp whats-new --text "Bug fixes and improvements"
        asc --app myapp whats-new --text "Bug fixes" --locales en-US,zh-CN
        asc --app myapp whats-new --file data/whats_new.txt
    """
    if not text and not file:
        typer.echo("❌ 请指定 --text 或 --file", err=True)
        raise typer.Exit(1)

    config = Config(app)
    app = resolve_app_profile(app, config)
    config = Config(app)
    guard = Guard()
    if guard.is_enabled():
        try:
            guard.check_and_enforce(
                app_id=config.app_id or "",
                app_name=config.app_name or app or "",
                key_id=config.key_id or "",
                issuer_id=config.issuer_id or "",
            )
        except GuardViolationError as e:
            typer.echo(f"❌ {e}", err=True)
            raise typer.Exit(1)
    api, app_id = make_api_from_config(config)

    version = api.get_editable_version(app_id)
    if not version:
        typer.echo("❌ 找不到可编辑的 App Store 版本", err=True)
        raise typer.Exit(1)
    version_id = version["id"]
    version_string = version["attributes"].get("versionString", "?")
    print("\n📋 更新版本描述 (What's New)")
    print(f"  版本: {version_string}")

    ver_locs = api.get_version_localizations(version_id)
    if not ver_locs:
        typer.echo("❌ 该版本没有本地化信息", err=True)
        raise typer.Exit(1)
    ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}
    existing_locales = list(ver_loc_map.keys())

    if file:
        file_path = Path(file)
        if not file_path.exists():
            typer.echo(f"❌ 文件不存在: {file_path}", err=True)
            raise typer.Exit(1)
        entries = _parse_whats_new_file(str(file_path))
        if not entries:
            typer.echo(f"❌ 未从文件中解析到更新描述: {file_path}", err=True)
            raise typer.Exit(1)

        for locale, content in entries.items():
            resolved = resolve_locale(locale, existing_locales)
            preview = content[:60] + "..." if len(content) > 60 else content
            print(f"\n  ── {locale} → {resolved} ──")
            print(f"    内容: {preview}")
            if resolved not in ver_loc_map:
                print(f"    ⚠️  locale '{resolved}' 不存在，跳过")
                continue
            if not dry_run:
                api.update_version_localization(
                    ver_loc_map[resolved]["id"], {"whatsNew": content}
                )
                print("    ✅ 已更新")
    else:
        locale_list = None
        if locales:
            locale_list = [l.strip() for l in locales.split(",")]

        target_locs = ver_locs
        if locale_list:
            target_locs = [
                loc for loc in ver_locs if loc["attributes"]["locale"] in locale_list
            ]
            if not target_locs:
                typer.echo(
                    f"❌ 指定的语言不存在，可用语言: {existing_locales}", err=True
                )
                raise typer.Exit(1)

        preview = text[:80] + "..." if len(text) > 80 else text
        print(f"  更新内容: {preview}")
        print(f"  目标语言: {[loc['attributes']['locale'] for loc in target_locs]}")

        if dry_run:
            print("  ⚠️  预览模式，不实际更新")
            return

        for loc in target_locs:
            locale = loc["attributes"]["locale"]
            loc_id = loc["id"]
            api.update_version_localization(loc_id, {"whatsNew": text})
            print(f"  ✅ {locale}: 已更新")

    print("\n✅ 版本描述更新完成")
