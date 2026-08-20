"""HTTP tests for /api/iap workflow endpoints."""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from asc.web.server import create_app


@pytest.fixture(autouse=True)
def isolated_guard(monkeypatch):
    monkeypatch.setattr("asc.web.routes_api.enforce_config_guard", MagicMock())
    monkeypatch.setattr("asc.web.routes_iap.enforce_config_guard", MagicMock())
    monkeypatch.setattr("asc.web.routes_listing.enforce_config_guard", MagicMock())


@pytest.fixture
def client():
    return TestClient(create_app())


def test_local_missing_file_returns_empty_snapshot(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "data" / "iap_packages.json"
    mock_config = MagicMock()
    mock_config.iap_path = str(missing)
    with patch("asc.web.routes_iap.Config", return_value=mock_config):
        resp = client.get("/api/iap/local", cookies={"asc_profile": "testapp"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["exists"] is False
    assert data["snapshot"] == {"items": [], "subscriptionGroups": []}
    assert data["hasContent"] is False


def test_local_save_mtime_conflict(client, tmp_path):
    path = tmp_path / "iap.json"
    path.write_text(
        json.dumps({"items": [{"productId": "a", "inAppPurchaseType": "CONSUMABLE"}], "subscriptionGroups": []}),
        encoding="utf-8",
    )
    mtime = path.stat().st_mtime
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    mock_config = MagicMock()
    mock_config.iap_path = str(path)
    with patch("asc.web.routes_iap.Config", return_value=mock_config):
        resp = client.post(
            "/api/iap/local/save",
            cookies={"asc_profile": "testapp"},
            json={
                "iapFile": str(path),
                "expected_mtime": mtime,
                "snapshot": {
                    "items": [{"productId": "b", "inAppPurchaseType": "CONSUMABLE"}],
                    "subscriptionGroups": [],
                },
            },
        )
    assert resp.status_code == 409


def test_infer_returns_draft_without_group_level(client, tmp_path):
    mock_config = MagicMock()
    mock_config.iap_path = str(tmp_path / "iap.json")
    table = "productId\tname\tprice\ncom.app.year.49.99\tYear\t49.99\n"
    with patch("asc.web.routes_iap.Config", return_value=mock_config):
        resp = client.post(
            "/api/iap/infer",
            cookies={"asc_profile": "testapp"},
            json={"text": table},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["groupLevelHelp"]
    subs = data["snapshot"]["subscriptionGroups"][0]["subscriptions"]
    assert "groupLevel" not in subs[0]
    assert not (tmp_path / "iap.json").exists()


def test_plan_uses_thread_and_returns_actions(client, tmp_path):
    path = tmp_path / "iap.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "productId": "com.app.coins",
                        "name": "Coins",
                        "inAppPurchaseType": "CONSUMABLE",
                    }
                ],
                "subscriptionGroups": [],
            }
        ),
        encoding="utf-8",
    )
    mock_config = MagicMock()
    mock_config.iap_path = str(path)
    remote = {
        "items": [
            {
                "productId": "com.app.coins",
                "name": "Coins",
                "inAppPurchaseType": "CONSUMABLE",
            }
        ],
        "subscriptionGroups": [],
    }
    with patch("asc.web.routes_iap.Config", return_value=mock_config), patch(
        "asc.web.routes_iap.make_api_from_config", return_value=(MagicMock(), "app1")
    ), patch("asc.web.routes_iap.pull_remote_snapshot", return_value=remote):
        resp = client.get(
            "/api/iap/plan",
            cookies={"asc_profile": "testapp"},
            params={"iap_file": str(path)},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["items"][0]["action"] == "skip"
    assert data["items"][0]["status"] == "equal"
    assert data["items"][0]["missingScreenshot"] is True


def test_compare_returns_task_result_with_plan_and_missing_store(client, tmp_path):
    import time
    from types import SimpleNamespace

    from asc.web import routes_iap
    from asc.web.tasks import TaskStatus

    path = tmp_path / "iap.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "productId": "com.app.coins",
                        "name": "Coins",
                        "inAppPurchaseType": "CONSUMABLE",
                    }
                ],
                "subscriptionGroups": [],
            }
        ),
        encoding="utf-8",
    )
    mock_config = MagicMock()
    mock_config.iap_path = str(path)
    remote = {
        "items": [
            {
                "productId": "com.app.coins",
                "name": "Coins",
                "inAppPurchaseType": "CONSUMABLE",
            }
        ],
        "subscriptionGroups": [],
    }

    def fake_pull(api, app_id, reporter=None, cancel_event=None, **_kwargs):
        if reporter is not None:
            reporter.phase("iap")
            reporter.progress(1, 1, msg="ok")
            reporter.phase("groups")
            reporter.progress(1, 1, msg="ok")
        return remote

    scan = SimpleNamespace(targets=[SimpleNamespace(product_id="com.app.coins")], errors=[])
    with patch("asc.web.routes_iap.Config", return_value=mock_config), patch(
        "asc.web.routes_iap.make_api_from_config", return_value=(MagicMock(), "app1")
    ), patch("asc.web.routes_iap.pull_remote_snapshot", side_effect=fake_pull), patch(
        "asc.web.routes_iap.scan_missing_review_screenshots", return_value=scan
    ):
        resp = client.post(
            "/api/iap/compare",
            cookies={"asc_profile": "testapp"},
            json={"iapFile": str(path)},
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]
        task = None
        for _ in range(100):
            task = routes_iap._task_store.get(task_id)
            if task and task["status"] in {TaskStatus.DONE, TaskStatus.ERROR, TaskStatus.CANCELED}:
                break
            time.sleep(0.02)

    assert task is not None
    assert task["status"] == TaskStatus.DONE
    assert task["kind"] == "iap-compare"
    result = task["result"]
    assert result["ok"] is True
    assert result["items"][0]["action"] == "skip"
    assert result["items"][0]["status"] == "equal"
    assert result["missingOnStore"] == ["com.app.coins"]
    progress = task.get("progress") or {}
    assert progress.get("phase") == "done"
    assert progress.get("phase_label") == "完成"
    assert int(progress.get("pct") or 0) == 100
    raw_logs = task.get("logs") or []
    texts = [row["message"] if isinstance(row, dict) else str(row) for row in raw_logs]
    assert "核对完成" in "\n".join(texts)


def _mock_pull_config(path: Path, remote: dict):
    mock_config = MagicMock()
    mock_config.iap_path = str(path)
    return (
        patch("asc.web.routes_iap.Config", return_value=mock_config),
        patch("asc.web.routes_iap.make_api_from_config", return_value=(MagicMock(), "app1")),
        patch("asc.web.routes_iap.pull_remote_snapshot", return_value=remote),
    )


def test_pull_accepts_frontend_create_payload_with_store_types(client, tmp_path):
    """CreateStep「从商店导入」body: iapFile + expected_mtime + empty groupNames + write."""
    path = tmp_path / "iap.json"
    path.write_text(
        json.dumps({"items": [], "subscriptionGroups": []}),
        encoding="utf-8",
    )
    mtime = path.stat().st_mtime
    remote = {
        "items": [
            {
                "productId": "com.app.coins",
                "name": "Coins",
                "inAppPurchaseType": "CONSUMABLE",
            },
            {
                "productId": "com.app.pass",
                "name": "Season Pass",
                "inAppPurchaseType": "NON_RENEWING_SUBSCRIPTION",
            },
        ],
        "subscriptionGroups": [],
    }
    patches = _mock_pull_config(path, remote)
    with patches[0], patches[1], patches[2]:
        resp = client.post(
            "/api/iap/pull",
            cookies={"asc_profile": "testapp"},
            json={
                "iapFile": str(path),
                "expected_mtime": mtime,
                "groupNames": [],
                "write": True,
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    ids = [item["productId"] for item in data["snapshot"]["items"]]
    assert ids == ["com.app.coins", "com.app.pass"]
    assert data["written"] is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert {item["productId"] for item in saved["items"]} == {
        "com.app.coins",
        "com.app.pass",
    }


def test_pull_accepts_frontend_overwrite_payload(client, tmp_path):
    """EditStep / dialog「用商店覆盖此条」body: productIds + expected_mtime + write."""
    path = tmp_path / "iap.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "productId": "com.app.pass",
                        "name": "Old",
                        "inAppPurchaseType": "NON_RENEWING_SUBSCRIPTION",
                    }
                ],
                "subscriptionGroups": [],
            }
        ),
        encoding="utf-8",
    )
    mtime = path.stat().st_mtime
    remote = {
        "items": [
            {
                "productId": "com.app.pass",
                "name": "From store",
                "inAppPurchaseType": "NON_RENEWING_SUBSCRIPTION",
            }
        ],
        "subscriptionGroups": [],
    }
    patches = _mock_pull_config(path, remote)
    with patches[0], patches[1], patches[2]:
        resp = client.post(
            "/api/iap/pull",
            cookies={"asc_profile": "testapp"},
            json={
                "iapFile": str(path),
                "productIds": ["com.app.pass"],
                "expected_mtime": mtime,
                "write": True,
            },
        )
    assert resp.status_code == 200, resp.text
    item = resp.json()["snapshot"]["items"][0]
    assert item["name"] == "From store"
    assert item["inAppPurchaseType"] == "NON_RENEWING_SUBSCRIPTION"
    assert resp.json()["written"] is True


def test_pull_preserves_review_screenshot(client, tmp_path):
    path = tmp_path / "iap.json"
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "productId": "com.app.coins",
                        "name": "Old",
                        "inAppPurchaseType": "CONSUMABLE",
                        "review": {"screenshot": "./iap_review/coins.png"},
                    }
                ],
                "subscriptionGroups": [],
            }
        ),
        encoding="utf-8",
    )
    mock_config = MagicMock()
    mock_config.iap_path = str(path)
    remote = {
        "items": [
            {
                "productId": "com.app.coins",
                "name": "From store",
                "inAppPurchaseType": "CONSUMABLE",
                "review": {"screenshot": ""},
            }
        ],
        "subscriptionGroups": [],
    }
    with patch("asc.web.routes_iap.Config", return_value=mock_config), patch(
        "asc.web.routes_iap.make_api_from_config", return_value=(MagicMock(), "app1")
    ), patch("asc.web.routes_iap.pull_remote_snapshot", return_value=remote):
        resp = client.post(
            "/api/iap/pull",
            cookies={"asc_profile": "testapp"},
            json={"iapFile": str(path), "productIds": ["com.app.coins"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    item = data["snapshot"]["items"][0]
    assert item["name"] == "From store"
    assert item["review"]["screenshot"] == "./iap_review/coins.png"
    assert data.get("written") is False
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["items"][0]["name"] == "Old"
    assert saved["items"][0]["review"]["screenshot"] == "./iap_review/coins.png"


def test_pull_write_false_returns_snapshot_without_saving(client, tmp_path):
    path = tmp_path / "iap.json"
    original = {
        "items": [
            {
                "productId": "com.app.coins",
                "name": "Local",
                "inAppPurchaseType": "CONSUMABLE",
            }
        ],
        "subscriptionGroups": [],
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    remote = {
        "items": [
            {
                "productId": "com.app.coins",
                "name": "From store",
                "inAppPurchaseType": "CONSUMABLE",
            },
            {
                "productId": "com.app.pass",
                "name": "Season Pass",
                "inAppPurchaseType": "NON_RENEWING_SUBSCRIPTION",
            },
        ],
        "subscriptionGroups": [],
    }
    patches = _mock_pull_config(path, remote)
    with patches[0], patches[1], patches[2]:
        resp = client.post(
            "/api/iap/pull",
            cookies={"asc_profile": "testapp"},
            json={
                "iapFile": str(path),
                "groupNames": [],
                "write": False,
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["written"] is False
    ids = [item["productId"] for item in data["snapshot"]["items"]]
    assert "com.app.coins" in ids
    assert "com.app.pass" in ids
    names = {item["productId"]: item["name"] for item in data["snapshot"]["items"]}
    assert names["com.app.coins"] == "From store"
    assert path.read_text(encoding="utf-8") == before
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["items"][0]["name"] == "Local"


def test_pull_preview_alias_does_not_write(client, tmp_path):
    path = tmp_path / "iap.json"
    path.write_text(
        json.dumps({"items": [], "subscriptionGroups": []}),
        encoding="utf-8",
    )
    remote = {
        "items": [
            {
                "productId": "com.app.coins",
                "name": "Coins",
                "inAppPurchaseType": "CONSUMABLE",
            }
        ],
        "subscriptionGroups": [],
    }
    patches = _mock_pull_config(path, remote)
    with patches[0], patches[1], patches[2]:
        resp = client.post(
            "/api/iap/pull",
            cookies={"asc_profile": "testapp"},
            json={"iapFile": str(path), "preview": True},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["written"] is False
    assert data["snapshot"]["items"][0]["productId"] == "com.app.coins"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["items"] == []


def test_translate_returns_in_request(client):
    mock_config = MagicMock()
    mock_config.llm_api_key = "sk-test"
    mock_config.llm_base_url = "https://example.com"
    mock_config.llm_model = "gpt"
    translator = MagicMock()
    translator.translate_fields.return_value = {
        "locale": "zh-Hans",
        "name": "金币",
        "description": "立即获得金币。",
    }
    with patch("asc.web.routes_iap.Config", return_value=mock_config), patch(
        "asc.web.routes_iap.make_iap_translator", return_value=translator
    ):
        resp = client.post(
            "/api/iap/translate",
            cookies={"asc_profile": "testapp"},
            json={
                "source_locale": "en-US",
                "mode": "translate",
                "fields": [
                    {"locale": "zh-Hans", "name": "Coins", "description": "Get coins."}
                ],
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" not in data
    assert data["translations"][0]["name"] == "金币"
    translator.translate_fields.assert_called_once()


def test_translate_without_llm_key_returns_400(client):
    mock_config = MagicMock()
    mock_config.llm_api_key = ""
    with patch("asc.web.routes_iap.Config", return_value=mock_config):
        resp = client.post(
            "/api/iap/translate",
            cookies={"asc_profile": "testapp"},
            json={
                "source_locale": "en-US",
                "fields": [{"locale": "zh-Hans", "name": "Coins", "description": "x"}],
            },
        )
    assert resp.status_code == 400
    assert "api_key" in json.dumps(resp.json())


def test_plan_is_sync_def():
    import inspect
    from asc.web import routes_iap

    assert not inspect.iscoroutinefunction(routes_iap.iap_plan)
    assert inspect.iscoroutinefunction(routes_iap.iap_compare)
    assert inspect.iscoroutinefunction(routes_iap.iap_translate)
    src = inspect.getsource(routes_iap.iap_translate)
    assert "to_thread" in src
    compare_src = inspect.getsource(routes_iap.iap_compare)
    assert "to_thread" in compare_src
    starter = inspect.getsource(routes_iap._start_iap_compare_task)
    assert "start_background_task" in starter
    assert 'kind="iap-compare"' in starter
    assert "reporter.set_phases" in starter
    assert "_iap_compare_phase_plan" in starter
    assert "scan_missing_review_screenshots" in starter
    assert "ProcessCanceled" in starter


def test_wizard_views_exist():
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    iap = (root / "views/IapView.vue").read_text(encoding="utf-8")
    assert "<t-steps" in iap
    assert "t-step-item" in iap
    assert 'v-model:current="current"' in iap
    assert ':readonly="false"' in iap
    assert "iap.step.create" in iap
    assert "iap.step.edit" in iap
    assert "iap.step.upload" in iap
    assert "position: sticky" in iap or "position: fixed" in iap
    assert "background: var(--bg)" in iap
    assert "var(--iap-footer-h)" in iap
    assert "justify-content: flex-end" in iap
    assert "CreateStep" in iap
    assert "EditStep" in iap
    assert "UploadStep" in iap
    assert "useIapWorkflow" in iap
    assert "appliedTick" in iap
    assert 'hasContent.value ? "edit"' not in iap
    assert "didDefault" not in iap
    assert 'step.value = "edit"' not in iap
    mounted = re.search(r"onMounted\(async \(\) => \{.*?\}\);", iap, re.S)
    assert mounted, "IapView onMounted missing"
    assert "hasContent" not in mounted.group(0)
    applied = re.search(r"watch\(appliedTick, \(\) => \{.*?\}\);", iap, re.S)
    assert applied, "IapView appliedTick watcher missing"
    assert "workflow.reload()" in applied.group(0)
    assert "hasContent" not in applied.group(0)
    assert "edit" not in applied.group(0)
    assert "ensureCompare" not in iap
    assert "/api/iap/compare" not in iap
    assert "/api/iap/plan" not in iap
    assert "/api/iap/pull" not in iap
    assert "?step=" not in iap or "step" in iap
    create = (root / "views/iap/CreateStep.vue").read_text(encoding="utf-8")
    assert "/api/iap/infer" in create
    assert "SUBSCRIPTION" in create
    assert 'source.value = "json"' in create
    assert 'const source = ref<Source>("table")' in create or "source = ref<Source>(\"table\")" in create
    assert "hasFile" in create
    assert "jsonPath" in create
    assert "openRemembered" in create
    assert "setIapFile" in create
    assert 'emit("next")' not in create
    assert "iap.skip_to_edit" in create
    assert "iap.file_opened" in create
    assert "iap.draft_applied" in create
    assert "<t-tabs" in create
    assert "t-tab-panel" in create
    assert 'v-model="source"' in create
    tab_values = [
        m.group(1)
        for m in re.finditer(r'<t-tab-panel[^>]*\bvalue="([^"]+)"', create)
    ]
    assert tab_values == ["json", "table", "asc", "blank", "agent"]
    assert "iap.tab.json" in create
    assert "iap.tab.table" in create
    assert "iap.tab.asc" in create
    assert "iap.tab.blank" in create
    assert "iap.tab.agent" in create
    assert "ExampleHelp" in create
    assert 'kind="iap"' in create
    assert "iap.json_path_help" in create
    assert "iap.file" in create
    assert 'destroy-on-hide="false"' in create
    assert "accordion" not in create.lower()
    assert "source-card" not in create
    assert "source-unit" not in create
    assert "toggleSource" not in create
    assert "ChevronDownIcon" not in create
    assert "onMounted" not in create
    assert '@click="pullAsc"' in create
    edit = (root / "views/iap/EditStep.vue").read_text(encoding="utf-8")
    assert "IapEditorDialog" in edit
    assert "list-row" in edit
    assert "edit-layout" not in edit
    assert "tree-item" not in edit
    assert "t-popconfirm" in edit
    assert "<t-dropdown" in edit
    assert "iap.add" in edit
    assert "iap.need_group_first" in edit
    assert "iap.pick_group" in edit
    assert "AddIcon" in edit
    assert "ensureCompare" in edit
    assert "ensureCompare({ force" in edit or 'ensureCompare({ force' in edit
    assert "/api/iap/plan" in (root / "composables/useIapWorkflow.ts").read_text(encoding="utf-8")
    assert "/api/iap/compare" in (root / "composables/useIapWorkflow.ts").read_text(encoding="utf-8")
    assert "review-screenshots/scan" in (root / "composables/useIapWorkflow.ts").read_text(encoding="utf-8")
    assert "PageLoading" in edit
    assert "compare-progress" in edit
    assert "iap.compare.phase_local" in edit
    assert "iap.compare.elapsed" in edit
    assert "iap.compare.button" in edit
    assert "iap.compare.refresh" in edit
    assert "opt.disabled" in edit
    assert "iap.filter.need_compare" in edit
    assert "iap.filter.checking" in edit
    assert "refreshStore" in edit
    assert "void workflow.ensureCompare();" not in edit
    mounted = re.search(r"onMounted\(async \(\) => \{.*?\}\);", edit, re.S)
    assert mounted, "EditStep onMounted missing"
    assert "ensureCompare" not in mounted.group(0)
    assert "loadPlan" not in mounted.group(0)
    assert "iap.filter.local" in edit
    assert "iap.filter.empty_local" in edit
    assert "iap.filter.empty_changed" in edit
    assert "iap.filter.empty_shot" in edit
    assert "filter-count" in edit
    assert "isMissingShot" in edit
    assert "missingScreenshot" in edit
    assert "missingOnStore" in edit
    assert '@click="addItem(\'CONSUMABLE\')"' not in edit
    assert '@click="addItem(\'NON_CONSUMABLE\')"' not in edit
    assert '@click="addGroup"' not in edit
    assert '@click="addSubscription()"' not in edit
    assert "if (!snap.subscriptionGroups.length)" not in edit
    dialog = (root / "views/iap/IapEditorDialog.vue").read_text(encoding="utf-8")
    assert "/api/iap/translate" in dialog
    assert "<t-dialog" in dialog
    assert "iap.auto_translate" in dialog
    assert "iap.dialog_ok" in dialog
    assert "common.cancel" in dialog
    assert "iap.section_basics" in dialog
    assert 'class="mod"' in dialog
    assert 'class="nested"' in dialog
    assert "loc-code" in dialog
    assert "useLocaleCatalog" in dialog
    assert "LocalePicker" in dialog
    assert "metadata.locales_btn" in dialog
    assert "metadata.locales_title" in dialog
    assert "disabled: used.has(row.code)" in dialog
    assert "{ label: c, value: c }" not in dialog
    catalog = (root / "composables/useLocaleCatalog.ts").read_text(encoding="utf-8")
    assert "/api/metadata/locales" in catalog
    assert "name_zh" in catalog
    assert "name_en" in catalog
    upload = (root / "views/iap/UploadStep.vue").read_text(encoding="utf-8")
    assert "ensureCompare" in upload
    assert "ensurePlan" not in upload
    assert "refreshStore" in upload
    assert "void workflow.ensurePlan();" not in upload
    assert "void loadPlan();" not in upload
    assert "onMounted" not in upload
    assert "TaskRunBar" in upload
    assert '@click="scan"' in upload
    assert "void scan();" not in upload
    assert '<t-space class="check-opts" size="small" break-line>' in upload
    assert '<t-checkbox v-model="workflow.dryRun.value">{{ t("iap.dry_run") }}</t-checkbox>' in upload
    assert '<t-checkbox v-model="workflow.updateExisting.value">{{ t("iap.update_existing") }}</t-checkbox>' in upload
    assert '<t-checkbox v-model="workflow.verbose.value">{{ t("build.verbose") }}</t-checkbox>' in upload
    assert "t-checkbox-group" not in upload
    flags_block = upload.split('class="card">', 1)[1].split('class="card">', 1)[0]
    assert 'class="field-row"' not in flags_block
    assert "padding-left: 0" in upload
    workflow = (root / "composables/useIapWorkflow.ts").read_text(encoding="utf-8")
    assert "dirty" in workflow
    assert "storeDraft" in workflow
    assert "iapDraftKey" in workflow
    assert "compared" in workflow
    assert "void ensureCompare({ force: true });" not in workflow
    assert "void ensureCompare({ force: true })" not in workflow
    assert "write: false" in create
    assert "write: false" in edit
    assert "storeDraft: true" in create
    assert "storeDraft: true" in edit
    assert "iap.store_draft_banner" in (root / "views/IapView.vue").read_text(encoding="utf-8")
    assert "iap.save_to_json" in (root / "views/IapView.vue").read_text(encoding="utf-8")
    assert "iap.discard_draft" in (root / "views/IapView.vue").read_text(encoding="utf-8")
    assert ':disabled="workflow.emptyProfile.value" @click="startUpload"' not in iap
    assert '@click="startUpload"' in iap
    assert "MessagePlugin" in iap
    assert "nav.select_app" in iap
    assert "iap.need_file" in iap
    assert "fieldErrors" in (root / "composables/useIapWorkflow.ts").read_text(encoding="utf-8")
    assert ':status="workflow.fieldErrors.value.file ? \'error\' : undefined"' in create
    assert ':disabled="workflow.emptyProfile.value || !targets.length"' not in upload
    assert "iap.pick_path" in upload
    assert "iap.no_missing" in upload
    assert "MessagePlugin" in upload
    assert "pathErrors" in upload
    assert ":status=\"pathErrors[item.id] ? 'error' : undefined\"" in upload
    assert "write: false" in dialog
    memory = (root / "composables/useFormMemory.ts").read_text(encoding="utf-8")
    assert 'IAP_DRAFT_KEY_PREFIX = "asc_iap_draft_"' in memory
    assert "sessionStorage" in memory
    rail = (root / "composables/useRightRail.ts").read_text(encoding="utf-8")
    assert "seedPrompt" in rail
