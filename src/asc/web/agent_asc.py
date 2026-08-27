"""Read-only App Store Connect helpers for the agent. No writes."""
from __future__ import annotations

from typing import Any

from asc.api import AppStoreConnectAPI
from asc.config import Config
from asc.web.agent_redact import redact_text

_CREDENTIALS_MISSING = "credentials missing"
_IAP_CAP = 50


def _api_for_profile(profile: str) -> tuple[AppStoreConnectAPI | None, str]:
    name = str(profile or "").strip()
    if not name:
        return None, _CREDENTIALS_MISSING
    try:
        cfg = Config(app_name=name)
    except Exception:
        return None, _CREDENTIALS_MISSING
    issuer_id = str(cfg.issuer_id or "").strip()
    key_id = str(cfg.key_id or "").strip()
    key_file = str(cfg.key_file or "").strip()
    app_id = str(cfg.app_id or "").strip()
    if not (issuer_id and key_id and key_file and app_id):
        return None, _CREDENTIALS_MISSING
    return AppStoreConnectAPI(issuer_id, key_id, key_file), app_id


def get_asc_version(profile: str) -> dict[str, Any]:
    api, extra = _api_for_profile(profile)
    if api is None:
        return {"ok": False, "error": extra or _CREDENTIALS_MISSING}
    try:
        version = api.get_editable_version(extra)
        if not version:
            return {"ok": True, "exists": False, "code": "no_editable_version"}
        attrs = version.get("attributes") or {}
        state = attrs.get("appStoreState") or attrs.get("appVersionState") or ""
        return {
            "ok": True,
            "version": attrs.get("versionString"),
            "state": state,
        }
    except Exception as exc:
        return {"ok": False, "error": redact_text(str(exc))}


def list_asc_iaps(profile: str) -> dict[str, Any]:
    api, extra = _api_for_profile(profile)
    if api is None:
        return {"ok": False, "error": extra or _CREDENTIALS_MISSING}
    try:
        records = api.list_in_app_purchases(extra) or []
        items: list[dict[str, str]] = []
        for record in records[:_IAP_CAP]:
            attrs = record.get("attributes") or {}
            items.append(
                {
                    "productId": str(attrs.get("productId") or ""),
                    "name": str(attrs.get("name") or attrs.get("referenceName") or ""),
                    "type": str(attrs.get("inAppPurchaseType") or ""),
                }
            )
        return {
            "ok": True,
            "items": items,
            "truncated": len(records) > _IAP_CAP,
        }
    except Exception as exc:
        return {"ok": False, "error": redact_text(str(exc))}
