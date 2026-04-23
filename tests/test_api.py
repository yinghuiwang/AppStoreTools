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
