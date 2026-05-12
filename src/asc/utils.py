"""Shared utility functions used across command modules"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Optional

import typer

from asc.constants import CSV_LOCALE_TO_ASC, normalize_locale_code


def extract_locale(raw_lang: str) -> str:
    """从 '简体中文(zh-Hans)' 或 '英文(en-US)' 格式中提取 locale 代码"""
    m = re.search(r"\(([^)]+)\)", raw_lang)
    if m:
        return normalize_locale_code(m.group(1))
    return normalize_locale_code(raw_lang.strip())


def parse_csv(csv_path: str) -> list[dict]:
    """解析 CSV 元数据文件，返回每个语言的元数据字典列表"""
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        raw_headers = reader.fieldnames or []
        clean_headers = []
        for h in raw_headers:
            stripped = h.strip().strip('"')
            if stripped:
                clean_headers.append((h, stripped))

        results = []
        for row in reader:
            mapped = {}
            for orig_key, clean_key in clean_headers:
                val = row.get(orig_key)
                if val and val.strip():
                    mapped[clean_key] = val.strip()
            if "语言" not in mapped or not mapped["语言"]:
                continue
            mapped["语言"] = extract_locale(mapped["语言"])
            results.append(mapped)

    return results


def resolve_locale(csv_locale: str, existing_locales: list[str]) -> Optional[str]:
    """将 CSV 中的语言代码映射到 ASC 中实际存在的 locale"""
    csv_locale = normalize_locale_code(csv_locale)

    if csv_locale in existing_locales:
        return csv_locale

    asc_locale = CSV_LOCALE_TO_ASC.get(csv_locale)
    if asc_locale and asc_locale in existing_locales:
        return asc_locale

    for existing in existing_locales:
        if existing.startswith(csv_locale):
            return existing

    return asc_locale or csv_locale


def md5_of_file(file_path: Path) -> str:
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def is_interactive() -> bool:
    """Check if running in an interactive TTY environment."""
    import sys
    return sys.stdin.isatty()


def list_valid_profiles(config: "Config") -> list[tuple[str, dict]]:
    """Return list of (app_name, profile_data) tuples for profiles with complete credentials."""
    all_apps = config.list_apps()
    valid = []
    for app_name in all_apps:
        profile = config.get_app_profile(app_name)
        if profile and profile.get("issuer_id") and profile.get("key_id") and profile.get("key_file"):
            valid.append((app_name, profile))
    return valid


def resolve_app_profile(app_name: Optional[str], config: "Config") -> str:
    """Resolve app profile by name or interactive selection.

    Returns:
        The selected app name (string).

    Exits with error if:
        - app_name provided but not found or has incomplete credentials
        - app_name not provided and non-interactive
        - no valid profiles exist
        - user selects invalid profile
    """
    from asc.i18n import t

    # If app_name provided, validate it
    if app_name:
        profile = config.get_app_profile(app_name)
        if not profile:
            typer.echo(t({
                'en': f'App profile "{app_name}" not found.\n'
                      'Please use --app or set ASC_APP environment variable.',
                'zh': f'未找到 App 配置 "{app_name}"。\n'
                      '请使用 --app 或设置 ASC_APP 环境变量。'
            }), err=True)
            raise typer.Exit(1)
        if not (profile.get("issuer_id") and profile.get("key_id") and profile.get("key_file")):
            typer.echo(t({
                'en': f'{app_name} is missing required credentials (issuer_id, key_id, key_file).\n'
                      'Please run "asc app edit {app_name}" to fix.',
                'zh': f'{app_name} 缺少必要的凭证信息（issuer_id, key_id, key_file）。\n'
                      '请先运行 "asc app edit {app_name}" 补充配置。'
            }), err=True)
            raise typer.Exit(1)
        return app_name

    # No app_name provided
    if not is_interactive():
        typer.echo(t({
            'en': 'Non-interactive environment detected. Please use --app or set ASC_APP environment variable.',
            'zh': '检测到非交互式环境，请使用 --app 或设置 ASC_APP 环境变量。'
        }), err=True)
        raise typer.Exit(1)

    # Interactive: show profile list
    valid_profiles = list_valid_profiles(config)
    if not valid_profiles:
        typer.echo(t({
            'en': 'No app profiles configured.\n'
                  'Please run "asc app add <name>" to add a profile, or "asc init" in your project root.',
            'zh': '未检测到任何 App 配置。\n'
                  '请先运行 "asc app add <name>" 添加配置，或在项目根目录运行 "asc init"。'
        }), err=True)
        raise typer.Exit(1)

    typer.echo(t({
        'en': 'Select an app profile to use:',
        'zh': '请选择要使用的 App 配置：'
    }))
    for i, (name, _profile) in enumerate(valid_profiles, 1):
        typer.echo(f'  {i}) {name}')

    typer.echo(t({
        'en': 'Enter your choice',
        'zh': '请输入选择'
    }) + ': ', err=False)

    try:
        choice = input().strip()
        idx = int(choice) - 1
        if idx < 0 or idx >= len(valid_profiles):
            raise ValueError("out of range")
    except (ValueError, EOFError, KeyboardInterrupt):
        typer.echo()
        raise typer.Exit(1)

    selected_name, selected_profile = valid_profiles[idx]
    # Validate selected profile has complete credentials (belt and suspenders)
    if not (selected_profile.get("issuer_id") and selected_profile.get("key_id") and selected_profile.get("key_file")):
        typer.echo(t({
            'en': f'{selected_name} is missing required credentials (issuer_id, key_id, key_file).\n'
                  'Please run "asc app edit {selected_name}" to fix.',
            'zh': f'{selected_name} 缺少必要的凭证信息（issuer_id, key_id, key_file）。\n'
                  '请先运行 "asc app edit {selected_name}" 补充配置。'
        }), err=True)
        raise typer.Exit(1)

    return selected_name


def make_api_from_config(config, app_id_override: Optional[str] = None):
    """Build an AppStoreConnectAPI instance from config, validating required fields"""
    from asc.api import AppStoreConnectAPI

    issuer_id = config.issuer_id
    key_id = config.key_id
    key_file = config.key_file
    app_id = app_id_override or config.app_id

    missing = []
    if not issuer_id:
        missing.append("ISSUER_ID / issuer_id")
    if not key_id:
        missing.append("KEY_ID / key_id")
    if not key_file:
        missing.append("KEY_FILE / key_file")
    if not app_id:
        missing.append("APP_ID / app_id")
    if missing:
        typer.echo(
            f"❌ Missing required config: {', '.join(missing)}\n"
            "Run 'asc app add <name>' to configure an app profile, or set environment variables.",
            err=True,
        )
        raise typer.Exit(1)

    return AppStoreConnectAPI(issuer_id, key_id, key_file), app_id


def detect_local_app_config(project_root: Path) -> Optional[dict]:
    """检测项目本地 AppStore/Config/.env 配置。

    Returns:
        dict with keys: issuer_id, key_id, key_file, app_id, project_name,
        screenshots_path, csv_path, iap_path, env_file_path
        或 None（如果 .env 不存在或不完整）
    """
    env_file = project_root / "AppStore" / "Config" / ".env"
    if not env_file.exists():
        return None

    env_vars: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip("'\"")
        env_vars[k.strip()] = v

    required = ["ISSUER_ID", "KEY_ID", "KEY_FILE", "APP_ID"]
    if not all(env_vars.get(k) for k in required):
        return None

    data_dir = project_root / "AppStore" / "data"
    screenshots_path = str(data_dir / "screenshots") if (data_dir / "screenshots").exists() else ""
    csv_path = str(data_dir / "appstore_info.csv") if (data_dir / "appstore_info.csv").exists() else ""
    iap_path = str(data_dir / "iap_packages.json") if (data_dir / "iap_packages.json").exists() else ""

    return {
        "issuer_id": env_vars.get("ISSUER_ID", ""),
        "key_id": env_vars.get("KEY_ID", ""),
        "key_file": env_vars.get("KEY_FILE", ""),
        "app_id": env_vars.get("APP_ID", ""),
        "project_name": project_root.name,
        "screenshots_path": screenshots_path,
        "csv_path": csv_path,
        "iap_path": iap_path,
        "env_file_path": str(env_file),
    }


def is_local_config_imported(local_config: Optional[dict], existing_profiles: list[dict]) -> bool:
    """检查 local_config 的凭证是否已对应某个已导入的 profile。"""
    if not local_config:
        return False
    for profile in existing_profiles:
        if (profile.get("issuer_id") == local_config.get("issuer_id")
                and profile.get("key_id") == local_config.get("key_id")
                and profile.get("app_id") == local_config.get("app_id")):
            return True
    return False
