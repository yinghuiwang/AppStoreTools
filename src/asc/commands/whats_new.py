"""What's New (release notes) upload command"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Event
from typing import Any, Optional, Sequence

import typer

from asc.config import Config
from asc.error_handler import get_action_hint
from asc.guard import Guard, GuardViolationError
from asc.progress import ProcessCanceled
from asc.reporting import TaskReporter, make_cli_reporter
from asc.utils import make_api_from_config, resolve_app_profile, resolve_locale
from asc.i18n import t, ERRORS, HELP


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


def _whats_new_phase_plan(*, translate: bool, upload: bool = True) -> list[tuple[str, int, str]]:
    """Return phase weights for What's New modes."""
    if translate and upload:
        return [("translate", 60, "翻译"), ("upload", 40, "上传")]
    if translate:
        return [("translate", 100, "翻译")]
    return [("upload", 100, "上传")]


def _make_translator(config: Config):
    from asc.llm import LLMClient
    from asc.services.translator import OpenAITranslator

    llm_client = LLMClient(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
    )
    return OpenAITranslator(llm_client)


def _whats_new_translate_locales(
    translator: Any,
    text: str,
    target_locales: Sequence[str],
    source_locale: str,
    *,
    reporter: TaskReporter,
    cancel_event: Event | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Translate text for each target locale; failed locales log + still advance progress."""
    translations: dict[str, str] = {}
    errors: list[str] = []
    total = len(target_locales)
    if total == 0:
        reporter.progress(1, 1, msg="无目标语言")
        return translations, errors

    for i, locale in enumerate(target_locales, start=1):
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCanceled("whats-new translate canceled")
        try:
            result = translator.translate(text, locale, source_locale)
            if result:
                translations[locale] = result
                preview = result[:50] + "..." if len(result) > 50 else result
                reporter.log(f"  {locale}: {preview}")
            else:
                errors.append(f"{locale}: empty translation")
                reporter.log(f"  ⚠️  {locale}: empty translation")
        except Exception as exc:
            errors.append(f"{locale}: {exc}")
            reporter.log(f"  ⚠️  {locale} 翻译失败: {exc}")
        reporter.progress(i, total, msg=f"翻译 {i}/{total} · {locale}")
    return translations, errors


def _upload_whats_new_locales(
    api: Any,
    ver_loc_map: dict[str, dict],
    entries: dict[str, str],
    *,
    dry_run: bool = False,
    reporter: TaskReporter,
    cancel_event: Event | None = None,
) -> int:
    """Upload What's New per locale. Returns success count. Missing locales skip but still progress."""
    items = list(entries.items())
    total = len(items)
    if total == 0:
        reporter.progress(1, 1, msg="无上传项")
        return 0

    success = 0
    for i, (locale, content) in enumerate(items, start=1):
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCanceled("whats-new upload canceled")
        if locale not in ver_loc_map:
            reporter.log(f"  ⚠️  {locale}: 不存在，跳过")
            reporter.progress(i, total, msg=f"上传 {i}/{total} · {locale}")
            continue
        if dry_run:
            preview = content[:50] + "..." if len(content) > 50 else content
            reporter.log(f"  [DRYRUN] {locale}: {preview}")
            reporter.progress(i, total, msg=f"上传 {i}/{total} · {locale}")
            success += 1
            continue
        api.update_version_localization(ver_loc_map[locale]["id"], {"whatsNew": content})
        reporter.log(f"  ✅ {locale}: 已上传")
        reporter.progress(i, total, msg=f"上传 {i}/{total} · {locale}")
        success += 1
    return success


def _whats_new_core(
    api: Any,
    app_id: str,
    *,
    text: str | None = None,
    translations: dict[str, str] | None = None,
    locales: list[str] | None = None,
    translate: bool = False,
    source_locale: str = "auto",
    dry_run: bool = False,
    translator: Any | None = None,
    reporter: TaskReporter | None = None,
    cancel_event: Event | None = None,
    manage_phases: bool = True,
    finalize: bool = True,
    verbose: bool = False,
    require_editable_state: bool = False,
) -> dict[str, Any]:
    """Shared What's New translate / upload core for CLI and Web.

    Returns dict with keys: success, translations, errors, uploaded, version.
    """
    if reporter is None:
        reporter = make_cli_reporter(verbose=verbose)

    if cancel_event is not None:
        api.cancel_event = cancel_event

    version = api.get_editable_version(app_id)
    if not version:
        reporter.fail(t(ERRORS["no_editable_version"]))
        raise RuntimeError(t(ERRORS["no_editable_version"]))

    if require_editable_state:
        app_store_state = version["attributes"].get("appStoreState", "")
        editable_states = {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED"}
        if app_store_state and app_store_state not in editable_states:
            state_hint = {
                "READY_FOR_SALE": "版本已上架，无法编辑更新说明。如需修改，请创建新版本。",
                "WAITING_FOR_REVIEW": "版本正在等待审核，请先拒绝版本后再修改。",
                "IN_REVIEW": "版本正在审核中，无法修改更新说明。",
                "PENDING_APPLE_RELEASE": "版本待 Apple 发布，无法修改更新说明。",
                "ACCEPTED": "版本已通过审核，无法修改更新说明。",
            }.get(app_store_state, f"当前版本状态「{app_store_state}」不允许编辑更新说明。")
            msg = (
                f"无法编辑 What's New：{state_hint}\n"
                f"💡 可编辑状态：{', '.join(sorted(editable_states))}"
            )
            reporter.fail(msg)
            raise RuntimeError(msg)

    version_id = version["id"]
    version_string = version["attributes"].get("versionString", "?")
    reporter.log(f"📋 更新版本描述 (What's New)  版本: {version_string}")

    ver_locs = api.get_version_localizations(version_id)
    if not ver_locs:
        reporter.fail(t(ERRORS["no_localization"]))
        raise RuntimeError(t(ERRORS["no_localization"]))
    ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}

    do_translate = bool(translate) and translations is None and bool(text)
    do_upload = True
    if manage_phases:
        reporter.set_phases(_whats_new_phase_plan(translate=do_translate, upload=do_upload))

    result_translations = dict(translations) if translations is not None else None
    errors: list[str] = []
    uploaded = 0

    if do_translate:
        if translator is None:
            raise ValueError("translator is required when translate=True")
        source = source_locale or "auto"
        target_locs = ver_locs
        if locales:
            target_locs = [loc for loc in ver_locs if loc["attributes"]["locale"] in locales]
            if not target_locs:
                raise RuntimeError(f"指定的语言不存在，可用语言: {list(ver_loc_map.keys())}")
        target_locales = [
            loc["attributes"]["locale"]
            for loc in target_locs
            if source == "auto" or loc["attributes"]["locale"] != source
        ]
        reporter.phase("translate")
        reporter.log(f"🌐 翻译模式: 源语言={source}, 目标={len(target_locales)} 个语言")
        result_translations, errors = _whats_new_translate_locales(
            translator,
            text or "",
            target_locales,
            source,
            reporter=reporter,
            cancel_event=cancel_event,
        )
        if not result_translations:
            msg = t(ERRORS["llm_all_translations_failed"])
            if errors:
                msg = f"{msg} {'; '.join(errors)}"
            reporter.fail(msg)
            raise RuntimeError(msg)

    # Resolve upload entries
    if result_translations is not None:
        entries = result_translations
    else:
        target_locs = ver_locs
        if locales:
            target_locs = [loc for loc in ver_locs if loc["attributes"]["locale"] in locales]
            if not target_locs:
                raise RuntimeError(f"指定的语言不存在，可用语言: {list(ver_loc_map.keys())}")
        entries = {loc["attributes"]["locale"]: (text or "") for loc in target_locs}

    reporter.phase("upload")
    if dry_run:
        reporter.log("⚠️  预览模式，不实际上传")
    uploaded = _upload_whats_new_locales(
        api,
        ver_loc_map,
        entries,
        dry_run=dry_run,
        reporter=reporter,
        cancel_event=cancel_event,
    )

    if errors:
        reporter.log(f"⚠️  以下语言翻译失败: {', '.join(errors)}")
    summary = f"✅ 版本描述更新完成 ({uploaded}/{len(entries)} 成功)"
    if finalize:
        reporter.done(summary)
    else:
        reporter.log(summary)

    return {
        "success": True,
        "translations": result_translations,
        "errors": errors,
        "uploaded": uploaded,
        "version": version_string,
        "source_locale": source_locale,
    }


def _whats_new_translate_only_core(
    api: Any,
    app_id: str,
    *,
    text: str,
    source_locale: str = "auto",
    translator: Any,
    reporter: TaskReporter | None = None,
    cancel_event: Event | None = None,
    manage_phases: bool = True,
    finalize: bool = True,
    verbose: bool = False,
) -> dict[str, Any]:
    """Preview-translate only: phase translate 100%."""
    if reporter is None:
        reporter = make_cli_reporter(verbose=verbose)

    if cancel_event is not None:
        api.cancel_event = cancel_event

    version = api.get_editable_version(app_id)
    if not version:
        reporter.fail(t(ERRORS["no_editable_version"]))
        raise RuntimeError(t(ERRORS["no_editable_version"]))
    version_id = version["id"]
    ver_locs = api.get_version_localizations(version_id)
    all_locales = [loc["attributes"]["locale"] for loc in ver_locs]
    source = source_locale or "auto"
    target_locales = (
        [locale for locale in all_locales if locale != source]
        if source != "auto"
        else all_locales
    )

    if manage_phases:
        reporter.set_phases(_whats_new_phase_plan(translate=True, upload=False))
    reporter.phase("translate")
    reporter.log(f"🌐 预览翻译: 源语言={source}, 目标={len(target_locales)} 个语言")
    translations, errors = _whats_new_translate_locales(
        translator,
        text,
        target_locales,
        source,
        reporter=reporter,
        cancel_event=cancel_event,
    )
    if not translations:
        msg = "All translations failed."
        if errors:
            msg = f"{msg} {'; '.join(errors)}"
        reporter.fail(msg)
        raise RuntimeError(msg)

    summary = f"✅ 翻译完成 ({len(translations)}/{len(target_locales)})"
    if finalize:
        reporter.done(summary)
    else:
        reporter.log(summary)

    return {
        "success": True,
        "translations": translations,
        "errors": errors,
        "source_locale": source,
    }


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
    translate: bool = typer.Option(
        False, "--translate", "-T",
        help=t(HELP['llm_translate']),
    ),
    source_locale: Optional[str] = typer.Option(
        None, "--source-locale", "-s",
        help=t(HELP['llm_source_locale']),
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed progress logs"),
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
        typer.echo(f"❌ {t(ERRORS['specify_text_or_file'])}", err=True)
        raise typer.Exit(1)

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
    reporter = make_cli_reporter(verbose=verbose)

    if file:
        file_path = Path(file)
        if not file_path.exists():
            typer.echo(f"❌ {t(ERRORS['file_not_found']).format(path=file_path)}", err=True)
            typer.echo("💡 请检查文件路径是否正确，或使用 --text 直接指定内容", err=True)
            raise typer.Exit(1)
        entries = _parse_whats_new_file(str(file_path))
        if not entries:
            typer.echo(f"❌ {t(ERRORS['parse_whats_new_failed']).format(path=file_path)}", err=True)
            typer.echo("💡 请确保文件格式正确，包含有效的更新描述文本", err=True)
            raise typer.Exit(1)

        version = api.get_editable_version(app_id)
        if not version:
            typer.echo(f"❌ {t(ERRORS['no_editable_version'])}", err=True)
            typer.echo("💡 请在 App Store Connect 中确认版本状态为可编辑状态（如 PREPARE_FOR_SUBMISSION）", err=True)
            raise typer.Exit(1)
        version_id = version["id"]
        version_string = version["attributes"].get("versionString", "?")
        reporter.log(f"📋 更新版本描述 (What's New)  版本: {version_string}")
        ver_locs = api.get_version_localizations(version_id)
        if not ver_locs:
            typer.echo(f"❌ {t(ERRORS['no_localization'])}", err=True)
            typer.echo("💡 请先通过 asc metadata 命令上传至少一个本地化描述文件", err=True)
            raise typer.Exit(1)
        existing_locales = [loc["attributes"]["locale"] for loc in ver_locs]
        ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}

        # Resolve file locales then upload-only
        resolved_entries: dict[str, str] = {}
        for locale, content in entries.items():
            resolved = resolve_locale(locale, existing_locales)
            preview = content[:60] + "..." if len(content) > 60 else content
            reporter.log(f"  ── {locale} → {resolved} ──  内容: {preview}")
            if resolved not in ver_loc_map:
                reporter.log(f"    ⚠️  locale '{resolved}' 不存在，跳过")
                continue
            resolved_entries[resolved] = content

        reporter.set_phases(_whats_new_phase_plan(translate=False, upload=True))
        reporter.phase("upload")
        if dry_run:
            reporter.log("⚠️  预览模式，不实际上传")
        _upload_whats_new_locales(
            api,
            ver_loc_map,
            resolved_entries,
            dry_run=dry_run,
            reporter=reporter,
        )
        reporter.done("✅ 版本描述更新完成")
        return

    locale_list = None
    if locales:
        locale_list = [l.strip() for l in locales.split(",")]

    translator = None
    if translate:
        if not text:
            typer.echo(f"❌ {t(ERRORS['llm_translate_requires_text'])}", err=True)
            raise typer.Exit(1)
        if not config.llm_api_key:
            typer.echo(f"❌ {t(ERRORS['llm_api_key_required'])}", err=True)
            raise typer.Exit(1)
        translator = _make_translator(config)

    try:
        _whats_new_core(
            api,
            app_id,
            text=text,
            locales=locale_list,
            translate=translate,
            source_locale=source_locale or "auto",
            dry_run=dry_run,
            translator=translator,
            reporter=reporter,
            verbose=verbose,
        )
    except RuntimeError as exc:
        typer.echo(f"❌ {exc}", err=True)
        raise typer.Exit(1)
