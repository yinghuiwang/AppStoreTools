"""Screenshots upload command"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

import typer
from PIL import Image

from asc.config import Config
from asc.constants import DISPLAY_TYPE_BY_SIZE, SCREENSHOT_FOLDER_TO_LOCALE
from asc.error_handler import get_action_hint
from asc.guard import Guard, GuardViolationError
from asc.utils import make_api_from_config, resolve_app_profile, resolve_locale, md5_of_file
from asc.i18n import t, HELP


def _detect_display_type(image_path: Path) -> Optional[str]:
    with Image.open(image_path) as img:
        size = img.size
    display_type = DISPLAY_TYPE_BY_SIZE.get(size)
    if display_type:
        return display_type
    print(f"  ⚠️  无法从尺寸 {size} 自动识别设备类型")
    return None


def _get_sorted_screenshots(folder: Path) -> list[Path]:
    extensions = {".png", ".jpg", ".jpeg"}
    files = [
        f
        for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in extensions
    ]

    def sort_key(p: Path):
        nums = re.findall(r"\d+", p.stem)
        return int(nums[-1]) if nums else 0

    return sorted(files, key=sort_key)


def _upload_screenshots_core(
    api,
    app_id: str,
    screenshots_dir: str,
    display_type_override: Optional[str] = None,
    dry_run: bool = False,
):
    """Core screenshots upload logic"""
    print("\n" + "=" * 60)
    print("🖼️  上传截图")
    print("=" * 60)

    screenshots_path = Path(screenshots_dir)
    if not screenshots_path.exists():
        print(f"❌ 截图目录不存在: {screenshots_dir}")
        print(f"💡 可使用 --screenshots-dir 参数指定其他路径")
        return

    version = api.get_editable_version(app_id)
    if not version:
        print("❌ 找不到可编辑的 App Store 版本")
        print(f"💡 请在 App Store Connect 中确认版本状态为可编辑状态")
        return
    version_id = version["id"]

    ver_locs = api.get_version_localizations(version_id)
    ver_loc_map = {loc["attributes"]["locale"]: loc for loc in ver_locs}
    existing_locales = list(ver_loc_map.keys())

    folders = [f for f in screenshots_path.iterdir() if f.is_dir()]
    if not folders:
        print("  截图目录中没有子文件夹")
        return

    locale_to_folder: dict[str, Path] = {}
    for folder in sorted(folders):
        folder_name = folder.name.lower()
        locale = SCREENSHOT_FOLDER_TO_LOCALE.get(folder_name, folder_name)
        resolved = resolve_locale(locale, existing_locales)
        locale_to_folder[resolved] = folder

    en_us_folder = locale_to_folder.get("en-US")
    if en_us_folder is None:
        for folder in folders:
            if folder.name.lower() in ("en", "en-us"):
                en_us_folder = folder
                break

    for resolved, loc_data in sorted(ver_loc_map.items()):
        folder = locale_to_folder.get(resolved)
        if folder is None:
            if en_us_folder is None:
                print(
                    f"\n  ── locale: {resolved} → 无截图文件夹且无 en-US 可回退，跳过 ──"
                )
                continue
            print(f"\n  ── locale: {resolved} → 无截图文件夹，使用 en-US 截图回退 ──")
            folder = en_us_folder
        else:
            print(f"\n  ── 文件夹: {folder.name} → locale: {resolved} ──")

        localization_id = loc_data["id"]
        files = _get_sorted_screenshots(folder)
        if not files:
            print("    没有找到截图文件，跳过")
            continue

        print(f"    找到 {len(files)} 张截图: {[f.name for f in files]}")

        display_type = display_type_override
        if not display_type:
            display_type = _detect_display_type(files[0])
        if not display_type:
            print("💡 无法确定设备类型，请使用 --display-type 手动指定")
            continue
        print(f"    设备类型: {display_type}")

        if dry_run:
            for f in files:
                print(
                    f"    [预览] 将上传: {f.name} ({f.stat().st_size / 1024:.0f} KB)"
                )
            continue

        sets_resp = api.get_screenshot_sets(localization_id)
        sets_data = sets_resp.get("data", [])
        included = sets_resp.get("included", [])

        target_set = None
        for s in sets_data:
            if s["attributes"]["screenshotDisplayType"] == display_type:
                target_set = s
                break

        if target_set:
            set_id = target_set["id"]
            existing_shots = [
                inc
                for inc in included
                if inc["type"] == "appScreenshots"
                and inc.get("relationships", {})
                .get("appScreenshotSet", {})
                .get("data", {})
                .get("id")
                == set_id
            ]
            if not existing_shots:
                existing_shots = api.get_screenshots_in_set(set_id)

            if existing_shots:
                print(f"    🗑️  删除 {len(existing_shots)} 张已有截图...")
                for shot in existing_shots:
                    api.delete_screenshot(shot["id"])
                time.sleep(1)
        else:
            print("    创建截图集...")
            resp = api.create_screenshot_set(localization_id, display_type)
            set_id = resp["data"]["id"]

        print(f"    截图集 ID: {set_id}")

        for idx, file_path in enumerate(files, 1):
            filesize = file_path.stat().st_size
            filename = file_path.name
            print(
                f"    [{idx}/{len(files)}] 上传: {filename} ({filesize / 1024:.0f} KB)"
            )

            reserve_resp = api.reserve_screenshot(set_id, filename, filesize)
            screenshot_data = reserve_resp["data"]
            screenshot_id = screenshot_data["id"]
            upload_ops = screenshot_data["attributes"]["uploadOperations"]

            api.upload_screenshot_asset(upload_ops, file_path)

            checksum = md5_of_file(file_path)
            api.commit_screenshot(screenshot_id, checksum)

            for retry in range(30):
                time.sleep(2)
                check = api.get(f"/v1/appScreenshots/{screenshot_id}")
                state = check["data"]["attributes"]["assetDeliveryState"]["state"]
                if state == "COMPLETE":
                    print("         ✅ 上传完成")
                    break
                elif state == "FAILED":
                    errors = check["data"]["attributes"]["assetDeliveryState"].get(
                        "errors", []
                    )
                    print(f"         ❌ 上传失败: {errors}")
                    print(f"💡 请检查网络连接后重试")
                    break
                else:
                    if retry % 5 == 4:
                        print(f"         ⏳ 处理中 ({state})...")
            else:
                print("         ⚠️  处理超时，请在 App Store Connect 中检查状态")

    print("\n✅ 截图上传完成")


def cmd_screenshots(
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['preview_uploads'])),
    screenshots: Optional[str] = typer.Option(None, "--screenshots", "-s",
        help=t(HELP['screenshots_dir'])),
    display_type: Optional[str] = typer.Option(None, "--display-type",
        help=t(HELP['screenshots_display_type']),
    ),
):
    """Upload screenshots to App Store Connect.

    Screenshots are uploaded per locale. The tool looks for subfolders in the
    screenshots directory named after locales (e.g. en-US, zh-CN).

    \b
    Device types (auto-detected from image dimensions):
    - APP_IPHONE_67 (iPhone 15 Pro)
    - APP_IPHONE_61 (iPhone 14)
    - APP_IPAD_PRO_129_EQ (iPad Pro 12.9")
    - APP_IPAD_MINI_97 (iPad mini)
    - APP_IPHONE_55 (iPhone 8 Plus)
    - etc.

    \b
    Notes:
    - Existing screenshots for the same device type are deleted before upload
    - Screenshots are sorted by filename number in upload order

    \b
    Example:
        asc --app myapp screenshots
        asc --app myapp screenshots --dry-run
        asc --app myapp screenshots --screenshots ./custom_screenshots/
        asc --app myapp screenshots --display-type APP_IPHONE_67
        asc --app myapp screenshots --screenshots ./custom_screenshots/ --display-type APP_IPHONE_67
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
    screenshots_dir = screenshots or config.screenshots_path
    _upload_screenshots_core(api, app_id, screenshots_dir, display_type, dry_run)
