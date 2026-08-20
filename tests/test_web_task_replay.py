from __future__ import annotations

from asc.web.tasks import TaskStore


def _noop_start(*_args, **kwargs):
    return kwargs.get("task_id") or "x"


def _patch_starters(monkeypatch, store: TaskStore) -> None:
    monkeypatch.setattr("asc.web.routes_api._task_store", store)
    monkeypatch.setattr("asc.web.routes_iap._task_store", store)
    monkeypatch.setattr("asc.web.routes_listing.task_store", store)
    monkeypatch.setattr("asc.web.routes_api.start_background_task", _noop_start)
    monkeypatch.setattr("asc.web.routes_iap.start_background_task", _noop_start)
    monkeypatch.setattr("asc.web.routes_listing.start_background_task", _noop_start)
    monkeypatch.setattr("asc.web.task_runner.start_background_task", _noop_start)


def test_metadata_starter_writes_replay(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    try:
        _patch_starters(monkeypatch, store)
        from asc.web.routes_api import _start_metadata_task

        task_id = _start_metadata_task(
            profile="myapp",
            csv_path="data/appstore_info.csv",
            screenshots_dir="data/screenshots",
            include_metadata=True,
            include_screenshots=False,
            dry_run=True,
            verbose=False,
            locales=["zh-Hans"],
            fields_by_locale=None,
            screenshot_scopes=None,
        )
        replay = store.get_replay(task_id)
        assert replay["kind"] == "metadata"
        assert replay["params"]["csv_path"] == "data/appstore_info.csv"
        assert replay["params"]["include_screenshots"] is False
        assert "issuer_id" not in replay["params"]
    finally:
        store.close()


def test_build_starter_omits_certificate_fields(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    try:
        _patch_starters(monkeypatch, store)
        from asc.web.routes_api import _start_build_task

        task_id = _start_build_task(
            profile="myapp",
            mode="build",
            project="App.xcodeproj",
            scheme="App",
            destination="testflight",
            ipa_path="",
            verbose=False,
            signing="manual",
            certificate="iPhone Distribution: Secret",
            provisioning_profile="secret-profile",
            dry_run=True,
        )
        params = store.get_replay(task_id)["params"]
        assert params["signing"] == "manual"
        assert params["project"] == "App.xcodeproj"
        assert "certificate" not in params
        assert "provisioning_profile" not in params
    finally:
        store.close()


def test_remaining_starters_write_kind_specific_replay(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "tasks.db")
    try:
        _patch_starters(monkeypatch, store)
        from asc.commands.iap_review_screenshots import ReviewScreenshotUploadItem
        from asc.web.routes_api import (
            _start_iap_compare_task,
            _start_iap_review_screenshots_task,
            _start_iap_task,
            _start_urls_task,
            _start_update_task,
            _start_whats_new_task,
            _start_whats_new_translate_task,
        )
        from asc.web.routes_listing import _start_listing_pull_screenshots_task

        iap_id = _start_iap_task("myapp", "data/iap_packages.json", True, False, False)
        assert store.get_replay(iap_id)["params"]["iap_file"] == "data/iap_packages.json"
        compare_id = _start_iap_compare_task("myapp", "data/iap_packages.json", True)
        assert store.get_replay(compare_id)["kind"] == "iap-compare"
        assert store.get_replay(compare_id)["params"]["iap_file"] == "data/iap_packages.json"
        assert store.get_replay(compare_id)["params"]["update_existing"] is True
        url_id = _start_urls_task(
            profile="myapp",
            field="supportUrl",
            url="https://example.com/s",
            locales=["en-US"],
            dry_run=True,
            verbose=False,
        )
        assert store.get_replay(url_id)["params"]["field"] == "supportUrl"
        upd_id = _start_update_task(version="0.1.26", branch=None, verbose=False)
        assert store.get_replay(upd_id)["params"]["version"] == "0.1.26"
        wn_id = _start_whats_new_task("myapp", True, text="hello", locales=["en-US"], verbose=False)
        assert store.get_replay(wn_id)["params"]["text"] == "hello"
        assert "source_file" not in store.get_replay(wn_id)["params"]
        tr_id = _start_whats_new_translate_task("myapp", "hello", "en-US", False)
        assert store.get_replay(tr_id)["kind"] == "whats-new-translate"
        pull_id = _start_listing_pull_screenshots_task(
            "myapp",
            "data/screenshots",
            [{"locale": "en-US", "display_type": "APP_IPHONE_67"}],
        )
        assert store.get_replay(pull_id)["params"]["screenshots_dir"] == "data/screenshots"
        review_id = _start_iap_review_screenshots_task(
            "myapp",
            [
                ReviewScreenshotUploadItem(
                    kind="iap",
                    id="sku-1",
                    product_id="coins_100",
                    path="data/iap_review/coins.png",
                )
            ],
            True,
            False,
        )
        review_items = store.get_replay(review_id)["params"]["items"]
        assert review_items == [
            {
                "kind": "iap",
                "id": "sku-1",
                "productId": "coins_100",
                "path": "data/iap_review/coins.png",
            }
        ]
    finally:
        store.close()
