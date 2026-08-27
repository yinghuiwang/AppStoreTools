from __future__ import annotations

from asc.web.agent_context import format_page_context, sanitize_page_context


def test_sanitize_drops_unknown_keys():
    out = sanitize_page_context(
        {"route": "/listing", "foo": "bar", "issuer_id": "abc-123", "unknown": 1}
    )
    assert out == {"route": "/listing"}
    assert "foo" not in out
    assert "issuer_id" not in out


def test_sanitize_drops_secrets_in_keys_and_values():
    out = sanitize_page_context(
        {
            "route": "/listing",
            "profile": "issuer_id=abc-123",
            "csv_path": "AuthKey_ABCDEF.p8",
            "iap_path": "data/iap_packages.json",
            "locale": "en-US",
            "fields": {"name": "api_key=sk-secret", "subtitle": "Safe subtitle"},
        }
    )
    assert out.get("route") == "/listing"
    assert out.get("locale") == "en-US"
    assert out.get("iap_path") == "data/iap_packages.json"
    assert "profile" not in out
    assert "csv_path" not in out
    fields = out.get("fields") or {}
    assert "name" not in fields
    assert fields.get("subtitle") == "Safe subtitle"


def test_sanitize_keeps_product_id_containing_token_word():
    out = sanitize_page_context(
        {"route": "/iap", "product_id": "com.app.token.pack", "phase": "edit"}
    )
    assert out.get("product_id") == "com.app.token.pack"
    assert out.get("phase") == "edit"


def test_sanitize_drops_password_token_and_blocked_paths():
    out = sanitize_page_context(
        {
            "phase": "edit",
            "product_id": "password=hunter2",
            "screenshots_path": "keys/shots",
            "iap_path": ".env",
            "csv_path": "data/appstore_info.csv",
        }
    )
    assert out.get("phase") == "edit"
    assert "product_id" not in out
    assert "screenshots_path" not in out
    assert "iap_path" not in out
    assert out.get("csv_path") == "data/appstore_info.csv"


def test_sanitize_drops_oversize_and_dotdot():
    out = sanitize_page_context(
        {
            "route": "x" * 65,
            "profile": "myapp",
            "locale": "x" * 17,
            "product_id": "x" * 129,
            "phase": "x" * 33,
            "csv_path": "x" * 513,
            "iap_path": "../secret/iap.json",
            "screenshots_path": "data/screenshots",
            "fields": {"name": "x" * 201, "subtitle": "ok", "whatsNew": "fixes"},
        }
    )
    assert "route" not in out
    assert out.get("profile") == "myapp"
    assert "locale" not in out
    assert "product_id" not in out
    assert "phase" not in out
    assert "csv_path" not in out
    assert "iap_path" not in out
    assert out.get("screenshots_path") == "data/screenshots"
    fields = out.get("fields") or {}
    assert "name" not in fields
    assert fields.get("subtitle") == "ok"
    assert fields.get("whatsNew") == "fixes"


def test_sanitize_fields_only_allowed_names():
    out = sanitize_page_context(
        {
            "fields": {
                "name": "App",
                "whatsNew": "Bug fixes",
                "secret": "nope",
                "description": "ok",
            }
        }
    )
    fields = out["fields"]
    assert fields["name"] == "App"
    assert fields["whatsNew"] == "Bug fixes"
    assert fields["description"] == "ok"
    assert "secret" not in fields


def test_sanitize_none_and_non_dict():
    assert sanitize_page_context(None) == {}
    assert sanitize_page_context(["route"]) == {}


def test_format_empty_dict_is_blank():
    assert format_page_context({}, "en") == ""
    assert format_page_context({}, "zh") == ""


def test_format_page_context_short_line():
    text = format_page_context(
        {
            "route": "/listing",
            "locale": "en-US",
            "csv_path": "data/appstore_info.csv",
        },
        "en",
    )
    assert text.startswith("[page]")
    assert "route=/listing" in text
    assert "locale=en-US" in text
    assert "csv=" in text
    assert "\n" not in text
