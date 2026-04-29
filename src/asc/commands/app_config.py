"""App profile management commands"""

from __future__ import annotations

import importlib.resources
import shutil
from pathlib import Path
from typing import Optional

import typer

from asc.config import Config


def cmd_app_add(
    name: str = typer.Argument(..., help="Profile name for this app (used with --app)"),
):
    """Interactively add a new app profile.

    This command guides you through setting up credentials for App Store Connect API.
    You'll need your App Store Connect API key details (Issuer ID, Key ID, .p8 private key)
    and your app's numeric ID.

    \b
    The profile stores:
    - API credentials (Issuer ID, Key ID, key file path)
    - Default paths for CSV and screenshots
    - App ID

    \b
    Example:
        asc app add myapp
        asc app add production-app
    """
    typer.echo(f"Adding app profile: {name}")
    typer.echo("Enter your App Store Connect credentials:")

    issuer_id = typer.prompt("  Issuer ID")
    key_id = typer.prompt("  Key ID")
    key_file_input = typer.prompt("  Path to .p8 private key file")
    app_id = typer.prompt("  App ID (numeric)")

    typer.echo("\nEnter default data paths (press Enter to use defaults):")
    csv_path = typer.prompt(
        "  CSV metadata file path", default="data/appstore_info.csv"
    )
    screenshots_path = typer.prompt(
        "  Screenshots directory", default="data/screenshots"
    )

    # Strip quotes and whitespace from path input
    key_file_clean = key_file_input.strip().strip("'\"")
    key_path = Path(key_file_clean).expanduser()
    if not key_path.exists():
        typer.echo(f"❌ Key file not found: {key_path}", err=True)
        raise typer.Exit(1)

    global_keys_dir = Path.home() / ".config" / "asc" / "keys"
    global_keys_dir.mkdir(parents=True, exist_ok=True)
    dest_key = global_keys_dir / key_path.name
    if not dest_key.exists():
        shutil.copy2(key_path, dest_key)
        typer.echo(f"  ✅ Key file copied to {dest_key}")

    config = Config()
    config.save_app_profile(
        name, issuer_id, key_id, str(dest_key), app_id, csv_path, screenshots_path
    )
    typer.echo(f"\n✅ App profile '{name}' saved.")
    typer.echo(f"   Use: asc --app {name} upload")


def cmd_app_list():
    """List all configured app profiles.

    Shows all app profiles that have been configured via 'asc app add'.

    \b
    Example:
        asc app list
    """
    config = Config()
    apps = config.list_apps()
    if not apps:
        typer.echo("No app profiles configured.")
        typer.echo("Run: asc app add <name>")
        return
    default = config.app_name
    typer.echo("Configured app profiles:")
    for app_name in apps:
        marker = " (default)" if app_name == default else ""
        typer.echo(f"  • {app_name}{marker}")


def cmd_app_remove(
    name: str = typer.Argument(..., help="Profile name to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Remove an app profile.

    Deletes the profile configuration saved in ~/.config/asc/profiles/.

    \b
    Example:
        asc app remove myapp
        asc app remove myapp --yes
    """
    if not yes:
        confirmed = typer.confirm(f"Remove app profile '{name}'?")
        if not confirmed:
            raise typer.Abort()
    config = Config()
    config.remove_app_profile(name)
    typer.echo(f"✅ App profile '{name}' removed.")


def cmd_app_default(
    name: str = typer.Argument(..., help="Profile name to set as default"),
):
    """Set or update the default app profile.

    Writes the default app to .asc/config.toml in the current directory.
    When no --app is specified, commands will use this default profile.

    \b
    Example:
        asc app default myapp
        asc app default production-app
    """
    local_dir = Path.cwd() / ".asc"
    local_dir.mkdir(parents=True, exist_ok=True)
    config_file = local_dir / "config.toml"

    # Check if profile exists
    config = Config()
    apps = config.list_apps()
    if name not in apps:
        typer.echo(f"❌ Profile '{name}' not found. Available profiles:", err=True)
        for app_name in apps:
            typer.echo(f"  • {app_name}")
        raise typer.Exit(1)

    _write_local_default(local_dir, name)
    typer.echo(f"✅ Default app profile set to '{name}'")
    typer.echo(f"   Config written to: {config_file.relative_to(Path.cwd())}")
    typer.echo(f"   Run 'asc upload' without --app to use this default.")


def cmd_app_show(
    name: str = typer.Argument(..., help="Profile name to display"),
):
    """Show all fields of an app profile.

    \b
    Example:
        asc app show myapp
    """
    config = Config()
    profile = config.get_app_profile(name)
    if profile is None:
        typer.echo(f"❌ Profile '{name}' not found.", err=True)
        raise typer.Exit(1)

    typer.echo(f"App profile: {name}")
    typer.echo(f"  Issuer ID:        {profile['issuer_id']}")
    typer.echo(f"  Key ID:           {profile['key_id']}")
    typer.echo(f"  Key file:         {profile['key_file']}")
    typer.echo(f"  App ID:           {profile['app_id']}")
    typer.echo(f"  CSV path:         {profile['csv']}")
    typer.echo(f"  Screenshots path: {profile['screenshots']}")


def cmd_app_edit(
    name: str = typer.Argument(..., help="Profile name to edit"),
):
    """Interactively re-edit an existing app profile.

    Re-prompts all fields with current values as defaults.
    Press Enter to keep the existing value for any field.

    \b
    Example:
        asc app edit myapp
    """
    config = Config()
    profile = config.get_app_profile(name)
    if profile is None:
        typer.echo(f"❌ Profile '{name}' not found.", err=True)
        raise typer.Exit(1)

    typer.echo(f"Editing app profile: {name}")
    typer.echo("Press Enter to keep the current value.\n")

    issuer_id = typer.prompt("  Issuer ID", default=profile["issuer_id"])
    key_id = typer.prompt("  Key ID", default=profile["key_id"])
    key_file_input = typer.prompt("  Path to .p8 private key file", default=profile["key_file"])
    app_id = typer.prompt("  App ID (numeric)", default=profile["app_id"])
    csv_path = typer.prompt("  CSV metadata file path", default=profile["csv"])
    screenshots_path = typer.prompt("  Screenshots directory", default=profile["screenshots"])

    # Only copy key file if user provided a new path
    if key_file_input != profile["key_file"]:
        new_key_path = Path(key_file_input).expanduser()
        if not new_key_path.exists():
            typer.echo(f"❌ Key file not found: {new_key_path}", err=True)
            raise typer.Exit(1)
        global_keys_dir = config._global_dir / "keys"
        global_keys_dir.mkdir(parents=True, exist_ok=True)
        dest_key = global_keys_dir / new_key_path.name
        if dest_key.exists():
            typer.echo(f"  ⚠️  Overwriting existing key file at {dest_key}")
        shutil.copy2(new_key_path, dest_key)
        typer.echo(f"  ✅ Key file copied to {dest_key}")
        final_key_file = str(dest_key)
    else:
        final_key_file = profile["key_file"]

    config.save_app_profile(name, issuer_id, key_id, final_key_file, app_id, csv_path, screenshots_path)
    typer.echo(f"\n✅ App profile '{name}' updated.")


def cmd_install():
    """引导式项目初始化：检查环境，配置 App profile（可选）。

    适合首次在新项目中使用 asc 时运行。安装 asc 工具本身请先运行 install.sh。

    \b
    Example:
        asc install
    """
    typer.echo("=" * 52)
    typer.echo("  App Store Connect Tools — 项目初始化")
    typer.echo("=" * 52)
    typer.echo("")

    # ── 检查当前目录是否已配置 ──
    local_config = Path.cwd() / ".asc" / "config.toml"
    config = Config()
    apps = config.list_apps()

    if local_config.exists():
        content = local_config.read_text()
        if "default_app" in content:
            typer.echo("✅ 环境已就绪！当前目录已有默认配置：")
            typer.echo(f"   {local_config.relative_to(Path.cwd())}")
            typer.echo("")
            if apps:
                typer.echo("已配置的 profiles：")
                for name in apps:
                    typer.echo(f"  • {name}")
            typer.echo("")
            _print_cheatsheet()
            return

    # ── 列出已有 profiles ──
    if apps:
        typer.echo("已有以下 App profiles：")
        for name in apps:
            typer.echo(f"  • {name}")
        typer.echo("")
        set_default = typer.confirm("是否将其中一个设为默认？")
        if set_default:
            if len(apps) == 1:
                chosen = apps[0]
                cmd_app_default(chosen)
                typer.echo("")
                _print_cheatsheet()
                return
            else:
                typer.echo("请输入要设为默认的 profile 名称：")
                for i, name in enumerate(apps, 1):
                    typer.echo(f"  {i}. {name}")
                chosen = typer.prompt("Profile 名称")
                if chosen not in apps:
                    typer.echo(f"❌ '{chosen}' 不在列表中，跳过", err=True)
                    typer.echo("")
                    _print_cheatsheet()
                    return
                cmd_app_default(chosen)
                typer.echo("")
                _print_cheatsheet()
                return
        else:
            typer.echo("")
            typer.echo("好的，稍后可运行：")
            typer.echo("  asc app default <profile-name>")
            typer.echo("")
            _print_cheatsheet()
            return

    # ── 询问是否现在配置 ──
    typer.echo("尚未配置任何 App profile。")
    typer.echo("")
    configure_now = typer.confirm("现在配置 App profile 吗？")
    if not configure_now:
        typer.echo("")
        typer.echo("好的，稍后可运行：")
        typer.echo("")
        typer.echo("  asc app add <profile-name>")
        typer.echo("  asc app default <profile-name>")
        typer.echo("")
        _print_cheatsheet()
        return

    # ── 引导添加 profile ──
    profile_name = typer.prompt("请为此 App 起一个 profile 名称（如 myapp）")
    typer.echo("")
    cmd_app_add(profile_name)
    typer.echo("")

    set_as_default = typer.confirm(f"将 '{profile_name}' 设为本项目的默认 profile？")
    if set_as_default:
        cmd_app_default(profile_name)

    typer.echo("")
    _print_cheatsheet()


def _write_local_default(local_dir: Path, profile_name: str) -> None:
    """Write or update default_app in {local_dir}/config.toml."""
    local_dir.mkdir(parents=True, exist_ok=True)
    config_file = local_dir / "config.toml"
    existing = config_file.read_text() if config_file.exists() else ""

    if "[defaults]" in existing:
        lines = existing.splitlines()
        new_lines = []
        found = False
        in_defaults = False
        for line in lines:
            stripped = line.strip()
            if stripped == "[defaults]":
                in_defaults = True
            elif stripped.startswith("[") and stripped != "[defaults]":
                in_defaults = False
            if in_defaults and stripped.startswith("default_app"):
                new_lines.append(f'default_app = "{profile_name}"')
                found = True
            else:
                new_lines.append(line)
        if not found:
            result = []
            for line in new_lines:
                result.append(line)
                if line.strip() == "[defaults]":
                    result.append(f'default_app = "{profile_name}"')
            new_lines = result
        config_file.write_text("\n".join(new_lines) + "\n")
    else:
        prefix = existing.rstrip() + "\n\n" if existing.strip() else ""
        config_file.write_text(prefix + f'[defaults]\ndefault_app = "{profile_name}"\n')


def cmd_app_import(
    path: Optional[str] = typer.Option(
        None, "--path", "-p",
        help="项目根路径（默认：当前目录）",
    ),
    name: Optional[str] = typer.Option(
        None, "--name", "-n",
        help="Profile 名称（默认：项目目录名）",
    ),
):
    """从项目 AppStore/Config/.env 读取凭证，自动创建 app profile。

    在项目根目录的 AppStore/Config/.env 中读取以下字段：
    ISSUER_ID, KEY_ID, KEY_FILE, APP_ID。

    KEY_FILE 若为纯文件名，会在 AppStore/Config/ 下查找并拷贝到全局
    ~/.config/asc/keys/（已存在则跳过）。

    csv 和 screenshots 路径根据 AppStore/data/ 目录内容自动推断。

    \b
    Example:
        asc app import
        asc app import --path /path/to/MyProject
        asc app import --path /path/to/MyProject --name myapp
    """
    project_root = Path(path).expanduser().resolve() if path else Path.cwd()
    env_file = project_root / "AppStore" / "Config" / ".env"

    if not env_file.exists():
        typer.echo(f"❌ 未找到配置文件：{env_file}", err=True)
        typer.echo("   请确保项目目录下有 AppStore/Config/.env 文件。", err=True)
        raise typer.Exit(1)

    # 解析 .env（仅读取不 load_dotenv 以避免污染进程环境）
    env_vars: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        # Strip surrounding quotes (common in .env files)
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        env_vars[k.strip()] = v

    required = ["ISSUER_ID", "KEY_ID", "KEY_FILE", "APP_ID"]
    missing = [f for f in required if not env_vars.get(f)]
    if missing:
        typer.echo(f"❌ .env 缺少必填字段：{', '.join(missing)}", err=True)
        raise typer.Exit(1)

    issuer_id = env_vars["ISSUER_ID"]
    key_id = env_vars["KEY_ID"]
    key_file_val = env_vars["KEY_FILE"]
    app_id = env_vars["APP_ID"]

    # 处理 KEY_FILE：纯文件名则在 AppStore/Config/ 下查找
    key_path = Path(key_file_val).expanduser()
    if not key_path.is_absolute():
        key_path = project_root / "AppStore" / "Config" / key_file_val
    if not key_path.exists():
        typer.echo(f"❌ 找不到 .p8 密钥文件：{key_path}", err=True)
        raise typer.Exit(1)

    global_keys_dir = Path.home() / ".config" / "asc" / "keys"
    global_keys_dir.mkdir(parents=True, exist_ok=True)
    dest_key = global_keys_dir / key_path.name
    if dest_key.exists():
        typer.echo(f"  ℹ️  密钥文件已存在，跳过拷贝：{dest_key}")
    else:
        shutil.copy2(key_path, dest_key)
        typer.echo(f"  ✅ 密钥文件已拷贝到 {dest_key}")

    # 自动推断 csv 和 screenshots 路径（相对于 project_root）
    data_dir = project_root / "AppStore" / "data"
    csv_path = "data/appstore_info.csv"
    screenshots_path = "data/screenshots"
    if data_dir.exists():
        csv_files = sorted(data_dir.glob("*.csv"))
        if csv_files:
            csv_path = str(csv_files[0].relative_to(project_root))
        screenshots_candidate = data_dir / "screenshots"
        if screenshots_candidate.exists():
            screenshots_path = str(screenshots_candidate.relative_to(project_root))

    # Profile 名称：--name 优先，否则用目录名
    profile_name = name or project_root.name

    config = Config()
    existing_apps = config.list_apps()
    if profile_name in existing_apps:
        typer.echo(f"  ⚠️  Profile '{profile_name}' already exists and will be overwritten.")
    config.save_app_profile(
        profile_name,
        issuer_id,
        key_id,
        str(dest_key),
        app_id,
        csv_path,
        screenshots_path,
    )
    typer.echo(f"\n✅ App profile '{profile_name}' 已创建。")
    typer.echo(f"   Issuer ID:  {issuer_id}")
    typer.echo(f"   Key ID:     {key_id}")
    typer.echo(f"   App ID:     {app_id}")
    typer.echo(f"   CSV:        {csv_path}")
    typer.echo(f"   截图路径:   {screenshots_path}")

    # 询问是否设为默认
    set_default = typer.confirm(f"\n将 '{profile_name}' 设为 {project_root.name} 的默认 profile？")
    if set_default:
        local_dir = project_root / ".asc"
        _write_local_default(local_dir, profile_name)
        local_config_file = local_dir / "config.toml"
        typer.echo(f"✅ 默认 profile 已设为 '{profile_name}'")
        typer.echo(f"   配置写入：{local_config_file.relative_to(project_root)}")


_ENV_EXAMPLE = """\
# App Store Connect API credentials
# Copy this file to .env and fill in the values.
# NEVER commit .env to version control.

ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
KEY_ID=XXXXXXXXXX
KEY_FILE=AuthKey_XXXXXXXXXX.p8
APP_ID=0000000000
"""

_CSV_TEMPLATE = (
    '"语言",应用名称,副标题,"长描述","关键子","技术支持链接",营销网站\n'
    '简体中文(zh-Hans),应用名称,副标题,"在这里填写应用的完整描述","关键词1,关键词2",,\n'
    '英文(en-US),App Name,Subtitle,"Write your full app description here","keyword1,keyword2",,\n'
)

_GITIGNORE = ".env\n"


def _read_template(relative: str) -> bytes:
    """Return the raw bytes of a bundled template file."""
    return importlib.resources.files("asc.templates").joinpath(relative).read_bytes()


def _scaffold_appstore_dir(project_root: Path) -> bool:
    """Create AppStore/ template structure under project_root.

    Returns True if any new file/dir was created, False if everything already existed.
    """
    appstore = project_root / "AppStore"
    config_dir = appstore / "Config"
    data_dir = appstore / "data"
    screenshots_dir = data_dir / "screenshots"
    iap_review_dir = data_dir / "iap_review"

    created: list[str] = []

    for d in (appstore, config_dir, data_dir, screenshots_dir, iap_review_dir):
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d.relative_to(project_root)))

    env_example = config_dir / ".env.example"
    if not env_example.exists():
        env_example.write_text(_ENV_EXAMPLE, encoding="utf-8")
        created.append(str(env_example.relative_to(project_root)))

    gitignore = config_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE, encoding="utf-8")
        created.append(str(gitignore.relative_to(project_root)))

    csv_file = data_dir / "appstore_info.csv"
    if not csv_file.exists():
        csv_file.write_text(_CSV_TEMPLATE, encoding="utf-8")
        created.append(str(csv_file.relative_to(project_root)))

    iap_json = data_dir / "iap_packages.json"
    if not iap_json.exists():
        iap_json.write_bytes(_read_template("iap_packages.json"))
        created.append(str(iap_json.relative_to(project_root)))

    iap_img_dst = iap_review_dir / "premium_monthly.png"
    if not iap_img_dst.exists():
        iap_img_dst.write_bytes(_read_template("iap_review/premium_monthly.png"))
        created.append(str(iap_img_dst.relative_to(project_root)))

    for item in created:
        typer.echo(f"  ✅ 已创建: {item}")

    return bool(created)


def cmd_init(
    path: Optional[str] = typer.Option(
        None, "--path", "-p",
        help="项目根路径（默认：当前目录）",
    ),
):
    """在 Xcode 项目根目录初始化 AppStore/ 模板目录结构。

    检测当前目录（或 --path）是否包含 .xcodeproj / .xcworkspace，
    若是则在该目录下创建 AppStore/ 及内部模板文件与子目录。
    若 AppStore/ 已存在，仅补全缺失的子目录/文件（幂等）。

    \b
    创建的文件结构：
        AppStore/
          Config/
            .env.example          ← 填写凭证模板（勿提交 .env）
            .gitignore            ← 自动忽略 .env
          data/
            appstore_info.csv     ← 元数据模板（多语言）
            iap_packages.json     ← IAP/订阅配置模板
            screenshots/          ← 按语言放截图
            iap_review/           ← IAP 审核截图示例

    \b
    Example:
        asc init
        asc init --path /path/to/MyApp
    """
    project_root = Path(path).expanduser().resolve() if path else Path.cwd()

    has_xcodeproj = any(project_root.glob("*.xcodeproj"))
    has_xcworkspace = any(project_root.glob("*.xcworkspace"))
    if not has_xcodeproj and not has_xcworkspace:
        typer.echo(
            "❌ 未检测到 Xcode 项目（.xcodeproj 或 .xcworkspace）。\n"
            "   请在 Xcode 项目根目录运行 asc init。",
            err=True,
        )
        raise typer.Exit(1)

    appstore = project_root / "AppStore"
    typer.echo(f"初始化 AppStore 目录结构：{project_root}")

    if appstore.exists():
        typer.echo("  ℹ️  AppStore/ 已存在，补全缺失文件…")

    any_created = _scaffold_appstore_dir(project_root)

    if not any_created:
        typer.echo("✅ AppStore/ 已存在且完整，无需变更。")
        return

    typer.echo("")
    typer.echo("✅ 初始化完成！下一步：")
    typer.echo("  1. 将 AppStore/Config/.env.example 复制为 AppStore/Config/.env")
    typer.echo("     并填入真实凭证（ISSUER_ID, KEY_ID, KEY_FILE, APP_ID）")
    typer.echo("  2. 运行：asc app import  ← 自动读取 .env 创建 profile")
    typer.echo("  3. 运行：asc upload      ← 上传元数据 + 截图")


def _print_cheatsheet():
    """Print a quick-reference command cheatsheet."""
    typer.echo("─" * 52)
    typer.echo("  常用命令速查")
    typer.echo("─" * 52)
    typer.echo("  asc upload                上传元数据 + 截图")
    typer.echo("  asc metadata              仅上传元数据")
    typer.echo("  asc screenshots           仅上传截图")
    typer.echo("  asc whats-new --text '...'  更新版本描述")
    typer.echo("  asc iap --iap-file <f>    上传 IAP / 订阅")
    typer.echo("  asc check                 验证 API 连接")
    typer.echo("  asc app list              查看所有 profiles")
    typer.echo("─" * 52)
