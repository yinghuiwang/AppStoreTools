"""Tests for src/asc/api.py

Mock 模式（默认）：mock requests.request，使用临时生成的 EC 私钥。
真实网络模式：ASC_TEST_LIVE=1，从 config/.env 读取真实凭据。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from asc.api import AppStoreConnectAPI


# ── Fixtures ──

@pytest.fixture
def ec_key_file(tmp_path):
    """生成真实 EC P-256 私钥，写入临时文件，返回路径字符串。"""
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "AuthKey_TEST.p8"
    key_file.write_bytes(pem)
    return str(key_file)


@pytest.fixture
def api(ec_key_file):
    return AppStoreConnectAPI(
        issuer_id="test-issuer",
        key_id="TESTKEYID",
        key_file=ec_key_file,
    )


# ── JWT token 缓存 ──

def test_token_cached_within_expiry(api):
    t1 = api.token
    t2 = api.token
    assert t1 == t2


def test_token_refreshed_after_expiry(api):
    t1 = api.token
    # 强制令过期
    api._token_expiry = None
    t2 = api.token
    assert t2
    assert isinstance(t2, str)


def test_token_signing_passes_private_key_bytes_to_pyjwt(tmp_path):
    key_file = tmp_path / "AuthKey_TEST.p8"
    key_file.write_bytes(b"fake-private-key")

    api = AppStoreConnectAPI(
        issuer_id="test-issuer",
        key_id="TESTKEYID",
        key_file=str(key_file),
    )

    with patch("asc.api.jwt.encode", return_value="signed-token") as mock_encode:
        assert api.token == "signed-token"

    assert mock_encode.call_args.args[1] == b"fake-private-key"


# ── _request: 429 重试 ──

def test_request_retries_on_429(api):
    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.json.return_value = {"data": "ok"}

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "0"}

    with patch("requests.request", side_effect=[rate_limited, ok_response]) as mock_req:
        with patch("time.sleep"):
            result = api._request("GET", "/v1/apps/123")

    assert result == {"data": "ok"}
    assert mock_req.call_count == 2


# ── _request: 4xx 抛出异常 ──

def test_request_raises_on_404(api):
    error_response = MagicMock()
    error_response.status_code = 404
    error_response.json.return_value = {
        "errors": [{"detail": "Not found", "title": "Not Found"}]
    }

    with patch("requests.request", return_value=error_response):
        with pytest.raises(Exception, match="404"):
            api._request("GET", "/v1/apps/missing")


def test_request_raises_on_401(api):
    error_response = MagicMock()
    error_response.status_code = 401
    error_response.json.return_value = {"errors": [{"detail": "Unauthorized"}]}

    with patch("requests.request", return_value=error_response):
        with pytest.raises(Exception, match="401"):
            api._request("GET", "/v1/apps/123")


# ── _request: 204 返回空字典 ──

def test_request_204_returns_empty_dict(api):
    response = MagicMock()
    response.status_code = 204

    with patch("requests.request", return_value=response):
        result = api._request("DELETE", "/v1/screenshots/abc")

    assert result == {}


def test_find_subscription_price_point_requests_all_price_points(api):
    price_points = {"data": [{"id": "pp1", "attributes": {"customerPrice": "9.99"}}]}
    with patch.object(api, "get", return_value=price_points) as mock_get:
        result = api.find_subscription_price_point("sub1", "USA", "9.99")

    assert result == "pp1"
    mock_get.assert_called_once_with(
        "/v1/subscriptions/sub1/pricePoints",
        limit=8000,
        **{"filter[territory]": "USA"},
    )


def test_create_subscription_price_allows_official_optional_fields(api):
    with patch.object(api, "post", return_value={"data": {"id": "price1"}}) as mock_post:
        api.create_subscription_price(
            "sub1",
            "pp1",
            "USA",
            start_date="2026-07-01",
            preserve_current_price=True,
        )

    payload = mock_post.call_args.args[1]
    assert payload["data"]["attributes"] == {
        "startDate": "2026-07-01",
        "preserveCurrentPrice": True,
    }
    relationships = payload["data"]["relationships"]
    assert relationships["subscription"]["data"]["id"] == "sub1"
    assert relationships["subscriptionPricePoint"]["data"]["id"] == "pp1"
    assert relationships["territory"]["data"]["id"] == "USA"


def test_create_in_app_purchase_availability_uses_official_resource(api):
    with patch.object(api, "post", return_value={"data": {"id": "avail1"}}) as mock_post:
        api.create_in_app_purchase_availability(
            "iap1",
            available_in_new_territories=True,
            territory_ids=["USA", "CHN"],
        )

    path, payload = mock_post.call_args.args
    assert path == "/v1/inAppPurchaseAvailabilities"
    assert payload["data"]["type"] == "inAppPurchaseAvailabilities"
    assert payload["data"]["attributes"] == {"availableInNewTerritories": True}
    relationships = payload["data"]["relationships"]
    assert relationships["inAppPurchase"]["data"] == {
        "type": "inAppPurchases",
        "id": "iap1",
    }
    assert relationships["availableTerritories"]["data"] == [
        {"type": "territories", "id": "USA"},
        {"type": "territories", "id": "CHN"},
    ]


def test_create_in_app_purchase_price_schedule_uses_official_resource(api):
    with patch.object(api, "post", return_value={"data": {"id": "sched1"}}) as mock_post:
        api.create_in_app_purchase_price_schedule(
            "iap1",
            "USA",
            [("USA", "pp1")],
            start_date="2026-07-01",
        )

    path, payload = mock_post.call_args.args
    assert path == "/v1/inAppPurchasePriceSchedules"
    assert payload["data"]["type"] == "inAppPurchasePriceSchedules"
    assert payload["data"]["relationships"]["inAppPurchase"]["data"] == {
        "type": "inAppPurchases",
        "id": "iap1",
    }
    assert payload["data"]["relationships"]["baseTerritory"]["data"] == {
        "type": "territories",
        "id": "USA",
    }
    assert payload["data"]["relationships"]["manualPrices"]["data"] == [
        {"type": "inAppPurchasePrices", "id": "${price-USA}"}
    ]
    assert payload["included"][0]["relationships"]["inAppPurchasePricePoint"]["data"] == {
        "type": "inAppPurchasePricePoints",
        "id": "pp1",
    }
    assert payload["included"][0]["attributes"] == {"startDate": "2026-07-01"}


def test_list_in_app_purchase_price_point_equalizations_uses_official_endpoint(api):
    with patch.object(api, "get", return_value={"data": []}) as mock_get:
        result = api.list_in_app_purchase_price_point_equalizations("pp1", "iap1")

    assert result == []
    mock_get.assert_called_once_with(
        "/v1/inAppPurchasePricePoints/pp1/equalizations",
        limit=8000,
        include="territory",
        **{"filter[inAppPurchaseV2]": "iap1"},
    )


def test_list_subscription_price_point_equalizations_uses_official_endpoint(api):
    with patch.object(api, "get", return_value={"data": []}) as mock_get:
        result = api.list_subscription_price_point_equalizations("pp1", "sub1")

    assert result == []
    mock_get.assert_called_once_with(
        "/v1/subscriptionPricePoints/pp1/equalizations",
        limit=8000,
        include="territory",
        **{"filter[subscription]": "sub1"},
    )


def test_list_in_app_purchases_follows_pagination(api):
    with patch.object(
        api,
        "get",
        side_effect=[
            {
                "data": [{"id": "iap1"}],
                "links": {"next": "https://api.appstoreconnect.apple.com/v1/page2"},
            },
            {"data": [{"id": "iap2"}], "links": {}},
        ],
    ) as mock_get:
        result = api.list_in_app_purchases("app123")

    assert [item["id"] for item in result] == ["iap1", "iap2"]
    assert mock_get.call_args_list == [
        call("/v1/apps/app123/inAppPurchasesV2", limit=200),
        call("https://api.appstoreconnect.apple.com/v1/page2"),
    ]


def test_list_subscription_groups_follows_pagination(api):
    with patch.object(
        api,
        "get",
        side_effect=[
            {
                "data": [{"id": "group1"}],
                "links": {"next": "https://api.appstoreconnect.apple.com/v1/groups2"},
            },
            {"data": [{"id": "group2"}], "links": {}},
        ],
    ) as mock_get:
        result = api.list_subscription_groups("app123")

    assert [item["id"] for item in result] == ["group1", "group2"]
    assert mock_get.call_args_list == [
        call("/v1/apps/app123/subscriptionGroups", limit=200),
        call("https://api.appstoreconnect.apple.com/v1/groups2"),
    ]


def test_list_subscriptions_follows_pagination(api):
    with patch.object(
        api,
        "get",
        side_effect=[
            {
                "data": [{"id": "sub1"}],
                "links": {"next": "https://api.appstoreconnect.apple.com/v1/subs2"},
            },
            {"data": [{"id": "sub2"}], "links": {}},
        ],
    ) as mock_get:
        result = api.list_subscriptions("group123")

    assert [item["id"] for item in result] == ["sub1", "sub2"]
    assert mock_get.call_args_list == [
        call("/v1/subscriptionGroups/group123/subscriptions", limit=200),
        call("https://api.appstoreconnect.apple.com/v1/subs2"),
    ]


def test_update_subscription_prices_inline_builds_compound_request(api):
    with patch.object(api, "patch", return_value={"data": {"id": "sub1"}}) as mock_patch:
        api.update_subscription_prices_inline(
            "sub1",
            [("USA", "pp_usa"), ("CHN", "pp_chn")],
            start_date="2026-07-01",
            preserve_current_price=True,
        )

    path, payload = mock_patch.call_args.args
    assert path == "/v1/subscriptions/sub1"
    assert payload["data"]["relationships"]["prices"]["data"] == [
        {"type": "subscriptionPrices", "id": "${price-USA}"},
        {"type": "subscriptionPrices", "id": "${price-CHN}"},
    ]
    included = payload["included"]
    assert included[0]["id"] == "${price-USA}"
    assert included[0]["attributes"] == {
        "startDate": "2026-07-01",
        "preserveCurrentPrice": True,
    }
    assert included[0]["relationships"]["territory"]["data"]["id"] == "USA"
    assert included[0]["relationships"]["subscriptionPricePoint"]["data"]["id"] == "pp_usa"


# ── get_editable_version ──

def _make_version(state: str, vid: str = "v1") -> dict:
    return {
        "id": vid,
        "attributes": {"appStoreState": state, "versionString": "1.0"},
    }


def test_get_editable_version_prefers_editable(api):
    versions = [
        _make_version("READY_FOR_SALE", "v1"),
        _make_version("PREPARE_FOR_SUBMISSION", "v2"),
    ]
    with patch.object(api, "get", return_value={"data": versions}):
        result = api.get_editable_version("app123")
    assert result["id"] == "v2"


def test_get_editable_version_falls_back_to_first(api):
    versions = [_make_version("READY_FOR_SALE", "v1")]
    with patch.object(api, "get", return_value={"data": versions}):
        result = api.get_editable_version("app123")
    assert result["id"] == "v1"


def test_get_editable_version_returns_none_when_empty(api):
    with patch.object(api, "get", return_value={"data": []}):
        result = api.get_editable_version("app123")
    assert result is None


# ── 真实网络模式 ──

LIVE = os.getenv("ASC_TEST_LIVE") == "1"
ENV_FILE = Path(__file__).parents[1] / "config" / ".env"


def _live_api():
    """从 config/.env 读取凭据，构造真实 API 实例。无凭据则 skip。"""
    if not LIVE:
        pytest.skip("ASC_TEST_LIVE 未设置，跳过真实网络测试")
    if not ENV_FILE.exists():
        pytest.skip("config/.env 不存在，跳过真实网络测试")

    from dotenv import dotenv_values
    env = dotenv_values(str(ENV_FILE))
    issuer_id = env.get("ISSUER_ID")
    key_id = env.get("KEY_ID")
    key_file = env.get("KEY_FILE")
    app_id = env.get("APP_ID")

    if not all([issuer_id, key_id, key_file, app_id]):
        pytest.skip("config/.env 缺少必要字段，跳过真实网络测试")

    key_path = Path(key_file)
    if not key_path.is_absolute():
        key_path = ENV_FILE.parent / key_path
    if not key_path.exists():
        pytest.skip(f"私钥文件不存在: {key_path}")

    return AppStoreConnectAPI(issuer_id, key_id, str(key_path)), app_id


@pytest.mark.skipif(not LIVE, reason="需要 ASC_TEST_LIVE=1")
def test_live_get_app():
    api, app_id = _live_api()
    resp = api.get_app(app_id)
    assert "data" in resp
    attrs = resp["data"]["attributes"]
    assert attrs.get("name")
    assert attrs.get("bundleId")


@pytest.mark.skipif(not LIVE, reason="需要 ASC_TEST_LIVE=1")
def test_live_get_app_infos():
    api, app_id = _live_api()
    infos = api.get_app_infos(app_id)
    assert isinstance(infos, list)
    assert len(infos) > 0


@pytest.mark.skipif(not LIVE, reason="需要 ASC_TEST_LIVE=1")
def test_live_get_editable_version():
    api, app_id = _live_api()
    version = api.get_editable_version(app_id)
    if version is not None:
        assert "id" in version
        assert "attributes" in version
