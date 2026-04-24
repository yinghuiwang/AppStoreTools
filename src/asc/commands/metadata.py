"""Metadata upload commands"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from asc.config import Config
from asc.guard import Guard, GuardViolationError
from asc.utils import make_api_from_config, parse_csv, resolve_locale


def _upload_metadata_core(
    api,
    app_id: str,
    metadata_list: list[dict],
    dry_run: bool = False,
    include_version_fields: set[str] | None = None,
):
    """Core metadata upload logic"""
    print("\n" + "=" * 60)
    print("📝 上传元数据")
    print("=" * 60)

    app_infos = api.get_app_infos(app_id)
    if not app_infos:
        print("❌ 找不到 App 信息")
        return
    app_info = app_infos[0]
    app_info_id = app_info["id"]
    print(f"  App Info ID: {app_info_id}")

    version = api.get_editable_version(app_id)
    if not version:
        print("❌ 找不到可编辑的 App Store 版本")
        return
    version_id = version["id"]
    version_string = version["attributes"].get("versionString", "?")
    version_state = version["attributes"].get("appStoreState") or version[
        "attributes"
    ].get("appVersionState", "?")
    print(f"  版本: {version_string} (状态: {version_state})")
    print(f"  版本 ID: {version_id}")

    info_locs = api.get_app_info_localizations(app_info_id)
    info_loc_map = {loc["attributes"]["locale"]: loc for loc in info_locs}
    existing_info_locales = list(info_loc_map.keys())
    print(f"  已有 App Info 语言: {existing_info_locales}")

    ver_locs = api.get_version_localizations(version_id)
    ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}
    existing_ver_locales = list(ver_loc_map.keys())
    print(f"  已有版本语言: {existing_ver_locales}")

    for meta in metadata_list:
        csv_locale = meta["语言"]
        info_locale = resolve_locale(csv_locale, existing_info_locales)
        ver_locale = resolve_locale(csv_locale, existing_ver_locales)
        print(
            f"\n  ── 语言: {csv_locale} → App Info: {info_locale}, 版本: {ver_locale} ──"
        )

        name = meta.get("应用名称", "")
        subtitle = meta.get("副标题", "")
        privacy_policy_url = (
            meta.get("隐私政策网址", "")
            or meta.get("隐私政策链接", "")
            or meta.get("隐私政策URL", "")
        )

        # appInfoLocalizations fields: name, subtitle, privacyPolicyUrl
        info_attrs = {}
        if name and include_version_fields is None:
            info_attrs["name"] = name
        if subtitle and include_version_fields is None:
            info_attrs["subtitle"] = subtitle
        if privacy_policy_url and (
            include_version_fields is None
            or "privacyPolicyUrl" in include_version_fields
        ):
            info_attrs["privacyPolicyUrl"] = privacy_policy_url

        if info_attrs:
            if name:
                print(f"    应用名称: {name}")
            if subtitle:
                print(f"    副标题: {subtitle}")
            if privacy_policy_url:
                print(f"    隐私政策: {privacy_policy_url}")

            if not dry_run:
                if info_locale in info_loc_map:
                    api.update_app_info_localization(
                        info_loc_map[info_locale]["id"], info_attrs
                    )
                    print("    ✅ 已更新 App Info 本地化")
                else:
                    api.create_app_info_localization(
                        app_info_id, info_locale, info_attrs
                    )
                    print("    ✅ 已创建 App Info 本地化")
                    existing_info_locales.append(info_locale)

        description = meta.get("长描述", "")
        keywords = meta.get("关键词", "") or meta.get("关键子", "")
        support_url = meta.get("技术支持网址", "") or meta.get("技术支持链接", "")
        marketing_url = meta.get("营销网站", "") or meta.get("营销网址", "")

        ver_attrs = {}
        if description and (
            include_version_fields is None or "description" in include_version_fields
        ):
            ver_attrs["description"] = description
        if keywords and (
            include_version_fields is None or "keywords" in include_version_fields
        ):
            ver_attrs["keywords"] = keywords
        if support_url and (
            include_version_fields is None or "supportUrl" in include_version_fields
        ):
            ver_attrs["supportUrl"] = support_url
        if marketing_url and (
            include_version_fields is None or "marketingUrl" in include_version_fields
        ):
            ver_attrs["marketingUrl"] = marketing_url

        if ver_attrs:
            desc_preview = (
                description[:60] + "..." if len(description) > 60 else description
            )
            print(f"    描述: {desc_preview}")
            if keywords:
                print(
                    f"    关键词: {keywords[:60]}{'...' if len(keywords) > 60 else ''}"
                )
            if support_url:
                print(f"    技术支持: {support_url}")
            if marketing_url:
                print(f"    营销网站: {marketing_url}")

            if not dry_run:
                if ver_locale in ver_loc_map:
                    api.update_version_localization(
                        ver_loc_map[ver_locale]["id"], ver_attrs
                    )
                    print("    ✅ 已更新版本本地化")
                else:
                    try:
                        api.create_version_localization(
                            version_id, ver_locale, ver_attrs
                        )
                        print("    ✅ 已创建版本本地化")
                    except Exception as e:
                        if "409" in str(e) or "already exists" in str(e):
                            print("    ⚠️  版本本地化已存在，重新获取后更新...")
                            ver_locs = api.get_version_localizations(version_id)
                            ver_loc_map = {
                                loc["attributes"]["locale"]: loc for loc in ver_locs
                            }
                            if ver_locale in ver_loc_map:
                                api.update_version_localization(
                                    ver_loc_map[ver_locale]["id"], ver_attrs
                                )
                                print("    ✅ 已更新版本本地化")
                            else:
                                print(f"    ❌ 无法处理版本本地化: {e}")
                        else:
                            raise

    print("\n✅ 元数据上传完成")


def _update_app_info_field_core(
    api,
    app_id: str,
    field_key: str,
    field_label: str,
    field_value: str,
    locales: list[str] | None = None,
    dry_run: bool = False,
):
    """Core implementation for set-*-url commands that target appInfoLocalizations"""
    print("\n" + "=" * 60)
    print(f"🔧 更新 App 信息字段 ({field_label})")
    print("=" * 60)

    app_infos = api.get_app_infos(app_id)
    if not app_infos:
        print("❌ 找不到 App 信息")
        return
    app_info_id = app_infos[0]["id"]

    info_locs = api.get_app_info_localizations(app_info_id)
    if not info_locs:
        print("❌ 该 App 没有本地化信息")
        return

    target_locs = info_locs
    if locales:
        target_locs = [
            loc for loc in info_locs if loc["attributes"]["locale"] in locales
        ]
        if not target_locs:
            available = [loc["attributes"]["locale"] for loc in info_locs]
            print(f"❌ 指定的语言不存在，可用语言: {available}")
            return

    preview = field_value[:80] + "..." if len(field_value) > 80 else field_value
    print(f"  {field_label}: {preview}")
    print(f"  目标语言: {[loc['attributes']['locale'] for loc in target_locs]}")

    if dry_run:
        print("  ⚠️  预览模式，不实际更新")
        return

    for loc in target_locs:
        locale = loc["attributes"]["locale"]
        loc_id = loc["id"]
        api.update_app_info_localization(loc_id, {field_key: field_value})
        print(f"  ✅ {locale}: 已更新")

    print(f"\n✅ {field_label} 更新完成")


def _update_version_field_core(
    api,
    app_id: str,
    field_key: str,
    field_label: str,
    field_value: str,
    locales: list[str] | None = None,
    dry_run: bool = False,
):
    """Core implementation for set-*-url commands"""
    print("\n" + "=" * 60)
    print(f"🔧 更新版本字段 ({field_label})")
    print("=" * 60)

    version = api.get_editable_version(app_id)
    if not version:
        print("❌ 找不到可编辑的 App Store 版本")
        return
    version_id = version["id"]
    version_string = version["attributes"].get("versionString", "?")
    version_state = version["attributes"].get("appStoreState") or version[
        "attributes"
    ].get("appVersionState", "?")
    print(f"  版本: {version_string} (状态: {version_state})")

    ver_locs = api.get_version_localizations(version_id)
    if not ver_locs:
        print("❌ 该版本没有本地化信息")
        return

    target_locs = ver_locs
    if locales:
        target_locs = [
            loc for loc in ver_locs if loc["attributes"]["locale"] in locales
        ]
        if not target_locs:
            available = [loc["attributes"]["locale"] for loc in ver_locs]
            print(f"❌ 指定的语言不存在，可用语言: {available}")
            return

    preview = field_value[:80] + "..." if len(field_value) > 80 else field_value
    print(f"  {field_label}: {preview}")
    print(f"  目标语言: {[loc['attributes']['locale'] for loc in target_locs]}")

    if dry_run:
        print("  ⚠️  预览模式，不实际更新")
        return

    for loc in target_locs:
        locale = loc["attributes"]["locale"]
        loc_id = loc["id"]
        api.update_version_localization(loc_id, {field_key: field_value})
        print(f"  ✅ {locale}: 已更新")

    print(f"\n✅ {field_label} 更新完成")


# ── typer command functions ──


def cmd_upload(
    app: Optional[str] = typer.Option(None, "--app", help="App profile name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without uploading"),
    csv: Optional[str] = typer.Option(None, "--csv", help="CSV metadata file path [default: data/appstore_info.csv]"),
    screenshots: Optional[str] = typer.Option(
        None, "--screenshots", help="Screenshots directory [default: data/screenshots]"
    ),
    display_type: Optional[str] = typer.Option(None, "--display-type",
        help="Device type override (e.g. APP_IPHONE_67, APP_IPAD_PRO_129_EQ)",
    ),
):
    """Upload all content: metadata (from CSV) + screenshots.

    This command uploads metadata from your CSV file and screenshots from
    the configured directory. Use --dry-run to preview what would be uploaded.

    \b
    Example:
        asc --app myapp upload
        asc --app myapp upload --dry-run
        asc --app myapp upload --csv custom.csv --screenshots ./screenshots
        asc --app myapp upload --display-type APP_IPHONE_67
    """
    from asc.commands.screenshots import _upload_screenshots_core

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
    csv_path = Path(csv or config.csv_path)
    if csv_path.exists():
        metadata_list = parse_csv(str(csv_path))
        print(f"\n📄 从 CSV 读取了 {len(metadata_list)} 个语言的元数据")
        _upload_metadata_core(api, app_id, metadata_list, dry_run=dry_run)
    else:
        print(f"\n⚠️  CSV 文件不存在: {csv_path}")
    screenshots_path = Path(screenshots or config.screenshots_path)
    if screenshots_path.exists():
        _upload_screenshots_core(
            api, app_id, str(screenshots_path), display_type, dry_run
        )
    else:
        print(f"\n⚠️  截图目录不存在: {screenshots_path}")
    print("\n" + "=" * 60)
    print("🎉 全部完成！")
    print("=" * 60)


def cmd_metadata(
    app: Optional[str] = typer.Option(None, "--app", help="App profile name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without uploading"),
    csv: Optional[str] = typer.Option(None, "--csv", help="CSV file path [default: data/appstore_info.csv]"),
):
    """Upload metadata only: name, subtitle, description, keywords, URLs.

    Metadata is read from the CSV file and uploaded to App Store Connect.
    The CSV should have columns like: 语言, 应用名称, 副标题, 长描述, 关键子.

    \b
    Example:
        asc --app myapp metadata
        asc --app myapp metadata --csv custom.csv --dry-run
    """
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
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    _upload_metadata_core(api, app_id, metadata_list, dry_run=dry_run)


def cmd_keywords(
    app: Optional[str] = typer.Option(None, "--app", help="App profile name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without uploading"),
    csv: Optional[str] = typer.Option(None, "--csv", help="CSV file path [default: data/appstore_info.csv]"),
):
    """Upload keywords only from CSV.

    Reads the '关键词' or '关键子' column from your CSV and updates keywords
    for all locales in App Store Connect.

    \b
    Example:
        asc --app myapp keywords
        asc --app myapp keywords --dry-run
    """
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
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    _upload_metadata_core(
        api, app_id, metadata_list, dry_run=dry_run, include_version_fields={"keywords"}
    )


def cmd_support_url(
    app: Optional[str] = typer.Option(None, "--app", help="App profile name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without uploading"),
    csv: Optional[str] = typer.Option(None, "--csv", help="CSV file path [default: data/appstore_info.csv]"),
):
    """Upload support URL from CSV.

    Reads '技术支持网址' or '技术支持链接' from your metadata CSV and
    updates the support URL for all locales.

    \b
    Example:
        asc --app myapp support-url
        asc --app myapp support-url --dry-run
    """
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
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    _upload_metadata_core(
        api,
        app_id,
        metadata_list,
        dry_run=dry_run,
        include_version_fields={"supportUrl"},
    )


def cmd_marketing_url(
    app: Optional[str] = typer.Option(None, "--app", help="App profile name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without uploading"),
    csv: Optional[str] = typer.Option(None, "--csv", help="CSV file path [default: data/appstore_info.csv]"),
):
    """Upload marketing URL from CSV.

    Reads '营销网站' or '营销网址' from your metadata CSV and updates the
    marketing URL for all locales.

    \b
    Example:
        asc --app myapp marketing-url
        asc --app myapp marketing-url --dry-run
    """
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
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    _upload_metadata_core(
        api,
        app_id,
        metadata_list,
        dry_run=dry_run,
        include_version_fields={"marketingUrl"},
    )


def cmd_privacy_policy_url(
    app: Optional[str] = typer.Option(None, "--app", help="App profile name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without uploading"),
    csv: Optional[str] = typer.Option(None, "--csv", help="CSV file path [default: data/appstore_info.csv]"),
):
    """Upload privacy policy URL from CSV.

    Reads '隐私政策网址' or '隐私政策链接' from your metadata CSV and updates
    the privacy policy URL for all locales.

    \b
    Example:
        asc --app myapp privacy-policy-url
        asc --app myapp privacy-policy-url --dry-run
    """
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
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    _upload_metadata_core(
        api,
        app_id,
        metadata_list,
        dry_run=dry_run,
        include_version_fields={"privacyPolicyUrl"},
    )


def cmd_set_support_url(
    url: str = typer.Option(..., "--text", help="Support URL to set"),
    locales: Optional[str] = typer.Option(
        None, "--locales", help="Comma-separated locales (e.g. en-US,zh-CN). If not set, updates all locales."
    ),
    app: Optional[str] = typer.Option(None, "--app", help="App profile name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without uploading"),
):
    """Set support URL directly (not from CSV).

    Unlike 'support-url' which reads from CSV, this command sets a single URL
    for all or specific locales directly via --text.

    \b
    Example:
        asc --app myapp set-support-url --text "https://example.com/support"
        asc --app myapp set-support-url --text "https://example.com/support" --locales en-US,zh-CN
        asc --app myapp set-support-url --text "https://example.com/support" --dry-run
    """
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
    locale_list = [l.strip() for l in locales.split(",")] if locales else None
    _update_version_field_core(
        api, app_id, "supportUrl", "Support URL", url, locale_list, dry_run
    )


def cmd_set_marketing_url(
    url: str = typer.Option(..., "--text", help="Marketing URL to set"),
    locales: Optional[str] = typer.Option(None, "--locales",
        help="Comma-separated locales (e.g. en-US,zh-CN). If not set, updates all locales."),
    app: Optional[str] = typer.Option(None, "--app", help="App profile name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without uploading"),
):
    """Set marketing URL directly (not from CSV).

    Unlike 'marketing-url' which reads from CSV, this command sets a single URL
    for all or specific locales directly via --text.

    \b
    Example:
        asc --app myapp set-marketing-url --text "https://example.com"
        asc --app myapp set-marketing-url --text "https://example.com" --locales en-US,zh-CN
    """
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
    locale_list = [l.strip() for l in locales.split(",")] if locales else None
    _update_version_field_core(
        api, app_id, "marketingUrl", "Marketing URL", url, locale_list, dry_run
    )


def cmd_set_privacy_policy_url(
    url: str = typer.Option(..., "--text", help="Privacy Policy URL to set"),
    locales: Optional[str] = typer.Option(None, "--locales",
        help="Comma-separated locales (e.g. en-US,zh-CN). If not set, updates all locales."),
    app: Optional[str] = typer.Option(None, "--app", help="App profile name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without uploading"),
):
    """Set privacy policy URL directly (not from CSV).

    Unlike 'privacy-policy-url' which reads from CSV, this command sets a single URL
    for all or specific locales directly via --text.

    \b
    Example:
        asc --app myapp set-privacy-policy-url --text "https://example.com/privacy"
        asc --app myapp set-privacy-policy-url --text "https://example.com/privacy" --locales en-US
    """
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
    locale_list = [l.strip() for l in locales.split(",")] if locales else None
    _update_app_info_field_core(
        api,
        app_id,
        "privacyPolicyUrl",
        "Privacy Policy URL",
        url,
        locale_list,
        dry_run,
    )


def cmd_check(
    app: Optional[str] = typer.Option(None, "--app", help="App profile name"),
):
    """Verify environment and API configuration.

    Checks that your credentials are valid and can connect to App Store Connect.
    Useful to run before doing actual uploads to ensure everything is configured.

    \b
    Example:
        asc --app myapp check
    """
    config = Config(app)
    api, app_id = make_api_from_config(config)
    print("\n🔐 验证 API 连接...")
    try:
        app_resp = api.get_app(app_id)
        app_name = app_resp["data"]["attributes"]["name"]
        bundle_id = app_resp["data"]["attributes"]["bundleId"]
        print(f"  ✅ 已连接: {app_name} ({bundle_id})")
    except Exception as e:
        typer.echo(f"  ❌ API 连接失败: {e}", err=True)
        raise typer.Exit(1)
