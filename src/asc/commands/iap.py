"""IAP upload command"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import os
import hashlib
from pathlib import Path
from typing import Optional

import typer

from asc.config import Config
from asc.error_handler import get_action_hint
from asc.guard import Guard, GuardViolationError
from asc.utils import make_api_from_config, resolve_app_profile
from asc.i18n import t, ERRORS, HELP

REVIEW_SCREENSHOT_WARNING_BYTES = 5 * 1024 * 1024
REVIEW_SCREENSHOT_EXTS = {".png", ".jpg", ".jpeg"}


def _non_empty_str(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _valid_territory_id(value) -> bool:
    return isinstance(value, str) and len(value.strip()) == 3 and value.strip().isalpha()


def _validate_iap_item_price(item: dict, label: str) -> None:
    price = item.get("price")
    if price is None:
        return
    if not isinstance(price, dict):
        raise ValueError(f"{label}.price must be an object")

    has_price_point = _non_empty_str(price.get("pricePointId"))
    has_base_lookup = (
        _non_empty_str(price.get("baseTerritory"))
        and _non_empty_str(price.get("baseAmount"))
    )
    if not has_price_point and not has_base_lookup:
        raise ValueError(
            f"{label}.price requires either pricePointId or baseTerritory + baseAmount"
        )
    if has_price_point and not _non_empty_str(price.get("baseTerritory")):
        raise ValueError(f"{label}.price.baseTerritory required when pricePointId is set")
    if price.get("baseTerritory") is not None and not _valid_territory_id(
        price.get("baseTerritory")
    ):
        raise ValueError(
            f"{label}.price.baseTerritory must be a 3-letter territory id such as USA or CHN"
        )
    if price.get("territory") is not None and not _valid_territory_id(
        price.get("territory")
    ):
        raise ValueError(
            f"{label}.price.territory must be a 3-letter territory id such as USA or CHN"
        )


def _resolve_review_screenshot(obj: dict, config_dir: Path) -> None:
    """Resolve relative review.screenshot path against config_dir (in-place)."""
    review = obj.get("review")
    if not isinstance(review, dict):
        return
    shot = review.get("screenshot")
    if not shot or not isinstance(shot, str):
        return
    p = Path(shot)
    if not p.is_absolute():
        review["screenshot"] = str(config_dir / p)


def _validate_review_screenshot(item: dict, label: str) -> Optional[Path]:
    review = item.get("review")
    if not isinstance(review, dict):
        return None
    shot = review.get("screenshot")
    if not shot:
        return None
    if not isinstance(shot, str) or not shot.strip():
        raise ValueError(f"{label}.review.screenshot path required")
    path = Path(shot)
    if not path.exists() or not path.is_file():
        raise ValueError(f"{label}.review.screenshot file not found: {shot}")
    if path.suffix.lower() not in REVIEW_SCREENSHOT_EXTS:
        raise ValueError(
            f"{label}.review.screenshot must be .png/.jpg/.jpeg, got {path.suffix}"
        )
    size = path.stat().st_size
    if size > REVIEW_SCREENSHOT_WARNING_BYTES:
        typer.echo(
            f"⚠️  {label}.review.screenshot exceeds 5MB ({size} bytes); "
            "continuing and leaving final validation to App Store Connect"
        )
    return path


def _load_iap_config(file_path: str) -> tuple[list[dict], list[dict]]:
    """Return (iap_items, subscription_groups) from the JSON file.

    Relative file paths in the JSON (e.g. review.screenshot) are resolved
    against the config file's parent directory so they work regardless of CWD.
    """
    config_path = Path(file_path).resolve()
    config_dir = config_path.parent
    raw = config_path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)

    items: list[dict] = []
    subs: list[dict] = []

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("items", []) or []
        subs = data.get("subscriptionGroups", []) or []
    else:
        raise ValueError("IAP 配置格式错误：应为数组或对象")

    if not items and not subs:
        raise ValueError("IAP 配置为空 (empty)：请至少提供 items 或 subscriptionGroups")

    # Resolve relative file paths against the config file's directory
    for idx, item in enumerate(items):
        _resolve_review_screenshot(item, config_dir)
        _validate_review_screenshot(item, f"items[{idx}]")
        _validate_iap_item_price(item, f"items[{idx}]")
    for group in subs:
        for sub in group.get("subscriptions", []):
            _resolve_review_screenshot(sub, config_dir)

    return items, subs


def _load_iap_package(file_path: str) -> list[dict]:
    """Legacy wrapper."""
    items, _ = _load_iap_config(file_path)
    if not items:
        raise ValueError("IAP 配置无 items")
    return items


def _upload_iap_core(api, app_id: str, iap_items: list[dict], dry_run: bool = False, update_existing: bool = False):
    print("\n" + "=" * 60)
    print("🛍️  上传 IAP 包")
    print("=" * 60)

    existing_iaps = api.list_in_app_purchases(app_id)
    existing_by_product_id = {}
    for iap in existing_iaps:
        product_id = iap.get("attributes", {}).get("productId")
        if product_id:
            existing_by_product_id[product_id] = iap

    total_items = len(iap_items)
    for idx, item in enumerate(iap_items):
        product_id = str(item.get("productId", "")).strip()
        if not product_id:
            print("  ❌ 跳过：缺少 productId")
            continue

        name = str(item.get("name", "")).strip()
        iap_type = str(item.get("inAppPurchaseType", "")).strip()
        review_note = str(item.get("reviewNote", "")).strip()
        review = item.get("review") if isinstance(item.get("review"), dict) else {}
        if not review_note:
            review_note = str(review.get("note", "")).strip()
        review_screenshot = review.get("screenshot")
        price = item.get("price") if isinstance(item.get("price"), dict) else {}
        localizations = item.get("localizations", {})

        print(f"\n  ── IAP: {product_id} ──")
        existing = existing_by_product_id.get(product_id)

        attrs = {"productId": product_id}
        if name:
            attrs["name"] = name
        if iap_type:
            attrs["inAppPurchaseType"] = iap_type
        if review_note:
            attrs["reviewNote"] = review_note

        if existing:
            iap_id = existing["id"]
            if not update_existing:
                print(f"    已存在 (ID: {iap_id})，跳过（使用 --update-existing 以更新）")
                continue
            print(f"    已存在 (ID: {iap_id})，执行更新")
            if not dry_run:
                update_attrs = {}
                if name:
                    update_attrs["name"] = name
                if update_attrs:
                    api.update_in_app_purchase(iap_id, update_attrs)
        else:
            print("    不存在，执行创建")
            if not dry_run:
                create_resp = api.create_in_app_purchase(app_id, attrs)
                iap_id = create_resp["data"]["id"]
                print(f"    ✅ 已创建，ID: {iap_id}")
            else:
                iap_id = "DRY_RUN_ID"

        _sync_iap_availability(api, iap_id, item, update_existing, dry_run)
        _sync_iap_price(api, iap_id, price, update_existing, dry_run)

        if review_screenshot:
            _sync_iap_review_screenshot(
                api, iap_id, review_screenshot, update_existing, dry_run
            )

        if not isinstance(localizations, dict) or not localizations:
            print("    ⚠️  无本地化配置，跳过本地化上传")
            pct = int((idx + 1) / total_items * 100)
            print(f"[PROGRESS:{pct}:IAP {idx + 1}/{total_items}]")
            continue

        if dry_run:
            print(f"    [预览] 将更新本地化: {list(localizations.keys())}")
            pct = int((idx + 1) / total_items * 100)
            print(f"[PROGRESS:{pct}:IAP {idx + 1}/{total_items}]")
            continue

        existing_locs = api.get_in_app_purchase_localizations(iap_id)
        loc_map = {loc["attributes"]["locale"]: loc for loc in existing_locs}

        for locale, loc_data in localizations.items():
            if not isinstance(loc_data, dict):
                print(f"    ⚠️  locale={locale} 配置格式错误，已跳过")
                continue
            loc_attrs = {}
            display_name = str(
                loc_data.get("name") or loc_data.get("displayName") or ""
            ).strip()
            description = str(loc_data.get("description") or "").strip()
            if display_name:
                loc_attrs["name"] = display_name
            if description:
                loc_attrs["description"] = description
            if not loc_attrs:
                print(f"    ⚠️  locale={locale} 无有效字段（name/description），已跳过")
                continue

            if locale in loc_map:
                api.update_in_app_purchase_localization(
                    loc_map[locale]["id"], loc_attrs
                )
                print(f"    ✅ {locale}: 已更新本地化")
            else:
                api.create_in_app_purchase_localization(iap_id, locale, loc_attrs)
                print(f"    ✅ {locale}: 已创建本地化")

        # Progress output for Web UI
        pct = int((idx + 1) / total_items * 100)
        print(f"[PROGRESS:{pct}:IAP {idx + 1}/{total_items}]")

    print("\n✅ IAP 上传完成")


def _sync_iap_availability(api, iap_id, item, update_existing, dry_run):
    available_all = bool(item.get("availableInAllTerritories", True))
    territory_ids = item.get("availableTerritories") or item.get("territories")

    if territory_ids is not None:
        if not isinstance(territory_ids, list):
            print("    ⚠️  销售地区: availableTerritories/territories 必须是列表，跳过")
            return
        territory_ids = [str(t).strip() for t in territory_ids if str(t).strip()]
    elif available_all:
        if dry_run:
            print("    [预览] 销售地区: 全部国家/地区")
            return
        territory_ids = [t["id"] for t in api.list_territories()]
    else:
        territory_ids = []

    if not territory_ids:
        print("    ⚠️  销售地区: 无可用地区配置，跳过")
        return

    if dry_run:
        print(f"    [预览] 销售地区: {len(territory_ids)} 个地区")
        return

    try:
        existing = api.get_in_app_purchase_availability(iap_id)
    except Exception:
        existing = None

    if existing and not update_existing:
        print("    销售地区: 已存在，跳过")
        return
    if existing and update_existing:
        print("    销售地区: 已存在（Apple API 不支持直接替换），跳过")
        return

    try:
        api.create_in_app_purchase_availability(
            iap_id,
            available_in_new_territories=available_all,
            territory_ids=territory_ids,
        )
        print(f"    销售地区: 已设置 {len(territory_ids)} 个地区 ✅")
    except Exception as e:
        print(f"    ⚠️  销售地区设置跳过: {e}")


def _sync_iap_price(api, iap_id, price_cfg, update_existing, dry_run):
    if not price_cfg:
        print("    ⚠️  无价格配置，跳过价格时间表")
        return

    territory = str(
        price_cfg.get("territory") or price_cfg.get("baseTerritory") or ""
    ).strip()
    amount = price_cfg.get("baseAmount")
    pp_id = str(price_cfg.get("pricePointId") or "").strip()
    apply_equalized = bool(price_cfg.get("applyEqualizedPrices", True))

    if not pp_id:
        if not territory or amount is None:
            print("    ⚠️  价格: 需要 pricePointId 或 baseTerritory + baseAmount，跳过")
            return
        pp_id = api.find_in_app_purchase_price_point(iap_id, territory, amount)
    if not pp_id:
        candidates = api.list_in_app_purchase_price_points(iap_id, territory)
        nearest = _nearest_iap_price_points(candidates, amount, limit=3)
        hint = ", ".join(f"{c}" for c in nearest) or "无候选"
        raise Exception(
            f"未找到 IAP Price Point: {territory} {amount}. "
            f"territory 必须使用 Apple 三字母 ID（如 USA/CHN），最近候选: {hint}"
        )

    if dry_run:
        if amount is not None:
            print(f"    [预览] 价格: 基准 {territory} {amount} → Price Point {pp_id}")
        else:
            print(f"    [预览] 价格: Price Point {pp_id}")
        return

    try:
        existing = api.get_in_app_purchase_price_schedule(iap_id)
    except Exception:
        existing = None

    if _iap_price_schedule_has_prices(existing) and not update_existing:
        print("    价格: 时间表已存在，跳过")
        return
    if _iap_price_schedule_has_prices(existing) and update_existing:
        print("    价格: 时间表已存在（Apple API 不支持直接替换），跳过")
        return

    price_points = [(territory, pp_id)]
    if apply_equalized:
        try:
            equalizations = api.list_in_app_purchase_price_point_equalizations(
                pp_id, iap_id
            )
            price_points = _price_points_by_territory(equalizations)
            if not any(price_territory == territory for price_territory, _ in price_points):
                price_points.insert(0, (territory, pp_id))
        except Exception as e:
            print(f"    ⚠️  等价价格点查询失败，仅设置基准地区: {e}")

    api.create_in_app_purchase_price_schedule(
        iap_id,
        territory,
        price_points,
        start_date=price_cfg.get("startDate"),
        end_date=price_cfg.get("endDate"),
    )
    if amount is not None:
        print(f"    价格: 基准 {territory} {amount} → 已设置 {len(price_points)} 个地区 ✅")
    else:
        print(f"    价格: Price Point {pp_id} → 已设置 {len(price_points)} 个地区 ✅")


def _iap_price_schedule_has_prices(schedule) -> bool:
    if not isinstance(schedule, dict):
        return False
    relationships = schedule.get("relationships")
    if not isinstance(relationships, dict):
        return False
    for key in ("manualPrices", "automaticPrices"):
        data = relationships.get(key, {}).get("data")
        if isinstance(data, list) and data:
            return True
    return False


def _price_points_by_territory(price_points: list) -> list[tuple[str, str]]:
    result = []
    seen = set()
    for price_point in price_points:
        territory_id = (
            price_point.get("relationships", {})
            .get("territory", {})
            .get("data", {})
            .get("id")
        )
        if not territory_id:
            territory_id = price_point.get("territory")
        pp_id = price_point.get("id")
        if territory_id and pp_id and territory_id not in seen:
            result.append((territory_id, pp_id))
            seen.add(territory_id)
    return result


def _nearest_iap_price_points(candidates: list, target, limit: int) -> list[str]:
    try:
        target_decimal = Decimal(str(target))
    except (InvalidOperation, TypeError, ValueError):
        return []
    scored = []
    for candidate in candidates:
        price_str = candidate.get("attributes", {}).get("customerPrice", "")
        try:
            scored.append((abs(Decimal(str(price_str)) - target_decimal), price_str))
        except (InvalidOperation, TypeError, ValueError):
            continue
    scored.sort(key=lambda item: item[0])
    return [price for _, price in scored[:limit]]


def _sync_iap_review_screenshot(api, iap_id, shot_path, update_existing, dry_run):
    path = Path(shot_path)

    if dry_run:
        print(f"    [预览] IAP 审核截图: 将上传 {path.name}")
        return

    existing = api.list_in_app_purchase_review_screenshots(iap_id)
    if existing and not update_existing:
        print("    IAP 审核截图: 已存在，跳过")
        return

    for s in existing:
        api.delete_in_app_purchase_review_screenshot(s["id"])

    file_bytes = path.read_bytes()
    reservation = api.create_in_app_purchase_review_screenshot_reservation(
        iap_id, path.name, len(file_bytes)
    )
    shot_id = reservation["data"]["id"]
    upload_ops = reservation["data"].get("attributes", {}).get("uploadOperations", [])
    api.upload_in_app_purchase_review_screenshot(upload_ops, file_bytes)
    md5 = hashlib.md5(file_bytes).hexdigest()
    api.commit_in_app_purchase_review_screenshot(shot_id, md5)
    print(f"    IAP 审核截图: {path.name} 上传 ✅")


def cmd_iap(
    iap_file: str = typer.Option(..., "--iap-file", "-f",
        help=t(HELP['iap_file'])),
    app: Optional[str] = typer.Option(None, "--app", "-a", help=t(HELP['app_profile_name'])),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help=t(HELP['preview_without_upload'])),
    update_existing: bool = typer.Option(
        False, "--update-existing", "-u",
        help=t(HELP['update_existing']),
    ),
):
    """Upload in-app purchases and subscriptions from JSON file.

    Supports both one-time IAP (items array) and auto-renewable subscriptions
    (subscriptionGroups array). The JSON file can contain one or both.

    \b
    IAP items structure:
    [
      {
        "productId": "com.example.app.item1",
        "name": "Item Name",
        "inAppPurchaseType": "CONSUMABLE",
        "reviewNote": "This is a test IAP",
        "localizations": {
          "en-US": { "name": "Item Name", "description": "Description" },
          "zh-CN": { "name": "物品名称", "description": "描述" }
        }
      }
    ]

    \b
    Subscription groups structure:
    {
      "subscriptionGroups": [
        {
          "referenceName": "Premium Subscription",
          "subscriptions": [
            {
              "productId": "com.example.app.premium.monthly",
              "name": "Premium Monthly",
              "subscriptionPeriod": "ONE_MONTH",
              "groupLevel": 1,
              "localizations": {...},
              "price": { "baseTerritory": "USA", "baseAmount": "4.99" },
              "introductoryOffer": {...},
              "promotionalOffers": [...],
              "review": { "note": "Review note", "screenshot": "path/to/screenshot.png" }
            }
          ]
        }
      ]
    }

    \b
    Default behavior: creates new items only. Use --update-existing to modify.

    \b
    Example:
        asc --app myapp iap --iap-file data/iap_packages.json
        asc --app myapp iap --iap-file data/iap_packages.json --dry-run
        asc --app myapp iap --iap-file data/iap_packages.json --update-existing
    """
    from asc.commands.subscriptions import _upload_subscriptions_core

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
    iap_path = Path(iap_file)
    if not iap_path.exists():
        typer.echo(f"❌ {t(ERRORS['iap_config_not_found']).format(path=iap_path)}", err=True)
        typer.echo(f"💡 可使用 --iap-file 参数指定其他路径。", err=True)
        raise typer.Exit(1)

    try:
        items, groups = _load_iap_config(str(iap_path))
    except ValueError as e:
        typer.echo(f"❌ {e}", err=True)
        hint = get_action_hint(e)
        if hint:
            typer.echo(f"💡 {hint}", err=True)
        raise typer.Exit(1)

    exit_code = 0
    if items:
        print(f"\n📦 一次性 IAP: {len(items)} 项")
        _upload_iap_core(api, app_id, items, dry_run, update_existing=update_existing)

    if groups:
        total_subs = sum(len(g.get("subscriptions", [])) for g in groups)
        print(f"\n🔁 订阅: {len(groups)} 组 / {total_subs} 商品")
        failed = _upload_subscriptions_core(
            api, app_id, groups, update_existing=update_existing, dry_run=dry_run
        )
        if failed:
            exit_code = 1

    if exit_code:
        raise typer.Exit(exit_code)
