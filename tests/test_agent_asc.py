"""Read-only ASC agent tools. Mock AppStoreConnectAPI; never hit the network."""
from __future__ import annotations

from unittest.mock import MagicMock

from asc.web.agent_asc import _api_for_profile, get_asc_version, list_asc_iaps
from asc.web.agent_tools import (
    MODEL_TOOL_NAMES,
    OPENAI_TOOLS,
    AgentToolContext,
    execute_model_tool,
)
from asc.web.tasks import TaskStore


class _Cfg:
    def __init__(self, **kwargs):
        self.issuer_id = kwargs.get("issuer_id", "iss")
        self.key_id = kwargs.get("key_id", "kid")
        self.key_file = kwargs.get("key_file", "/tmp/key.p8")
        self.app_id = kwargs.get("app_id", "app123")


def _ctx(tmp_path, store, *, profile="", task_id=None):
    return AgentToolContext(
        task_store=store,
        agent_store=None,
        bound_task_id=task_id,
        project_root=tmp_path,
        turn_seq=1,
        profile=profile,
    )


def _patch_creds(monkeypatch, **kwargs):
    cfg = _Cfg(**kwargs)
    monkeypatch.setattr("asc.web.agent_asc.Config", lambda app_name=None: cfg)
    api = MagicMock()
    monkeypatch.setattr("asc.web.agent_asc.AppStoreConnectAPI", lambda *a, **k: api)
    return api


def test_api_for_profile_missing_credentials(monkeypatch):
    monkeypatch.setattr(
        "asc.web.agent_asc.Config",
        lambda app_name=None: _Cfg(issuer_id="", key_id="", key_file="", app_id=""),
    )
    constructed = []
    monkeypatch.setattr(
        "asc.web.agent_asc.AppStoreConnectAPI",
        lambda *a, **k: constructed.append((a, k)) or MagicMock(),
    )
    api, err = _api_for_profile("myapp")
    assert api is None
    assert err == "credentials missing"
    assert constructed == []


def test_api_for_profile_empty_profile_is_credentials_missing(monkeypatch):
    api, err = _api_for_profile("")
    assert api is None
    assert err == "credentials missing"


def test_api_for_profile_builds_api_without_make_api_from_config(monkeypatch):
    monkeypatch.setattr("asc.web.agent_asc.Config", lambda app_name=None: _Cfg())
    mock_cls = MagicMock()
    monkeypatch.setattr("asc.web.agent_asc.AppStoreConnectAPI", mock_cls)
    called = []

    def boom(*_a, **_k):
        called.append(True)
        raise AssertionError("make_api_from_config must not be used")

    monkeypatch.setattr("asc.utils.make_api_from_config", boom)
    api, app_id = _api_for_profile("myapp")
    mock_cls.assert_called_once_with("iss", "kid", "/tmp/key.p8")
    assert api is mock_cls.return_value
    assert app_id == "app123"
    assert called == []


def test_get_asc_version_returns_version_and_state(monkeypatch):
    api = _patch_creds(monkeypatch)
    api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {
            "versionString": "1.2.3",
            "appStoreState": "PREPARE_FOR_SUBMISSION",
        },
    }
    result = get_asc_version("myapp")
    assert result == {
        "ok": True,
        "version": "1.2.3",
        "state": "PREPARE_FOR_SUBMISSION",
    }
    api.get_editable_version.assert_called_once_with("app123")


def test_get_asc_version_falls_back_to_app_version_state(monkeypatch):
    api = _patch_creds(monkeypatch)
    api.get_editable_version.return_value = {
        "attributes": {
            "versionString": "2.0",
            "appVersionState": "REJECTED",
        },
    }
    result = get_asc_version("myapp")
    assert result["ok"] is True
    assert result["version"] == "2.0"
    assert result["state"] == "REJECTED"


def test_get_asc_version_no_editable_version(monkeypatch):
    api = _patch_creds(monkeypatch)
    api.get_editable_version.return_value = None
    result = get_asc_version("myapp")
    assert result == {"ok": True, "exists": False, "code": "no_editable_version"}


def test_get_asc_version_credentials_missing(monkeypatch):
    monkeypatch.setattr(
        "asc.web.agent_asc.Config",
        lambda app_name=None: _Cfg(issuer_id="", key_id="k", key_file="f", app_id="a"),
    )
    result = get_asc_version("myapp")
    assert result == {"ok": False, "error": "credentials missing"}


def test_get_asc_version_redacts_api_errors(monkeypatch):
    api = _patch_creds(monkeypatch)
    api.get_editable_version.side_effect = RuntimeError(
        "issuer_id=SECRET123 failed AuthKey_ABC12.p8"
    )
    result = get_asc_version("myapp")
    assert result["ok"] is False
    assert "SECRET123" not in result["error"]
    assert "AuthKey_ABC12.p8" not in result["error"]
    assert "issuer_id" not in str(result).lower() or "SECRET123" not in str(result)


def test_list_asc_iaps_maps_and_caps_fifty(monkeypatch):
    api = _patch_creds(monkeypatch)
    records = []
    for i in range(51):
        attrs = {
            "productId": f"com.app.item{i}",
            "inAppPurchaseType": "CONSUMABLE",
        }
        if i % 2 == 0:
            attrs["name"] = f"Name {i}"
        else:
            attrs["referenceName"] = f"Ref {i}"
        records.append({"id": f"iap{i}", "attributes": attrs})
    api.list_in_app_purchases.return_value = records
    result = list_asc_iaps("myapp")
    assert result["ok"] is True
    assert result["truncated"] is True
    assert len(result["items"]) == 50
    assert result["items"][0] == {
        "productId": "com.app.item0",
        "name": "Name 0",
        "type": "CONSUMABLE",
    }
    assert result["items"][1] == {
        "productId": "com.app.item1",
        "name": "Ref 1",
        "type": "CONSUMABLE",
    }
    api.list_in_app_purchases.assert_called_once_with("app123")
    api.get_in_app_purchase_price_schedule.assert_not_called()


def test_list_asc_iaps_not_truncated_under_cap(monkeypatch):
    api = _patch_creds(monkeypatch)
    api.list_in_app_purchases.return_value = [
        {
            "attributes": {
                "productId": "com.app.coins",
                "name": "Coins",
                "inAppPurchaseType": "CONSUMABLE",
            }
        }
    ]
    result = list_asc_iaps("myapp")
    assert result == {
        "ok": True,
        "items": [
            {"productId": "com.app.coins", "name": "Coins", "type": "CONSUMABLE"}
        ],
        "truncated": False,
    }


def test_list_asc_iaps_credentials_missing(monkeypatch):
    monkeypatch.setattr(
        "asc.web.agent_asc.Config",
        lambda app_name=None: _Cfg(app_id=""),
    )
    result = list_asc_iaps("myapp")
    assert result == {"ok": False, "error": "credentials missing"}


def test_list_asc_iaps_redacts_api_errors(monkeypatch):
    api = _patch_creds(monkeypatch)
    api.list_in_app_purchases.side_effect = RuntimeError("api_key=SUPERSECRET boom")
    result = list_asc_iaps("myapp")
    assert result["ok"] is False
    assert "SUPERSECRET" not in result["error"]


def test_tools_are_advertised():
    names = {item["function"]["name"] for item in OPENAI_TOOLS}
    assert "get_asc_version" in MODEL_TOOL_NAMES
    assert "list_asc_iaps" in MODEL_TOOL_NAMES
    assert "get_asc_version" in names
    assert "list_asc_iaps" in names


def test_tool_get_asc_version_defaults_to_ctx_profile(tmp_path, monkeypatch):
    api = _patch_creds(monkeypatch)
    api.get_editable_version.return_value = {
        "attributes": {"versionString": "9.0", "appStoreState": "IN_REVIEW"}
    }
    store = TaskStore(tmp_path / "tasks.db")
    result = execute_model_tool(
        _ctx(tmp_path, store, profile="myapp"),
        "get_asc_version",
        {},
    )
    assert result["ok"] is True
    assert result["version"] == "9.0"
    store.close()


def test_tool_list_asc_iaps_uses_argument_profile(tmp_path, monkeypatch):
    seen = {}

    class _NamedCfg(_Cfg):
        def __init__(self, app_name=None):
            seen["profile"] = app_name
            super().__init__()

    monkeypatch.setattr("asc.web.agent_asc.Config", _NamedCfg)
    api = MagicMock()
    api.list_in_app_purchases.return_value = []
    monkeypatch.setattr("asc.web.agent_asc.AppStoreConnectAPI", lambda *a, **k: api)
    store = TaskStore(tmp_path / "tasks.db")
    result = execute_model_tool(
        _ctx(tmp_path, store, profile="ctxapp"),
        "list_asc_iaps",
        {"profile": "argapp"},
    )
    assert result["ok"] is True
    assert seen["profile"] == "argapp"
    store.close()


def test_tool_get_asc_version_falls_back_to_task_profile(tmp_path, monkeypatch):
    seen = {}

    class _NamedCfg(_Cfg):
        def __init__(self, app_name=None):
            seen["profile"] = app_name
            super().__init__()

    monkeypatch.setattr("asc.web.agent_asc.Config", _NamedCfg)
    api = MagicMock()
    api.get_editable_version.return_value = None
    monkeypatch.setattr("asc.web.agent_asc.AppStoreConnectAPI", lambda *a, **k: api)
    store = TaskStore(tmp_path / "tasks.db")
    task_id = store.create("metadata", profile="taskapp")
    result = execute_model_tool(
        _ctx(tmp_path, store, profile="", task_id=task_id),
        "get_asc_version",
        {},
    )
    assert result["ok"] is True
    assert result["code"] == "no_editable_version"
    assert seen["profile"] == "taskapp"
    store.close()
