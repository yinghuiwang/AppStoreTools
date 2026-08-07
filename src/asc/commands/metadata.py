"""Metadata upload commands"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer

from asc.config import Config
from asc.error_handler import get_action_hint
from asc.guard import Guard, GuardViolationError
from asc.progress import ProcessCanceled
from asc.reporting import TaskReporter, make_cli_reporter
from asc.utils import make_api_from_config, parse_csv, resolve_locale, resolve_app_profile
from asc.i18n import t, HELP, ERRORS


def _select_app_info_id(app_infos: list[dict], version_id: str, version_state: str) -> str:
    """Pick the App Info that belongs to the editable version when possible."""
    relation_keys = ("appStoreVersions", "versions")
    for app_info in app_infos:
        relationships = app_info.get("relationships", {})
        for key in relation_keys:
            rel = relationships.get(key, {}).get("data")
            if isinstance(rel, list):
                if any(item.get("id") == version_id for item in rel if isinstance(item, dict)):
                    return app_info["id"]
            elif isinstance(rel, dict) and rel.get("id") == version_id:
                return app_info["id"]

    for app_info in app_infos:
        attrs = app_info.get("attributes", {})
        state = attrs.get("state") or attrs.get("appStoreState")
        if state == version_state:
            return app_info["id"]

    editable_states = {
        "PREPARE_FOR_SUBMISSION",
        "DEVELOPER_REJECTED",
        "REJECTED",
        "METADATA_REJECTED",
    }
    for app_info in app_infos:
        attrs = app_info.get("attributes", {})
        state = attrs.get("state") or attrs.get("appStoreState")
        if state in editable_states:
            return app_info["id"]

    return app_infos[0]["id"]


def _upload_metadata_core(
    api,
    app_id: str,
    metadata_list: list[dict],
    dry_run: bool = False,
    include_version_fields: Optional[set[str]] = None,
    app_profile: str = "",
    cancel_event=None,
    reporter: TaskReporter | None = None,
    verbose: bool = False,
    manage_phases: bool = True,
    finalize: bool = True,
):
    """Core metadata upload logic"""
    if cancel_event is not None:
        api.cancel_event = cancel_event
    if reporter is None:
        reporter = make_cli_reporter(verbose=verbose)

    if manage_phases:
        reporter.set_phases([
            ("check", 5, "校验"),
            ("locales", 95, "上传"),
        ])
    reporter.phase("check")

    reporter.log("=" * 60)
    reporter.log("📝 上传元数据")
    reporter.log("=" * 60)
    if app_profile:
        reporter.log(f"  App Profile: {app_profile}")

    version = api.get_editable_version(app_id)
    if not version:
        msg = t(ERRORS["no_editable_version"])
        reporter.fail(f"❌ {msg}")
        raise RuntimeError(msg)
    version_id = version["id"]
    version_string = version["attributes"].get("versionString", "?")
    version_state = version["attributes"].get("appStoreState") or version[
        "attributes"
    ].get("appVersionState", "?")
    reporter.log(f"  版本: {version_string} (状态: {version_state})")
    reporter.log(f"  版本 ID: {version_id}")

    app_infos = api.get_app_infos(app_id)
    if not app_infos:
        msg = t(ERRORS["no_app_info"])
        reporter.fail(f"❌ {msg}")
        raise RuntimeError(msg)
    app_info_id = _select_app_info_id(app_infos, version_id, version_state)
    reporter.log(f"  App Info ID: {app_info_id}")

    info_locs = api.get_app_info_localizations(app_info_id)
    info_loc_map = {loc["attributes"]["locale"]: loc for loc in info_locs}
    existing_info_locales = list(info_loc_map.keys())
    reporter.log(f"  已有 App Info 语言: {existing_info_locales}")

    ver_locs = api.get_version_localizations(version_id)
    ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}
    existing_ver_locales = list(ver_loc_map.keys())
    reporter.log(f"  已有版本语言: {existing_ver_locales}")

    reporter.progress(1, 1, msg="ok")
    reporter.phase("locales")

    total_locales = len(metadata_list)
    for idx, meta in enumerate(metadata_list):
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCanceled("metadata upload canceled")
        csv_locale = meta["locale"]
        info_locale = resolve_locale(csv_locale, existing_info_locales)
        ver_locale = resolve_locale(csv_locale, existing_ver_locales)
        reporter.log(
            f"  ── 语言: {csv_locale} → App Info: {info_locale}, 版本: {ver_locale} ──"
        )

        name = meta.get("name", "")
        subtitle = meta.get("subtitle", "")
        privacy_policy_url = meta.get("privacyPolicyUrl", "")

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
                reporter.debug(f"    应用名称: {name}")
            if subtitle:
                reporter.debug(f"    副标题: {subtitle}")
            if privacy_policy_url:
                reporter.debug(f"    隐私政策: {privacy_policy_url}")

            if not dry_run:
                if info_locale in info_loc_map:
                    api.update_app_info_localization(
                        info_loc_map[info_locale]["id"], info_attrs
                    )
                    reporter.log("    ✅ 已更新 App Info 本地化")
                else:
                    api.create_app_info_localization(
                        app_info_id, info_locale, info_attrs
                    )
                    reporter.log("    ✅ 已创建 App Info 本地化")
                    existing_info_locales.append(info_locale)
            else:
                reporter.log("    ⏭ App Info 本地化（dry-run）")

        description = meta.get("description", "")
        keywords = meta.get("keywords", "")
        support_url = meta.get("supportUrl", "")
        marketing_url = meta.get("marketingUrl", "")

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
            reporter.debug(f"    描述: {desc_preview}")
            if keywords:
                reporter.debug(
                    f"    关键词: {keywords[:60]}{'...' if len(keywords) > 60 else ''}"
                )
            if support_url:
                reporter.debug(f"    技术支持: {support_url}")
            if marketing_url:
                reporter.debug(f"    营销网站: {marketing_url}")

            if not dry_run:
                if ver_locale in ver_loc_map:
                    api.update_version_localization(
                        ver_loc_map[ver_locale]["id"], ver_attrs
                    )
                    reporter.log("    ✅ 已更新版本本地化")
                else:
                    try:
                        api.create_version_localization(
                            version_id, ver_locale, ver_attrs
                        )
                        reporter.log("    ✅ 已创建版本本地化")
                    except Exception as e:
                        if "409" in str(e) or "already exists" in str(e):
                            reporter.log("    ⚠️  版本本地化已存在，重新获取后更新...")
                            ver_locs = api.get_version_localizations(version_id)
                            ver_loc_map = {
                                loc["attributes"]["locale"]: loc for loc in ver_locs
                            }
                            if ver_locale in ver_loc_map:
                                api.update_version_localization(
                                    ver_loc_map[ver_locale]["id"], ver_attrs
                                )
                                reporter.log("    ✅ 已更新版本本地化")
                            else:
                                reporter.log(f"    ❌ 无法处理版本本地化: {e}")
                        else:
                            raise
            else:
                reporter.log("    ⏭ 版本本地化（dry-run）")

        if not info_attrs and not ver_attrs:
            reporter.log("    ⏭ 无字段可更新，已跳过")

        current_idx = idx + 1
        reporter.progress(
            current_idx,
            total_locales,
            msg=f"元数据 {current_idx}/{total_locales} 语言",
        )

    if finalize:
        reporter.done("元数据上传完成")
    else:
        reporter.log("元数据上传完成")


def _url_phase_plan() -> list[tuple[str, int, str]]:
    """Single update phase for set-*-url commands."""
    return [("update", 100, "更新")]


def _update_app_info_field_core(
    api,
    app_id: str,
    field_key: str,
    field_label: str,
    field_value: str,
    locales: Optional[list[str]] = None,
    dry_run: bool = False,
    cancel_event=None,
    reporter: TaskReporter | None = None,
    verbose: bool = False,
):
    """Core implementation for set-*-url commands that target appInfoLocalizations"""
    if cancel_event is not None:
        api.cancel_event = cancel_event
    if reporter is None:
        reporter = make_cli_reporter(verbose=verbose)

    reporter.set_phases(_url_phase_plan())
    reporter.phase("update")
    reporter.log("=" * 60)
    reporter.log(f"🔧 更新 App 信息字段 ({field_label})")
    reporter.log("=" * 60)

    app_infos = api.get_app_infos(app_id)
    if not app_infos:
        msg = f"❌ {t(ERRORS['no_app_info'])}"
        reporter.fail(msg)
        raise RuntimeError(msg)
    app_info_id = app_infos[0]["id"]

    info_locs = api.get_app_info_localizations(app_info_id)
    if not info_locs:
        msg = f"❌ {t(ERRORS['app_no_localization'])}"
        reporter.fail(msg)
        raise RuntimeError(msg)

    target_locs = info_locs
    if locales:
        target_locs = [
            loc for loc in info_locs if loc["attributes"]["locale"] in locales
        ]
        if not target_locs:
            available = [loc["attributes"]["locale"] for loc in info_locs]
            msg = f"❌ {t(ERRORS['invalid_locale']).format(locales=available)}"
            reporter.fail(msg)
            raise RuntimeError(msg)

    preview = field_value[:80] + "..." if len(field_value) > 80 else field_value
    reporter.log(f"  {field_label}: {preview}")
    reporter.log(f"  目标语言: {[loc['attributes']['locale'] for loc in target_locs]}")

    # locales × fields written (one field per call)
    total = max(len(target_locs), 1)
    if dry_run:
        reporter.log("  ⚠️  预览模式，不实际更新")
        for i, loc in enumerate(target_locs, start=1):
            locale = loc["attributes"]["locale"]
            reporter.progress(i, total, msg=f"更新 {i}/{total} · {locale}")
        reporter.done(f"✅ {field_label} 预览完成")
        return

    for i, loc in enumerate(target_locs, start=1):
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCanceled(f"{field_label} update canceled")
        locale = loc["attributes"]["locale"]
        loc_id = loc["id"]
        api.update_app_info_localization(loc_id, {field_key: field_value})
        reporter.log(f"  ✅ {locale}: 已更新")
        reporter.progress(i, total, msg=f"更新 {i}/{total} · {locale}")

    reporter.done(f"✅ {field_label} 更新完成")


def _update_version_field_core(
    api,
    app_id: str,
    field_key: str,
    field_label: str,
    field_value: str,
    locales: Optional[list[str]] = None,
    dry_run: bool = False,
    cancel_event=None,
    reporter: TaskReporter | None = None,
    verbose: bool = False,
):
    """Core implementation for set-*-url commands"""
    if cancel_event is not None:
        api.cancel_event = cancel_event
    if reporter is None:
        reporter = make_cli_reporter(verbose=verbose)

    reporter.set_phases(_url_phase_plan())
    reporter.phase("update")
    reporter.log("=" * 60)
    reporter.log(f"🔧 更新版本字段 ({field_label})")
    reporter.log("=" * 60)

    version = api.get_editable_version(app_id)
    if not version:
        msg = f"❌ {t(ERRORS['no_editable_version'])}"
        reporter.fail(msg)
        raise RuntimeError(msg)
    version_id = version["id"]
    version_string = version["attributes"].get("versionString", "?")
    version_state = version["attributes"].get("appStoreState") or version[
        "attributes"
    ].get("appVersionState", "?")
    reporter.log(f"  版本: {version_string} (状态: {version_state})")

    ver_locs = api.get_version_localizations(version_id)
    if not ver_locs:
        msg = f"❌ {t(ERRORS['no_localization'])}"
        reporter.fail(msg)
        raise RuntimeError(msg)

    target_locs = ver_locs
    if locales:
        target_locs = [
            loc for loc in ver_locs if loc["attributes"]["locale"] in locales
        ]
        if not target_locs:
            available = [loc["attributes"]["locale"] for loc in ver_locs]
            msg = f"❌ {t(ERRORS['invalid_locale']).format(locales=available)}"
            reporter.fail(msg)
            raise RuntimeError(msg)

    preview = field_value[:80] + "..." if len(field_value) > 80 else field_value
    reporter.log(f"  {field_label}: {preview}")
    reporter.log(f"  目标语言: {[loc['attributes']['locale'] for loc in target_locs]}")

    # locales × fields written (one field per call)
    total = max(len(target_locs), 1)
    if dry_run:
        reporter.log("  ⚠️  预览模式，不实际更新")
        for i, loc in enumerate(target_locs, start=1):
            locale = loc["attributes"]["locale"]
            reporter.progress(i, total, msg=f"更新 {i}/{total} · {locale}")
        reporter.done(f"✅ {field_label} 预览完成")
        return

    for i, loc in enumerate(target_locs, start=1):
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCanceled(f"{field_label} update canceled")
        locale = loc["attributes"]["locale"]
        loc_id = loc["id"]
        api.update_version_localization(loc_id, {field_key: field_value})
        reporter.log(f"  ✅ {locale}: 已更新")
        reporter.progress(i, total, msg=f"更新 {i}/{total} · {locale}")

    reporter.done(f"✅ {field_label} 更新完成")


# ── typer command functions ──


def cmd_upload(
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['dry_run'])),
    csv: Optional[str] = typer.Option(None, "--csv", "-c", help=t(HELP['csv_file'])),
    screenshots: Optional[str] = typer.Option(
        None, "--screenshots", "-s", help=t(HELP['screenshots_dir'])
    ),
    display_type: Optional[str] = typer.Option(None, "--display-type",
        help=t(HELP['display_type']),
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress logs"),
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
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env
        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        os.environ.pop("_ASC_APP", None)  # Clear so Config uses __local__ sentinel
    app = resolved_app
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
            hint = get_action_hint(e)
            if hint:
                typer.echo(f"💡 {hint}", err=True)
            raise typer.Exit(1)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    try:
        if csv_path.exists():
            metadata_list = parse_csv(str(csv_path))
            print(f"\n📄 从 CSV 读取了 {len(metadata_list)} 个语言的元数据")
            _upload_metadata_core(
                api,
                app_id,
                metadata_list,
                dry_run=dry_run,
                app_profile=app or "",
                verbose=verbose,
            )
        else:
            print(f"\n⚠️  CSV 文件不存在: {csv_path}")
            print(f"💡 可使用 --csv 参数指定其他路径，或参考 'asc upload --help'")
        screenshots_path = Path(screenshots or config.screenshots_path)
        if screenshots_path.exists():
            _upload_screenshots_core(
                api,
                app_id,
                str(screenshots_path),
                display_type,
                dry_run,
                verbose=verbose,
            )
        else:
            print(f"\n⚠️  截图目录不存在: {screenshots_path}")
    except RuntimeError:
        raise typer.Exit(1)
    print("\n" + "=" * 60)
    print("🎉 全部完成！")
    print("=" * 60)


def cmd_metadata(
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['dry_run'])),
    csv: Optional[str] = typer.Option(None, "--csv", "-c", help=t(HELP['csv_file_short'])),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress logs"),
):
    """Upload metadata only: name, subtitle, description, keywords, URLs.

    Metadata is read from the CSV file and uploaded to App Store Connect.
    The CSV should have columns like: locale, name, subtitle, description, keywords.
    Chinese headers (语言, 应用名称, …) are still accepted.

    \b
    Example:
        asc --app myapp metadata
        asc --app myapp metadata --csv custom.csv
        asc --app myapp metadata --csv custom.csv --dry-run
    """
    config = Config(app)
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env
        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        os.environ.pop("_ASC_APP", None)  # Clear so Config uses __local__ sentinel
    app = resolved_app
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
            hint = get_action_hint(e)
            if hint:
                typer.echo(f"💡 {hint}", err=True)
            raise typer.Exit(1)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        typer.echo(f"💡 可使用 --csv 参数指定其他路径，或参考 'asc upload --help'", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    try:
        _upload_metadata_core(
            api,
            app_id,
            metadata_list,
            dry_run=dry_run,
            app_profile=app or "",
            verbose=verbose,
        )
    except RuntimeError:
        raise typer.Exit(1)


def cmd_keywords(
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['dry_run'])),
    csv: Optional[str] = typer.Option(None, "--csv", "-c", help=t(HELP['csv_file_short'])),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress logs"),
):
    """Upload keywords only from CSV.

    Reads the 'keywords' column from your CSV and updates keywords for all
    locales in App Store Connect. Chinese header aliases are still accepted.

    \b
    Example:
        asc --app myapp keywords
        asc --app myapp keywords --dry-run
    """
    config = Config(app)
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env
        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        os.environ.pop("_ASC_APP", None)  # Clear so Config uses __local__ sentinel
    app = resolved_app
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
            hint = get_action_hint(e)
            if hint:
                typer.echo(f"💡 {hint}", err=True)
            raise typer.Exit(1)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        typer.echo(f"💡 可使用 --csv 参数指定其他路径，或参考 'asc upload --help'", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    try:
        _upload_metadata_core(
            api, app_id, metadata_list, dry_run=dry_run, include_version_fields={"keywords"}, app_profile=app or "", verbose=verbose
        )
    except RuntimeError:
        raise typer.Exit(1)


def cmd_support_url(
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['dry_run'])),
    csv: Optional[str] = typer.Option(None, "--csv", "-c", help=t(HELP['csv_file_short'])),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress logs"),
):
    """Upload support URL from CSV.

    Reads 'supportUrl' from your metadata CSV and updates the support URL for
    all locales. Chinese header aliases are still accepted.

    \b
    Example:
        asc --app myapp support-url
        asc --app myapp support-url --dry-run
    """
    config = Config(app)
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env
        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        os.environ.pop("_ASC_APP", None)  # Clear so Config uses __local__ sentinel
    app = resolved_app
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
            hint = get_action_hint(e)
            if hint:
                typer.echo(f"💡 {hint}", err=True)
            raise typer.Exit(1)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        typer.echo(f"💡 可使用 --csv 参数指定其他路径，或参考 'asc upload --help'", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    try:
        _upload_metadata_core(
            api,
            app_id,
            metadata_list,
            dry_run=dry_run,
            include_version_fields={"supportUrl"},
            app_profile=app or "",
            verbose=verbose,
        )
    except RuntimeError:
        raise typer.Exit(1)


def cmd_marketing_url(
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['dry_run'])),
    csv: Optional[str] = typer.Option(None, "--csv", "-c", help=t(HELP['csv_file_short'])),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress logs"),
):
    """Upload marketing URL from CSV.

    Reads 'marketingUrl' from your metadata CSV and updates the marketing URL
    for all locales. Chinese header aliases are still accepted.

    \b
    Example:
        asc --app myapp marketing-url
        asc --app myapp marketing-url --dry-run
    """
    config = Config(app)
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env
        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        os.environ.pop("_ASC_APP", None)  # Clear so Config uses __local__ sentinel
    app = resolved_app
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
            hint = get_action_hint(e)
            if hint:
                typer.echo(f"💡 {hint}", err=True)
            raise typer.Exit(1)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        typer.echo(f"💡 可使用 --csv 参数指定其他路径，或参考 'asc upload --help'", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    try:
        _upload_metadata_core(
            api,
            app_id,
            metadata_list,
            dry_run=dry_run,
            include_version_fields={"marketingUrl"},
            app_profile=app or "",
            verbose=verbose,
        )
    except RuntimeError:
        raise typer.Exit(1)


def cmd_privacy_policy_url(
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['dry_run'])),
    csv: Optional[str] = typer.Option(None, "--csv", "-c", help=t(HELP['csv_file_short'])),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress logs"),
):
    """Upload privacy policy URL from CSV.

    Reads 'privacyPolicyUrl' from your metadata CSV and updates the privacy
    policy URL for all locales. Chinese header aliases are still accepted.

    \b
    Example:
        asc --app myapp privacy-policy-url
        asc --app myapp privacy-policy-url --dry-run
    """
    config = Config(app)
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env
        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        os.environ.pop("_ASC_APP", None)  # Clear so Config uses __local__ sentinel
    app = resolved_app
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
            hint = get_action_hint(e)
            if hint:
                typer.echo(f"💡 {hint}", err=True)
            raise typer.Exit(1)
    api, app_id = make_api_from_config(config)
    csv_path = Path(csv or config.csv_path)
    if not csv_path.exists():
        typer.echo(f"❌ CSV 文件不存在: {csv_path}", err=True)
        typer.echo(f"💡 可使用 --csv 参数指定其他路径，或参考 'asc upload --help'", err=True)
        raise typer.Exit(1)
    metadata_list = parse_csv(str(csv_path))
    try:
        _upload_metadata_core(
            api,
            app_id,
            metadata_list,
            dry_run=dry_run,
            include_version_fields={"privacyPolicyUrl"},
            app_profile=app or "",
            verbose=verbose,
        )
    except RuntimeError:
        raise typer.Exit(1)


def cmd_set_support_url(
    url: str = typer.Option(..., "--text", "-t", help=t(HELP['support_url'])),
    locales: Optional[str] = typer.Option(
        None, "--locales", "-l", help=t(HELP['locales_option'])
    ),
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['preview_without_upload'])),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress logs"),
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
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env
        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        os.environ.pop("_ASC_APP", None)  # Clear so Config uses __local__ sentinel
    app = resolved_app
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
            hint = get_action_hint(e)
            if hint:
                typer.echo(f"💡 {hint}", err=True)
            raise typer.Exit(1)
    api, app_id = make_api_from_config(config)
    locale_list = [l.strip() for l in locales.split(",")] if locales else None
    try:
        _update_version_field_core(
            api, app_id, "supportUrl", "Support URL", url, locale_list, dry_run, verbose=verbose
        )
    except RuntimeError:
        raise typer.Exit(1)


def cmd_set_marketing_url(
    url: str = typer.Option(..., "--text", "-t", help=t(HELP['marketing_url'])),
    locales: Optional[str] = typer.Option(None, "--locales", "-l",
        help=t(HELP['locales_option'])),
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['preview_without_upload'])),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress logs"),
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
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env
        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        os.environ.pop("_ASC_APP", None)  # Clear so Config uses __local__ sentinel
    app = resolved_app
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
            hint = get_action_hint(e)
            if hint:
                typer.echo(f"💡 {hint}", err=True)
            raise typer.Exit(1)
    api, app_id = make_api_from_config(config)
    locale_list = [l.strip() for l in locales.split(",")] if locales else None
    try:
        _update_version_field_core(
            api, app_id, "marketingUrl", "Marketing URL", url, locale_list, dry_run, verbose=verbose
        )
    except RuntimeError:
        raise typer.Exit(1)


def cmd_set_privacy_policy_url(
    url: str = typer.Option(..., "--text", "-t", help=t(HELP['privacy_policy_url'])),
    locales: Optional[str] = typer.Option(None, "--locales", "-l",
        help=t(HELP['locales_option'])),
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['preview_without_upload'])),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress logs"),
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
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env
        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        os.environ.pop("_ASC_APP", None)  # Clear so Config uses __local__ sentinel
    app = resolved_app
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
            hint = get_action_hint(e)
            if hint:
                typer.echo(f"💡 {hint}", err=True)
            raise typer.Exit(1)
    api, app_id = make_api_from_config(config)
    locale_list = [l.strip() for l in locales.split(",")] if locales else None
    try:
        _update_app_info_field_core(
            api,
            app_id,
            "privacyPolicyUrl",
            "Privacy Policy URL",
            url,
            locale_list,
            dry_run,
            verbose=verbose,
        )
    except RuntimeError:
        raise typer.Exit(1)


def cmd_check(
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
):
    """Verify environment and API configuration.

    Checks that your credentials are valid and can connect to App Store Connect.
    Useful to run before doing actual uploads to ensure everything is configured.

    \b
    Example:
        asc --app myapp check
    """
    config = Config(app)
    resolved_app = resolve_app_profile(app, config)
    if resolved_app == "__import__":
        from asc.commands.app_config import _do_import_from_env
        env_path = os.environ.pop("_ASC_IMPORT_LOCAL_CONFIG", "")
        resolved_app = _do_import_from_env(env_path)
    elif resolved_app == "__local__":
        os.environ.pop("_ASC_APP", None)  # Clear so Config uses __local__ sentinel
    app = resolved_app
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
        hint = get_action_hint(e)
        if hint:
            typer.echo(f"💡 {hint}", err=True)
        raise typer.Exit(1)
