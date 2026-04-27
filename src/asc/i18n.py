"""Internationalization support for CLI help text"""

from __future__ import annotations

import locale
import os
from typing import Dict


def get_system_language() -> str:
    """Get system language, returns 'zh' for Chinese, 'en' for English"""
    # Check ASC_LANG environment variable first
    asc_lang = os.environ.get('ASC_LANG', '').lower()
    if asc_lang in ('zh', 'zh_cn', 'zh-cn', 'chinese'):
        return 'zh'
    elif asc_lang in ('en', 'en_us', 'en-us', 'english'):
        return 'en'

    # Check LANG environment variable
    lang = os.environ.get('LANG', '')
    if lang.startswith('zh'):
        return 'zh'

    # Try locale
    try:
        system_locale = locale.getdefaultlocale()[0]
        if system_locale and system_locale.startswith('zh'):
            return 'zh'
    except:
        pass

    return 'en'


# Current language
LANG = get_system_language()


def t(text_dict: Dict[str, str]) -> str:
    """Translate text based on current language"""
    return text_dict.get(LANG, text_dict.get('en', ''))


# Common help text translations
HELP = {
    'app_profile_name': {
        'en': 'App profile name',
        'zh': 'App 配置名称'
    },
    'dry_run': {
        'en': 'Preview changes without uploading',
        'zh': '预览更改但不上传'
    },
    'csv_file': {
        'en': 'CSV metadata file path [default: data/appstore_info.csv]',
        'zh': 'CSV 元数据文件路径 [默认: data/appstore_info.csv]'
    },
    'csv_file_short': {
        'en': 'CSV file path [default: data/appstore_info.csv]',
        'zh': 'CSV 文件路径 [默认: data/appstore_info.csv]'
    },
    'screenshots_dir': {
        'en': 'Screenshots directory [default: data/screenshots]',
        'zh': '截图目录 [默认: data/screenshots]'
    },
    'display_type': {
        'en': 'Device type override (e.g. APP_IPHONE_67, APP_IPAD_PRO_129_EQ)',
        'zh': '设备类型覆盖（例如 APP_IPHONE_67, APP_IPAD_PRO_129_EQ）'
    },
    'version_info': {
        'en': 'Show version information',
        'zh': '显示版本信息'
    },
    'text_option': {
        'en': 'Text content',
        'zh': '文本内容'
    },
    'file_option': {
        'en': 'File path',
        'zh': '文件路径'
    },
    'locales_option': {
        'en': 'Comma-separated locales (e.g. en-US,zh-CN). If not set, updates all locales.',
        'zh': '逗号分隔的语言代码（例如 en-US,zh-CN）。如果不设置，则更新所有语言。'
    },
    'locales_option_short': {
        'en': 'Comma-separated locales (e.g. en-US,zh-CN)',
        'zh': '逗号分隔的语言代码（例如 en-US,zh-CN）'
    },
    'iap_file': {
        'en': 'Path to IAP JSON config file (see data/iap_packages.example.json for schema)',
        'zh': 'IAP JSON 配置文件路径（参考 data/iap_packages.example.json）'
    },
    'update_existing': {
        'en': 'Update existing IAP/subscriptions. Default: skip items that already exist.',
        'zh': '更新已存在的 IAP/订阅。默认：跳过已存在的项目。'
    },
    'project_path': {
        'en': 'Xcode project path (.xcodeproj or .xcworkspace)',
        'zh': 'Xcode 项目路径（.xcodeproj 或 .xcworkspace）'
    },
    'scheme_name': {
        'en': 'Xcode Scheme name',
        'zh': 'Xcode Scheme 名称'
    },
    'configuration': {
        'en': 'Build configuration (default: Release)',
        'zh': '构建配置（默认：Release）'
    },
    'output_dir': {
        'en': 'Output directory (default: ./build)',
        'zh': '输出目录（默认：./build）'
    },
    'signing_method': {
        'en': 'Signing method: auto or manual (default: auto)',
        'zh': '签名方式：auto 或 manual（默认：auto）'
    },
    'profile_path': {
        'en': 'Manual signing: Provisioning Profile path',
        'zh': '手动签名：Provisioning Profile 路径'
    },
    'certificate_name': {
        'en': 'Manual signing: Certificate name',
        'zh': '手动签名：证书名称'
    },
    'destination': {
        'en': 'Export type: appstore or testflight (default: appstore)',
        'zh': '导出类型：appstore 或 testflight（默认：appstore）'
    },
    'ipa_path': {
        'en': '.ipa file path',
        'zh': '.ipa 文件路径'
    },
    'upload_destination': {
        'en': 'Upload target: testflight or appstore (default: testflight)',
        'zh': '上传目标：testflight 或 appstore（默认：testflight）'
    },
    'release_destination': {
        'en': 'Release target: testflight or appstore (default: testflight)',
        'zh': '发布目标：testflight 或 appstore（默认：testflight）'
    },
    'preview_without_upload': {
        'en': 'Preview without uploading',
        'zh': '预览但不上传'
    },
    'preview_command': {
        'en': 'Preview command but do not execute',
        'zh': '预览命令但不执行'
    },
    'preview_without_actual_upload': {
        'en': 'Preview but do not actually upload',
        'zh': '预览但不实际上传'
    },
    'preview_without_execute': {
        'en': 'Preview but do not execute',
        'zh': '预览但不执行'
    },
    'support_url': {
        'en': 'Support URL to set',
        'zh': '要设置的技术支持链接'
    },
    'marketing_url': {
        'en': 'Marketing URL to set',
        'zh': '要设置的营销网站'
    },
    'privacy_policy_url': {
        'en': 'Privacy Policy URL to set',
        'zh': '要设置的隐私政策网址'
    },
    'release_notes_text': {
        'en': 'Release notes text (applied to all or --locales target locales)',
        'zh': '更新说明文本（应用于所有语言或 --locales 指定的语言）'
    },
    'whats_new_file': {
        'en': 'Path to multi-locale whats_new.txt file',
        'zh': '多语言 whats_new.txt 文件路径'
    },
    'whats_new_locales': {
        'en': 'Comma-separated target locales (e.g. en-US,zh-CN). Only used with --text. If not set, applies to all available locales.',
        'zh': '逗号分隔的目标语言（例如 en-US,zh-CN）。仅与 --text 一起使用。如果不设置，则应用于所有可用语言。'
    },
    'preview_uploads': {
        'en': 'Preview uploads without sending to App Store',
        'zh': '预览上传但不发送到 App Store'
    },
    'screenshots_display_type': {
        'en': 'Device type override (e.g. APP_IPHONE_67, APP_IPAD_PRO_129_EQ, APP_IPHONE_61). Auto-detected from image dimensions if not specified.',
        'zh': '设备类型覆盖（例如 APP_IPHONE_67, APP_IPAD_PRO_129_EQ, APP_IPHONE_61）。如果不指定，则从图片尺寸自动检测。'
    },
    # Command descriptions (shown in command list)
    'cmd_upload': {
        'en': 'Upload all content: metadata (from CSV) + screenshots.',
        'zh': '上传全部内容：元数据（CSV）+ 截图。',
    },
    'cmd_metadata': {
        'en': 'Upload metadata only: name, subtitle, description, keywords, URLs.',
        'zh': '仅上传元数据：名称、副标题、描述、关键词、链接。',
    },
    'cmd_keywords': {
        'en': 'Upload keywords only from CSV.',
        'zh': '仅从 CSV 上传关键词。',
    },
    'cmd_support_url': {
        'en': 'Upload support URL from CSV.',
        'zh': '从 CSV 上传技术支持链接。',
    },
    'cmd_marketing_url': {
        'en': 'Upload marketing URL from CSV.',
        'zh': '从 CSV 上传营销网站链接。',
    },
    'cmd_privacy_policy_url': {
        'en': 'Upload privacy policy URL from CSV.',
        'zh': '从 CSV 上传隐私政策链接。',
    },
    'cmd_set_support_url': {
        'en': 'Set support URL directly (not from CSV).',
        'zh': '直接设置技术支持链接（不从 CSV 读取）。',
    },
    'cmd_set_marketing_url': {
        'en': 'Set marketing URL directly (not from CSV).',
        'zh': '直接设置营销网站链接（不从 CSV 读取）。',
    },
    'cmd_set_privacy_policy_url': {
        'en': 'Set privacy policy URL directly (not from CSV).',
        'zh': '直接设置隐私政策链接（不从 CSV 读取）。',
    },
    'cmd_screenshots': {
        'en': 'Upload screenshots to App Store Connect.',
        'zh': '上传截图到 App Store Connect。',
    },
    'cmd_iap': {
        'en': 'Upload in-app purchases and subscriptions from JSON file.',
        'zh': '从 JSON 文件上传内购和订阅项目。',
    },
    'cmd_whats_new': {
        'en': "Update What's New (release notes) for the current version.",
        'zh': '更新当前版本的"新功能"（更新说明）。',
    },
    'cmd_check': {
        'en': 'Verify environment and API configuration.',
        'zh': '验证环境和 API 配置。',
    },
    'cmd_install': {
        'en': 'Interactive project setup: check environment and configure app profile.',
        'zh': '引导式项目初始化：检查环境，配置 App profile。',
    },
    'cmd_build': {
        'en': 'Build Xcode project and export .ipa file.',
        'zh': '构建 Xcode 项目并导出 .ipa 文件。',
    },
    'cmd_deploy': {
        'en': 'Upload .ipa to TestFlight or App Store.',
        'zh': '上传 .ipa 到 TestFlight 或 App Store。',
    },
    'cmd_release': {
        'en': 'Build and publish to TestFlight or App Store in one step.',
        'zh': '一键构建并发布到 TestFlight 或 App Store。',
    },
    'cmd_app': {
        'en': 'Manage app profiles.',
        'zh': '管理 App 配置。',
    },
    'cmd_guard': {
        'en': 'Manage app binding guard.',
        'zh': '管理 App 绑定守卫功能。',
    },
    'cmd_app_add': {
        'en': 'Add a new app profile.',
        'zh': '添加新的 App 配置。',
    },
    'cmd_app_list': {
        'en': 'List all configured app profiles.',
        'zh': '列出所有已配置的 App。',
    },
    'cmd_app_remove': {
        'en': 'Remove an app profile.',
        'zh': '删除 App 配置。',
    },
    'cmd_app_default': {
        'en': 'Set or update the default app profile.',
        'zh': '设置默认 App 配置。',
    },
    'cmd_app_show': {
        'en': 'Show all fields of an app profile.',
        'zh': '显示 App 配置的所有字段。',
    },
    'cmd_app_edit': {
        'en': 'Interactively re-edit an existing app profile.',
        'zh': '交互式编辑已有的 App 配置。',
    },
    'cmd_app_import': {
        'en': 'Import app profile from project AppStore/Config/.env.',
        'zh': '从项目 AppStore/Config/.env 自动导入 App 配置。',
    },
}

_COMPLETION_INSTALL = {
    'en': 'Install completion for the current shell.',
    'zh': '为当前 Shell 安装命令补全。',
}
_COMPLETION_SHOW = {
    'en': 'Show completion for the current shell, to copy it or customize the installation.',
    'zh': '显示当前 Shell 的补全脚本，可复制或自定义安装。',
}
_HELP_OPTION = {
    'en': 'Show this message and exit.',
    'zh': '显示帮助信息并退出。',
}


def patch_typer_completion() -> None:
    """Patch typer's built-in completion/help option strings to match the current language."""
    if LANG == 'en':
        return  # defaults are already English
    try:
        import typer.completion as tc
        for fn_name in (
            '_install_completion_placeholder_function',
            '_install_completion_no_auto_placeholder_function',
        ):
            fn = getattr(tc, fn_name, None)
            if fn is None or not fn.__defaults__:
                continue
            new_defaults = []
            for d in fn.__defaults__:
                if hasattr(d, 'help') and isinstance(d.help, str):
                    if d.help.lower().startswith('install'):
                        try:
                            d.help = t(_COMPLETION_INSTALL)
                        except Exception:
                            pass
                    elif d.help.lower().startswith('show'):
                        try:
                            d.help = t(_COMPLETION_SHOW)
                        except Exception:
                            pass
                new_defaults.append(d)
            fn.__defaults__ = tuple(new_defaults)
    except Exception:
        pass  # never break the CLI over a cosmetic patch

    # Patch click's internal translation function for --help text
    try:
        import click.core as cc
        _original_gettext = cc._
        _zh_map = {
            'Show this message and exit.': t(_HELP_OPTION),
        }

        def _patched_gettext(x: str) -> str:
            return _zh_map.get(x, _original_gettext(x))

        cc._ = _patched_gettext
    except Exception:
        pass


# Patch click's gettext early so --help text is translated when click builds commands
if LANG != 'en':
    try:
        import click.decorators as _cd
        _orig_gt = _cd._
        _help_zh = t(_HELP_OPTION)

        def _early_gettext(x: str) -> str:
            if x == 'Show this message and exit.':
                return _help_zh
            return _orig_gt(x)

        _cd._ = _early_gettext
    except Exception:
        pass
