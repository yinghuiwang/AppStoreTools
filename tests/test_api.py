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
    assert mock_req.call_args.kwargs["timeout"] == (10, 60)


def test_request_429_wait_respects_cancel_event(api):
    import threading

    from asc.progress import ProcessCanceled

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "30"}

    cancel = threading.Event()
    api.cancel_event = cancel

    def set_cancel_soon():
        time.sleep(0.05)
        cancel.set()

    with patch("requests.request", return_value=rate_limited):
        t = threading.Thread(target=set_cancel_soon)
        t.start()
        with pytest.raises(ProcessCanceled, match="rate-limit"):
            api._request("GET", "/v1/apps/123")
        t.join(timeout=2.0)


def test_request_releases_inflight_slot_during_429_wait(api, monkeypatch):
    """429 Retry-After must not hold ASC_API_MAX_INFLIGHT (starves other pages)."""
    import threading

    import asc.api as api_mod

    monkeypatch.setenv("ASC_API_MAX_INFLIGHT", "1")
    api_mod._asc_inflight_sem = None
    api_mod._asc_inflight_limit = None

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "30"}

    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.json.return_value = {"data": "ok"}

    slot_free_during_wait = threading.Event()

    def fake_sleep(_seconds, cancel_event=None, chunk=0.5):
        del cancel_event, chunk
        sem = api_mod._get_asc_request_semaphore()
        if sem.acquire(blocking=False):
            slot_free_during_wait.set()
            sem.release()

    with patch("requests.request", side_effect=[rate_limited, ok_response]):
        with patch("asc.api._interruptible_sleep", side_effect=fake_sleep):
            result = api._request("GET", "/v1/apps/123")

    assert result == {"data": "ok"}
    assert slot_free_during_wait.is_set()


def test_request_inflight_semaphore_serializes_when_limit_one(api, monkeypatch):
    """ASC_API_MAX_INFLIGHT=1: second request waits until the first releases the slot."""
    import threading

    import asc.api as api_mod

    monkeypatch.setenv("ASC_API_MAX_INFLIGHT", "1")
    api_mod._asc_inflight_sem = None
    api_mod._asc_inflight_limit = None

    release_first = threading.Event()
    second_entered = threading.Event()
    call_order: list[str] = []
    order_lock = threading.Lock()

    def slow_request(*_args, **_kwargs):
        with order_lock:
            call_order.append("enter")
            is_second = call_order.count("enter") == 2
        if is_second:
            second_entered.set()
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"data": "second"}
            return resp
        assert release_first.wait(timeout=2.0)
        with order_lock:
            call_order.append("first_done")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": "first"}
        return resp

    errors: list[BaseException] = []

    def worker() -> None:
        try:
            api._request("GET", "/v1/apps/123")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with patch("requests.request", side_effect=slow_request):
        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        time.sleep(0.05)
        t2.start()
        time.sleep(0.2)
        assert not second_entered.is_set()
        release_first.set()
        assert second_entered.wait(timeout=2.0)
        t1.join(timeout=2.0)
        t2.join(timeout=2.0)

    assert not errors
    assert call_order[0] == "enter"
    assert "first_done" in call_order
    assert call_order.index("first_done") < call_order.index("enter", 1)


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
        limit=200,
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
        limit=200,
        include="territory",
        **{"filter[inAppPurchaseV2]": "iap1"},
    )


def test_list_subscription_price_point_equalizations_uses_official_endpoint(api):
    with patch.object(api, "get", return_value={"data": []}) as mock_get:
        result = api.list_subscription_price_point_equalizations("pp1", "sub1")

    assert result == []
    mock_get.assert_called_once_with(
        "/v1/subscriptionPricePoints/pp1/equalizations",
        limit=200,
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


def test_get_paginated_data_stops_on_repeated_next_link(api):
    """Broken ASC pagination that repeats links.next must not spin forever."""
    looping = {
        "data": [{"id": "iap1"}],
        "links": {"next": "https://api.appstoreconnect.apple.com/v1/same"},
    }
    with patch.object(api, "get", return_value=looping) as mock_get:
        result = api._get_paginated_data("/v1/apps/app123/inAppPurchasesV2", limit=200)

    assert [item["id"] for item in result] == ["iap1", "iap1"]
    assert mock_get.call_count == 2


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


def test_list_territories_cached_across_calls(api):
    with patch.object(
        api,
        "get",
        return_value={"data": [{"id": "USA"}, {"id": "CHN"}]},
    ) as mock_get:
        first = api.list_territories()
        second = api.list_territories()

    assert first == second == [{"id": "USA"}, {"id": "CHN"}]
    assert mock_get.call_count == 1
    mock_get.assert_called_once_with("/v1/territories", limit=200)


def test_list_territories_follows_pagination(api):
    with patch.object(
        api,
        "get",
        side_effect=[
            {
                "data": [{"id": "USA"}],
                "links": {
                    "next": "https://api.appstoreconnect.apple.com/v1/territories?cursor=2"
                },
            },
            {"data": [{"id": "CHN"}], "links": {}},
        ],
    ) as mock_get:
        result = api.list_territories()

    assert [t["id"] for t in result] == ["USA", "CHN"]
    assert mock_get.call_count == 2
    assert api.list_territories() == result
    assert mock_get.call_count == 2


def test_list_subscription_prices_follows_pagination(api):
    with patch.object(
        api,
        "get",
        side_effect=[
            {
                "data": [{"id": "p1"}],
                "links": {"next": "https://api.appstoreconnect.apple.com/v1/prices2"},
            },
            {"data": [{"id": "p2"}], "links": {}},
        ],
    ) as mock_get:
        result = api.list_subscription_prices("sub1")

    assert [p["id"] for p in result] == ["p1", "p2"]
    assert mock_get.call_args_list == [
        call("/v1/subscriptions/sub1/prices", limit=200),
        call("https://api.appstoreconnect.apple.com/v1/prices2"),
    ]


def test_list_subscription_localizations_follows_pagination(api):
    with patch.object(
        api,
        "get",
        side_effect=[
            {
                "data": [{"id": "loc1"}],
                "links": {"next": "https://api.appstoreconnect.apple.com/v1/locs2"},
            },
            {"data": [{"id": "loc2"}], "links": {}},
        ],
    ):
        result = api.list_subscription_localizations("sub1")
    assert [item["id"] for item in result] == ["loc1", "loc2"]


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


# ── Binary asset PUT retry / timeout ──

def _upload_ops(url="https://upload.example.test/chunk", size=100, headers=None):
    return [
        {
            "url": url,
            "offset": 0,
            "length": size,
            "requestHeaders": headers
            or [{"name": "Content-Type", "value": "image/jpeg"}],
        }
    ]


def _write_timeout_error():
    """Match production: urllib3 SSL write timeout wrapped by requests."""
    from requests.exceptions import ConnectionError as RequestsConnectionError
    from urllib3.exceptions import ProtocolError

    return RequestsConnectionError(
        ProtocolError(
            "Connection aborted.",
            TimeoutError("The write operation timed out"),
        )
    )


def _ok_put_response(status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = "ok"
    return resp


def test_upload_timeout_tuple_is_write_friendly():
    from asc.api import UPLOAD_TIMEOUT

    assert isinstance(UPLOAD_TIMEOUT, tuple)
    connect, read = UPLOAD_TIMEOUT
    assert connect >= 30
    assert read >= 300


def test_upload_screenshot_asset_retries_write_timeout_then_succeeds(api, tmp_path):
    from asc.api import UPLOAD_TIMEOUT

    payload = b"x" * 100
    shot = tmp_path / "4.jpg"
    shot.write_bytes(payload)
    logs: list[str] = []

    with patch(
        "requests.put",
        side_effect=[_write_timeout_error(), _ok_put_response()],
    ) as mock_put:
        with patch("asc.api._interruptible_sleep"):
            api.upload_screenshot_asset(
                _upload_ops(size=len(payload)),
                shot,
                log=logs.append,
            )

    assert mock_put.call_count == 2
    assert mock_put.call_args.kwargs["timeout"] == UPLOAD_TIMEOUT
    assert mock_put.call_args.kwargs["data"] == payload
    joined = "\n".join(logs)
    assert "1/" in joined
    assert "重试" in joined or "Retry" in joined


def test_upload_screenshot_asset_raises_clear_error_after_retries_exhausted(api, tmp_path):
    from asc.api import AssetUploadError

    shot = tmp_path / "4.jpg"
    shot.write_bytes(b"x" * 80)
    logs: list[str] = []

    with patch("requests.put", side_effect=_write_timeout_error()) as mock_put:
        with patch("asc.api._interruptible_sleep"):
            with pytest.raises(AssetUploadError) as ei:
                api.upload_screenshot_asset(
                    _upload_ops(size=80),
                    shot,
                    log=logs.append,
                )

    assert mock_put.call_count >= 3
    assert mock_put.call_count <= 8
    msg = str(ei.value)
    assert "Connection aborted" not in msg
    assert "TimeoutError" not in msg
    assert "4.jpg" in msg or "截图" in msg or "screenshot" in msg.lower() or "上传" in msg
    joined = "\n".join(logs)
    assert "1/" in joined


def test_upload_in_app_purchase_review_screenshot_retries_read_timeout(api):
    from requests.exceptions import ReadTimeout

    payload = b"iap-shot"
    with patch(
        "requests.put",
        side_effect=[ReadTimeout("Read timed out"), _ok_put_response()],
    ) as mock_put:
        with patch("asc.api._interruptible_sleep"):
            api.upload_in_app_purchase_review_screenshot(
                _upload_ops(size=len(payload)),
                payload,
            )

    assert mock_put.call_count == 2


def test_upload_subscription_review_screenshot_retries_protocol_error(api):
    from urllib3.exceptions import ProtocolError

    payload = b"sub-shot"
    with patch(
        "requests.put",
        side_effect=[ProtocolError("Connection aborted."), _ok_put_response()],
    ) as mock_put:
        with patch("asc.api._interruptible_sleep"):
            api.upload_subscription_review_screenshot(
                _upload_ops(size=len(payload)),
                payload,
            )

    assert mock_put.call_count == 2


def test_upload_screenshot_asset_refetches_operations_on_403(api, tmp_path):
    payload = b"y" * 40
    shot = tmp_path / "1.jpg"
    shot.write_bytes(payload)
    stale = _upload_ops("https://upload.example.test/stale", size=len(payload))
    fresh = _upload_ops("https://upload.example.test/fresh", size=len(payload))

    forbidden = MagicMock()
    forbidden.status_code = 403
    forbidden.text = "Expired token"

    with patch("requests.put", side_effect=[forbidden, _ok_put_response()]) as mock_put:
        with patch("asc.api._interruptible_sleep"):
            with patch.object(
                api,
                "get",
                return_value={"data": {"attributes": {"uploadOperations": fresh}}},
            ) as mock_get:
                api.upload_screenshot_asset(
                    stale,
                    shot,
                    screenshot_id="shot_1",
                )

    mock_get.assert_called_once()
    urls = [c.args[0] for c in mock_put.call_args_list]
    assert urls[0] == "https://upload.example.test/stale"
    assert urls[-1] == "https://upload.example.test/fresh"


def test_upload_screenshot_asset_does_not_retry_http_401(api, tmp_path):
    from asc.api import AssetUploadError

    shot = tmp_path / "1.jpg"
    shot.write_bytes(b"z" * 10)
    unauthorized = MagicMock()
    unauthorized.status_code = 401
    unauthorized.text = "nope"

    with patch("requests.put", return_value=unauthorized) as mock_put:
        with pytest.raises(AssetUploadError, match="401"):
            api.upload_screenshot_asset(_upload_ops(size=10), shot)

    assert mock_put.call_count == 1


def test_upload_screenshot_asset_retries_http_503_then_succeeds(api, tmp_path):
    shot = tmp_path / "1.jpg"
    shot.write_bytes(b"x" * 10)
    unavailable = MagicMock()
    unavailable.status_code = 503
    unavailable.text = "busy"

    with patch("requests.put", side_effect=[unavailable, _ok_put_response()]):
        with patch("asc.api._interruptible_sleep"):
            api.upload_screenshot_asset(_upload_ops(size=10), shot)


def test_upload_screenshot_asset_exhausted_http_502_keeps_status(api, tmp_path):
    from asc.api import AssetUploadError

    shot = tmp_path / "1.jpg"
    shot.write_bytes(b"x" * 10)
    bad_gateway = MagicMock()
    bad_gateway.status_code = 502
    bad_gateway.text = "bad gateway"

    with patch("requests.put", return_value=bad_gateway) as mock_put:
        with patch("asc.api._interruptible_sleep"):
            with pytest.raises(AssetUploadError, match="502"):
                api.upload_screenshot_asset(_upload_ops(size=10), shot)

    assert mock_put.call_count >= 3


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
