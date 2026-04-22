"""IAP upload command"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from asc.config import Config
from asc.utils import make_api_from_config


def _load_iap_package(file_path: str) -> list[dict]:
    raw = Path(file_path).read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    if isinstance(data, dict):
        items = data.get("items", [])
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("IAP 配置格式错误：应为数组或包含 items 数组的对象")

    if not isinstance(items, list) or not items:
        raise ValueError("IAP 配置为空，请至少提供一个 IAP 项")
    return items


def _upload_iap_core(api, app_id: str, iap_items: list[dict], dry_run: bool = False):
    print("\n" + "=" * 60)
    print("🛍️  上传 IAP 包")
    print("=" * 60)

    existing_iaps = api.list_in_app_purchases(app_id)
    existing_by_product_id = {}
    for iap in existing_iaps:
        product_id = iap.get("attributes", {}).get("productId")
        if product_id:
            existing_by_product_id[product_id] = iap

    for item in iap_items:
        product_id = str(item.get("productId", "")).strip()
        if not product_id:
            print("  ❌ 跳过：缺少 productId")
            continue

        name = str(item.get("name", "")).strip()
        iap_type = str(item.get("inAppPurchaseType", "")).strip()
        review_note = str(item.get("reviewNote", "")).strip()
        available_all = item.get("availableInAllTerritories", True)
        localizations = item.get("localizations", {})

        print(f"\n  ── IAP: {product_id} ──")
        existing = existing_by_product_id.get(product_id)

        attrs = {
            "productId": product_id,
            "availableInAllTerritories": bool(available_all),
        }
        if name:
            attrs["name"] = name
        if iap_type:
            attrs["inAppPurchaseType"] = iap_type
        if review_note:
            attrs["reviewNote"] = review_note

        if existing:
            iap_id = existing["id"]
            print(f"    已存在，ID: {iap_id}，执行更新")
            if not dry_run:
                update_attrs = {k: v for k, v in attrs.items() if k != "productId"}
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

        if not isinstance(localizations, dict) or not localizations:
            print("    ⚠️  无本地化配置，跳过本地化上传")
            continue

        if dry_run:
            print(f"    [预览] 将更新本地化: {list(localizations.keys())}")
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

    print("\n✅ IAP 上传完成")


def cmd_iap(
    iap_file: str = typer.Option(..., "--iap-file", help="IAP JSON config file path"),
    app: Optional[str] = typer.Option(None, "--app"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Upload in-app purchases from JSON file"""
    config = Config(app)
    api, app_id = make_api_from_config(config)
    iap_path = Path(iap_file)
    if not iap_path.exists():
        typer.echo(f"❌ IAP 配置文件不存在: {iap_path}", err=True)
        raise typer.Exit(1)
    iap_items = _load_iap_package(str(iap_path))
    print(f"\n📦 从 IAP 配置读取 {len(iap_items)} 项")
    _upload_iap_core(api, app_id, iap_items, dry_run)
