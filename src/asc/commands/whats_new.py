"""What's New (release notes) upload command"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from asc.config import Config
from asc.utils import make_api_from_config, resolve_locale


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
        elif current_locale is None and stripped.endswith(":"):
            current_locale = stripped[:-1].strip()
        elif (
            current_locale is None
            and ":" in stripped
            and len(stripped.split(":")[0]) < 20
        ):
            parts = stripped.split(":", 1)
            current_locale = parts[0].strip()
            if parts[1].strip():
                current_lines.append(parts[1].strip())
        elif current_locale:
            current_lines.append(line.rstrip())

    if current_locale and current_lines:
        entries[current_locale] = "\n".join(current_lines).strip()

    return entries


def cmd_whats_new(
    text: Optional[str] = typer.Option(
        None, "--text", help="Release notes text (all locales)"
    ),
    file: Optional[str] = typer.Option(
        None, "--file", help="Path to multi-locale whats_new.txt"
    ),
    locales: Optional[str] = typer.Option(
        None, "--locales", help="Comma-separated locales"
    ),
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Update What's New (release notes)"""
    if not text and not file:
        typer.echo("❌ 请指定 --text 或 --file", err=True)
        raise typer.Exit(1)

    config = Config(app)
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
