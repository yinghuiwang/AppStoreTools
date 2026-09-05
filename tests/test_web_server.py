# tests/test_web_server.py
from __future__ import annotations
from datetime import datetime
import inspect
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from asc.web.security import mask_identifier, mask_ip
from asc.web.server import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_asgi_factory_create_app_imports():
    """uvicorn loads `asc.web.server:create_app --factory`; this must succeed on 3.9+."""
    from fastapi import FastAPI

    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.routes


def test_fastapi_route_params_avoid_pep604_unions():
    """Python 3.9 + Pydantic cannot evaluate FastAPI `str | None` annotations.

    Scan route signatures for `|` (catches the regression on 3.10+ CI too) and
    evaluate each annotation the same way FastAPI does at route registration.
    """
    from fastapi.dependencies.utils import get_typed_annotation
    from fastapi.routing import APIRoute

    bad: list[str] = []
    eval_errors: list[str] = []
    app = create_app()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        globalns = getattr(route.endpoint, "__globals__", {})
        for name, annotation in route.endpoint.__annotations__.items():
            if name == "return":
                continue
            text = annotation if isinstance(annotation, str) else repr(annotation)
            if "|" in text:
                bad.append(f"{route.path} {name}: {text}")
            try:
                get_typed_annotation(annotation, globalns)
            except TypeError as exc:
                eval_errors.append(f"{route.path} {name}: {exc}")
    assert bad == []
    assert eval_errors == []


@pytest.mark.skipif(
    sys.version_info >= (3, 10),
    reason="PEP 604 unions evaluate natively on Python 3.10+",
)
def test_fastapi_rejects_pep604_union_query_on_python39():
    """Lock the 3.9 failure mode so we do not 'fix' it by bumping Python."""
    from fastapi import FastAPI, Query

    app = FastAPI()
    with pytest.raises(TypeError, match=r"Unable to evaluate type annotation 'str \| None'"):

        @app.get("/bad")
        def _bad(q: str | None = Query(None)):
            return {"q": q}


def test_lifespan_logs_runtime_version_and_commit(caplog, monkeypatch):
    import logging
    from asc.web import server
    from asc.web.tasks import TaskStore

    caplog.set_level(logging.INFO, logger="asc.web")
    monkeypatch.setattr(server, "task_store", TaskStore())
    monkeypatch.setattr(
        "asc.web.server.runtime_identity",
        lambda: ("0.1.25", "b211c90"),
        raising=False,
    )

    with TestClient(create_app()):
        pass

    assert "asc_version=0.1.25" in caplog.text
    assert "commit=b211c90" in caplog.text


def test_runtime_identity_falls_back_when_commit_lookup_fails(monkeypatch):
    from asc.web import server

    monkeypatch.setattr(server, "__version__", "0.1.25", raising=False)
    monkeypatch.setattr(
        server,
        "_installed_commit_short",
        lambda: (_ for _ in ()).throw(RuntimeError("git unavailable")),
        raising=False,
    )

    assert server.runtime_identity() == ("0.1.25", "unknown")


def test_lifespan_resolves_runtime_identity_off_event_loop(monkeypatch):
    import asyncio

    from asc.web import server
    from asc.web.tasks import TaskStore

    calls = []
    monkeypatch.setattr(server, "task_store", TaskStore())

    async def fake_to_thread(function):
        calls.append(function)
        return ("0.1.25", "b211c90")

    monkeypatch.setattr(server.asyncio, "to_thread", fake_to_thread)

    async def run_lifespan():
        async with server._lifespan(None):
            pass

    asyncio.run(run_lifespan())
    assert calls == [server.runtime_identity]


@pytest.fixture(autouse=True)
def isolated_web_task_guard(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr(
        "asc.web.routes_api.enforce_config_guard",
        MagicMock(),
    )
    monkeypatch.setattr(
        "asc.web.routes_iap.enforce_config_guard",
        MagicMock(),
    )


def test_dashboard_api_filters_tasks_and_returns_savings(client, monkeypatch):
    from asc.web import routes_api

    created_at = datetime.now().isoformat()
    tasks = [
        {
            "id": "matching-task",
            "kind": "metadata",
            "profile": "myapp",
            "status": "done",
            "created_at": created_at,
            "duration_seconds": 60,
        },
        {
            "id": "other-profile",
            "kind": "metadata",
            "profile": "another-app",
            "status": "done",
            "created_at": created_at,
            "duration_seconds": 60,
        },
    ]
    monkeypatch.setattr(routes_api._task_store, "list_recent_states", lambda limit: tasks)

    resp = client.get(
        "/api/dashboard/summary",
        params={"range": "7d", "profile": "myapp", "kind": "metadata", "status": "done"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert [task["id"] for task in data["tasks"]] == ["matching-task"]
    assert data["metrics"]["saved_seconds"] == 29 * 60
    assert data["range_days"] == 7


def test_dashboard_api_defaults_to_profile_cookie_and_allows_explicit_empty(client, monkeypatch):
    from asc.web import routes_api

    created_at = datetime.now().isoformat()
    tasks = [
        {"id": "a", "kind": "metadata", "profile": "cookie-app", "status": "done", "created_at": created_at},
        {"id": "b", "kind": "metadata", "profile": "other", "status": "done", "created_at": created_at},
    ]
    monkeypatch.setattr(routes_api._task_store, "list_recent_states", lambda limit: tasks)
    client.cookies.set("asc_profile", "cookie-app")

    assert [task["id"] for task in client.get("/api/dashboard/summary").json()["tasks"]] == ["a"]
    assert {task["id"] for task in client.get("/api/dashboard/summary?profile=").json()["tasks"]} == {"a", "b"}


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("range", "14d"),
        ("status", "unknown"),
        ("kind", "unknown"),
    ],
)
def test_dashboard_api_rejects_invalid_filters(client, name, value):
    resp = client.get("/api/dashboard/summary", params={name: value})

    assert resp.status_code == 400
    assert name in resp.json()["detail"]


def test_blocking_web_probes_run_in_threadpool():
    from asc.web import routes_api

    assert not inspect.iscoroutinefunction(routes_api.dashboard_summary)
    assert not inspect.iscoroutinefunction(routes_api.build_schemes)
    assert not inspect.iscoroutinefunction(routes_api.build_options)
    assert not inspect.iscoroutinefunction(routes_api.whats_new_check)
    assert not inspect.iscoroutinefunction(routes_api.metadata_check)
    assert not inspect.iscoroutinefunction(routes_api.urls_check)
    assert not inspect.iscoroutinefunction(routes_api.update_check)
    assert not inspect.iscoroutinefunction(routes_api.update_versions)
    assert not inspect.iscoroutinefunction(routes_api.update_branches)
    assert not inspect.iscoroutinefunction(routes_api.guard_status)
    # Task creation waits for a durable SQLite write. Entry points that do not
    # await a request body must use FastAPI's sync threadpool.
    assert not inspect.iscoroutinefunction(routes_api.metadata_run)
    assert not inspect.iscoroutinefunction(routes_api.build_run)
    assert not inspect.iscoroutinefunction(routes_api.iap_run)
    assert not inspect.iscoroutinefunction(routes_api.iap_check)
    assert not inspect.iscoroutinefunction(routes_api.urls_set)
    assert not inspect.iscoroutinefunction(routes_api.update_run)
    assert not inspect.iscoroutinefunction(routes_api.browse)


def test_spa_fallback_is_sync():
    app = create_app()
    spa = next(
        route
        for route in app.router.routes
        if getattr(route, "path", "") == "/{full_path:path}"
    )
    assert not inspect.iscoroutinefunction(spa.endpoint)


def test_iap_review_upload_offloads_task_start_to_thread():
    from asc.web import routes_api

    src = inspect.getsource(routes_api.iap_review_screenshots_upload)
    assert "to_thread" in src
    assert "_start_iap_review_screenshots_task" in src


def test_async_task_entrypoints_offload_task_creation_to_thread():
    """Routes that await request parsing must still keep TaskStore writes off-loop."""
    from asc.web import routes_api

    for endpoint, starter in (
        (routes_api.whats_new_run, "_start_whats_new_task"),
        (routes_api.whats_new_translate, "_start_whats_new_translate_task"),
    ):
        src = inspect.getsource(endpoint)
        assert "to_thread" in src
        assert starter in src


def test_profile_guard_and_webhook_routes_offload_to_thread():
    from asc.web import routes_api

    create_src = inspect.getsource(routes_api.create_profile)
    update_src = inspect.getsource(routes_api.update_profile)
    assert "to_thread" in create_src
    assert "_enforce_web_profile_guard" in create_src
    assert "to_thread" in update_src
    assert "_enforce_web_profile_guard" in update_src


def test_update_check_includes_current_commit(client):
    from unittest.mock import patch

    from asc.web.i18n import COOKIE_NAME

    with patch("asc.commands.update_cmd._current_version", return_value="0.1.17"), \
            patch("asc.commands.update_cmd._latest_version_from_github", return_value="0.1.18"), \
            patch("asc.commands.update_cmd._resolve_git_ref_commit", return_value="abcdef1234567890"), \
            patch("asc.commands.update_cmd._is_editable", return_value=False), \
            patch("asc.cli._installed_commit_short", return_value="15e4b3a"):
        client.cookies.set(COOKIE_NAME, "en")
        resp = client.get("/api/update/check")

    assert resp.status_code == 200
    data = resp.json()
    assert data["detail"]["current"] == "0.1.17"
    assert data["detail"]["current_commit"] == "15e4b3a"
    assert data["detail"]["latest"] == "0.1.18"
    assert data["detail"]["latest_commit"] == "abcdef1"
    assert data["detail"]["is_editable"] is False
    assert "commit 15e4b3a" in data["message"]
    assert "latest: 0.1.18 (commit abcdef1)" in data["message"]


def test_update_branches_returns_options(client):
    from unittest.mock import patch

    with patch("asc.commands.update_cmd._branches_from_github", return_value=["develop", "main"]):
        resp = client.get("/api/update/branches")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["branches"] == ["develop", "main"]


def test_update_versions_returns_options(client):
    from unittest.mock import patch

    with patch("asc.commands.update_cmd._all_versions_from_github", return_value=["0.1.18", "0.1.17"]):
        resp = client.get("/api/update/versions")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["versions"] == ["0.1.18", "0.1.17"]


def test_update_post_restart_finalizes_pending_install(tmp_path, monkeypatch, client):
    from asc.web import daemon, routes_api
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    monkeypatch.setattr(daemon, "_STATE_DIR", tmp_path)

    task_id = store.create("update", profile="system")
    store.set_status(task_id, TaskStatus.DONE)
    store.set_result(
        task_id,
        {
            "success": True,
            "installed": False,
            "pending_install": True,
            "restarting": True,
        },
    )
    daemon.write_update_restart_marker(
        task_id, installed=True, pending_install=False
    )

    resp = client.get("/api/update/post-restart")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["result"]["installed"] is True
    assert data["result"]["pending_install"] is False
    assert data["result"]["restarting"] is False
    assert data["result"]["restarted"] is True


def test_update_post_restart_marks_install_error(tmp_path, monkeypatch, client):
    from asc.web import daemon, routes_api
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    monkeypatch.setattr(daemon, "_STATE_DIR", tmp_path)

    task_id = store.create("update", profile="system")
    store.set_status(task_id, TaskStatus.DONE)
    store.set_result(
        task_id,
        {"success": True, "pending_install": True, "restarting": True},
    )
    daemon.write_update_restart_marker(
        task_id,
        installed=False,
        pending_install=True,
        install_error="CalledProcessError: pip failed",
    )

    resp = client.get("/api/update/post-restart")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "error"
    assert data["result"]["success"] is False
    assert "pip failed" in data["result"]["error"]


def test_update_post_restart_finalizes_done_task(tmp_path, monkeypatch, client):
    from asc.web import daemon, routes_api
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    monkeypatch.setattr(daemon, "_STATE_DIR", tmp_path)

    task_id = store.create("update", profile="system")
    store.set_status(task_id, TaskStatus.DONE)
    store.set_result(task_id, {"success": True, "installed": True, "restarting": True})
    daemon.write_update_restart_marker(task_id, installed=True)

    resp = client.get("/api/update/post-restart")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert data["pending"] is True
    assert data["task_id"] == task_id
    assert data["status"] == "done"
    assert data["boot_id"]
    assert data["result"]["restarting"] is False
    assert data["result"]["restarted"] is True
    assert data["pid"]
    assert data["marker"]["old_pid"]

    task = store.get(task_id)
    assert task["status"] == TaskStatus.DONE
    assert task["result"]["restarting"] is False

    ack = client.post("/api/update/post-restart/ack")
    assert ack.status_code == 200
    assert ack.json()["cleared"] is True
    assert daemon.read_update_restart_marker() is None


def test_update_post_restart_recovers_running_success(tmp_path, monkeypatch, client):
    from asc.web import daemon, routes_api
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(daemon, "_STATE_DIR", tmp_path)

    task_id = store.create("update", profile="system")
    store.set_status(task_id, TaskStatus.RUNNING)
    store.set_result(task_id, {"success": True, "installed": True, "restarting": True})
    daemon.write_update_restart_marker(task_id)

    # Simulate a brand-new process: reload store with recover, then serve it.
    recovered = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", recovered)

    resp = client.get("/api/update/post-restart")
    data = resp.json()
    assert data["pending"] is True
    assert data["status"] == "done"
    assert recovered.get(task_id)["status"] == TaskStatus.DONE


def test_filebrowser_returns_json(client, tmp_path):
    resp = client.get(f"/api/browse?path={tmp_path}&mode=dir")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["mode"] == "dir"
    assert body["current_path"] == str(tmp_path.resolve())
    assert isinstance(body["entries"], list)


def test_filebrowser_lists_files(client, tmp_path):
    (tmp_path / "test.csv").write_text("a,b")
    resp = client.get(f"/api/browse?path={tmp_path}&mode=file&ext=.csv")
    names = [e["name"] for e in resp.json()["entries"]]
    assert "test.csv" in names


def test_filebrowser_accepts_comma_separated_extensions_case_insensitive(client, tmp_path):
    (tmp_path / "image.jpg").write_bytes(b"jpg")
    (tmp_path / "image.jpeg").write_bytes(b"jpeg")
    (tmp_path / "image.PNG").write_bytes(b"png")
    (tmp_path / "notes.txt").write_text("text")
    resp = client.get(f"/api/browse?path={tmp_path}&mode=file&ext=.png,.jpg,.jpeg")
    names = [e["name"] for e in resp.json()["entries"]]
    assert "image.jpg" in names
    assert "image.jpeg" in names
    assert "image.PNG" in names
    assert "notes.txt" not in names


def test_filebrowser_lists_directories_in_file_mode(client, tmp_path):
    (tmp_path / "nested").mkdir()
    resp = client.get(f"/api/browse?path={tmp_path}&mode=file&ext=.csv")
    entries = {e["name"]: e for e in resp.json()["entries"]}
    assert entries["nested"]["is_dir"] is True


def test_filebrowser_rejects_outside_home(client):
    resp = client.get("/api/browse?path=/etc&mode=dir")
    assert resp.status_code == 403
    assert resp.json() == {"ok": False, "error": "Forbidden"}


def test_metadata_check_api(client):
    """POST /api/metadata/check 返回 JSON 验证结果"""
    from unittest.mock import patch
    with patch("asc.web.routes_api._run_metadata_check") as mock_check:
        mock_check.return_value = {"ok": True, "level": "success", "message": "环境正常", "detail": {}}
        resp = client.post("/api/metadata/check", cookies={"asc_profile": "myapp"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["level"] == "success"

def test_metadata_run_api_starts_task(client):
    """POST /api/metadata/run 创建任务并返回 task_id"""
    from unittest.mock import patch
    with patch("asc.web.routes_api._start_metadata_task") as mock_start:
        mock_start.return_value = "fake-task-id"
        resp = client.post("/api/metadata/run", cookies={"asc_profile": "myapp"}, data={
            "csv_path": "data/appstore_info.csv",
            "screenshots_dir": "data/screenshots",
            "include_metadata": "on",
            "dry_run": "",
        })
        assert resp.status_code == 200
        assert "task_id" in resp.json()


def test_metadata_task_stops_when_guard_rejects(monkeypatch):
    import time
    from unittest.mock import MagicMock
    from asc.guard import GuardViolationError
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore()
    monkeypatch.setattr(routes_api, "_task_store", store)
    enforce_guard = MagicMock(side_effect=GuardViolationError("machine mismatch"))
    monkeypatch.setattr(routes_api, "enforce_config_guard", enforce_guard)

    task_id = routes_api._start_metadata_task(
        profile="myapp",
        csv_path="unused.csv",
        screenshots_dir="unused",
        include_metadata=True,
        include_screenshots=False,
        dry_run=False,
    )
    deadline = time.time() + 2
    while store.get(task_id)["status"] not in {TaskStatus.ERROR, TaskStatus.DONE} and time.time() < deadline:
        time.sleep(0.01)

    task = store.get(task_id)
    assert task["status"] == TaskStatus.ERROR
    assert task["result"]["error"] == "machine mismatch"
    assert enforce_guard.call_args.kwargs == {"interactive": False}


def test_build_run_api_starts_task(client):
    from unittest.mock import patch
    with patch("asc.web.routes_api._start_build_task") as mock_start:
        mock_start.return_value = "fake-build-task-id"
        resp = client.post("/api/build/run", cookies={"asc_profile": "myapp"}, data={
            "mode": "full",
            "project": "/tmp/MyApp.xcworkspace",
            "destination": "testflight",
            "verbose": "",
        })
        assert resp.status_code == 200
        assert "task_id" in resp.json()


def test_build_run_api_passes_interactive_release_options(client):
    with patch("asc.web.routes_api._start_build_task") as mock_start:
        mock_start.return_value = "fake-build-task-id"
        resp = client.post("/api/build/run", cookies={"asc_profile": "myapp"}, data={
            "mode": "full",
            "project": "MyApp.xcworkspace",
            "scheme": "MyApp",
            "destination": "testflight",
            "signing": "manual",
            "certificate": "Apple Distribution: ACME",
            "provisioning_profile": "/tmp/acme.mobileprovision",
            "reuse_archive": "reuse",
            "dry_run": "on",
            "verbose": "on",
        })
        assert resp.status_code == 200
        mock_start.assert_called_once()
        kwargs = mock_start.call_args.kwargs
        assert kwargs["scheme"] == "MyApp"
        assert kwargs["signing"] == "manual"
        assert kwargs["certificate"] == "Apple Distribution: ACME"
        assert kwargs["provisioning_profile"] == "/tmp/acme.mobileprovision"
        assert kwargs["reuse_archive"] == "reuse"
        assert kwargs["dry_run"] is True


def test_build_run_rejects_manual_signing_without_certificate(client):
    from unittest.mock import patch
    from asc.web.i18n import t

    with patch("asc.web.routes_api._start_build_task") as mock_start:
        resp = client.post(
            "/api/build/run",
            cookies={"asc_profile": "myapp", "asc_lang": "zh"},
            data={
                "mode": "full",
                "project": "/tmp/MyApp.xcworkspace",
                "signing": "manual",
                "certificate": "",
                "provisioning_profile": "/tmp/acme.mobileprovision",
            },
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == t("build.need_certificate", lang="zh")
    mock_start.assert_not_called()


def test_build_run_rejects_manual_signing_without_profile(client):
    from unittest.mock import patch
    from asc.web.i18n import t

    with patch("asc.web.routes_api._start_build_task") as mock_start:
        resp = client.post(
            "/api/build/run",
            cookies={"asc_profile": "myapp", "asc_lang": "en"},
            data={
                "mode": "full",
                "project": "/tmp/MyApp.xcworkspace",
                "signing": "manual",
                "certificate": "Apple Distribution: ACME",
                "provisioning_profile": "  ",
            },
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == t("build.need_profile", lang="en")
    mock_start.assert_not_called()


def test_build_run_allows_auto_signing_without_certificate(client):
    from unittest.mock import patch

    with patch("asc.web.routes_api._start_build_task", return_value="task-1") as mock_start:
        resp = client.post(
            "/api/build/run",
            cookies={"asc_profile": "myapp"},
            data={
                "mode": "full",
                "project": "/tmp/MyApp.xcworkspace",
                "signing": "auto",
                "certificate": "",
                "provisioning_profile": "",
            },
        )
    assert resp.status_code == 200
    mock_start.assert_called_once()


def test_build_run_rejects_cwd_sentinel_without_project(client):
    from unittest.mock import MagicMock, patch

    mock_config = MagicMock()
    mock_config.build_project = None
    with patch("asc.web.routes_api.Config", return_value=mock_config):
        resp = client.post(
            "/api/build/run",
            cookies={"asc_profile": "myapp"},
            data={"mode": "full", "project": ".", "destination": "testflight"},
        )
    assert resp.status_code == 400
    assert resp.json()["error"]


def test_build_run_parses_false_form_values_as_false(client):
    from unittest.mock import patch

    with patch("asc.web.routes_api._start_build_task", return_value="task-1") as mock_start:
        resp = client.post(
            "/api/build/run",
            cookies={"asc_profile": "myapp"},
            data={
                "verbose": "false",
                "dry_run": "false",
                "project": "/tmp/MyApp.xcworkspace",
            },
        )

    assert resp.status_code == 200
    assert mock_start.call_args.kwargs["verbose"] is False
    assert mock_start.call_args.kwargs["dry_run"] is False


def test_iap_review_screenshots_scan_returns_targets_with_default_path(client, tmp_path):
    from unittest.mock import MagicMock
    from asc.commands.iap_review_screenshots import ReviewScreenshotTarget

    iap_file = tmp_path / "iap_packages.json"
    screenshot_path = tmp_path / "review.png"
    iap_file.write_text(
        '{"items":[{"productId":"coins_100","review":{"screenshot":"review.png"}}]}',
        encoding="utf-8",
    )

    scan_result = MagicMock()
    scan_result.targets = [
        ReviewScreenshotTarget(
            kind="iap",
            id="iap-1",
            product_id="coins_100",
            name="100 Coins",
        )
    ]
    scan_result.errors = []

    with patch("asc.web.routes_iap.Config") as mock_config_cls, \
         patch("asc.web.routes_iap.make_api_from_config", return_value=(MagicMock(), "app-1")), \
         patch("asc.web.routes_iap.scan_missing_review_screenshots", return_value=scan_result):
        mock_config_cls.return_value.iap_path = ""
        resp = client.post(
            "/api/iap/review-screenshots/scan",
            cookies={"asc_profile": "myapp"},
            json={"iapFile": str(iap_file)},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 1
    assert data["errors"] == []
    assert data["targets"][0]["productId"] == "coins_100"
    assert data["targets"][0]["defaultPath"] == str(screenshot_path)


def test_iap_review_screenshots_scan_rejects_malformed_json(client):
    with patch("asc.web.routes_iap._scan_iap_review_screenshot_targets") as mock_scan, \
         patch("asc.web.routes_iap.scan_missing_review_screenshots") as mock_scan_helper:
        resp = client.post(
            "/api/iap/review-screenshots/scan",
            cookies={"asc_profile": "myapp"},
            content=b"{",
            headers={"content-type": "application/json"},
        )

    assert resp.status_code == 400
    mock_scan.assert_not_called()
    mock_scan_helper.assert_not_called()


def test_iap_review_screenshots_scan_rejects_non_string_iap_file(client):
    with patch("asc.web.routes_iap._scan_iap_review_screenshot_targets") as mock_scan:
        resp = client.post(
            "/api/iap/review-screenshots/scan",
            cookies={"asc_profile": "myapp"},
            json={"iapFile": 123},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "iapFile must be a string"
    mock_scan.assert_not_called()


def test_iap_review_screenshots_upload_starts_task_with_items(client):
    with patch("asc.web.routes_iap._start_iap_review_screenshots_task") as mock_start:
        mock_start.return_value = "fake-review-task-id"
        resp = client.post(
            "/api/iap/review-screenshots/upload",
            cookies={"asc_profile": "myapp"},
            json={
                "dryRun": True,
                "items": [
                    {
                        "kind": "iap",
                        "id": "iap-1",
                        "productId": "coins_100",
                        "path": "/tmp/review.png",
                    }
                ],
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"task_id": "fake-review-task-id"}
    mock_start.assert_called_once()
    kwargs = mock_start.call_args.kwargs
    assert kwargs["profile"] == "myapp"
    assert kwargs["dry_run"] is True
    assert len(kwargs["items"]) == 1
    assert kwargs["items"][0].product_id == "coins_100"
    assert kwargs["items"][0].path == "/tmp/review.png"


def test_iap_review_screenshots_upload_accepts_false_dry_run(client):
    with patch("asc.web.routes_iap._start_iap_review_screenshots_task") as mock_start:
        mock_start.return_value = "fake-review-task-id"
        resp = client.post(
            "/api/iap/review-screenshots/upload",
            cookies={"asc_profile": "myapp"},
            json={
                "dryRun": False,
                "items": [
                    {
                        "kind": "subscription",
                        "id": "sub-1",
                        "productId": "pro_monthly",
                        "path": "/tmp/review.png",
                    }
                ],
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"task_id": "fake-review-task-id"}
    assert mock_start.call_args.kwargs["dry_run"] is False


def test_iap_review_screenshots_upload_rejects_non_boolean_dry_run(client):
    with patch("asc.web.routes_iap._start_iap_review_screenshots_task") as mock_start:
        resp = client.post(
            "/api/iap/review-screenshots/upload",
            cookies={"asc_profile": "myapp"},
            json={
                "dryRun": "false",
                "items": [
                    {
                        "kind": "iap",
                        "id": "iap-1",
                        "productId": "coins_100",
                        "path": "/tmp/review.png",
                    }
                ],
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "dryRun must be a boolean"
    mock_start.assert_not_called()


def test_iap_review_screenshots_upload_rejects_mixed_invalid_items(client):
    with patch("asc.web.routes_iap._start_iap_review_screenshots_task") as mock_start:
        resp = client.post(
            "/api/iap/review-screenshots/upload",
            cookies={"asc_profile": "myapp"},
            json={
                "items": [
                    {
                        "kind": "iap",
                        "id": "iap-1",
                        "productId": "coins_100",
                        "path": "/tmp/review.png",
                    },
                    {
                        "kind": "subscription",
                        "id": "sub-1",
                        "path": "/tmp/sub-review.png",
                    },
                ],
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid item"
    mock_start.assert_not_called()


def test_iap_review_screenshots_upload_rejects_unsupported_kind(client):
    with patch("asc.web.routes_iap._start_iap_review_screenshots_task") as mock_start:
        resp = client.post(
            "/api/iap/review-screenshots/upload",
            cookies={"asc_profile": "myapp"},
            json={
                "items": [
                    {
                        "kind": "consumable",
                        "id": "iap-1",
                        "productId": "coins_100",
                        "path": "/tmp/review.png",
                    }
                ],
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid item"
    mock_start.assert_not_called()


def test_iap_review_screenshots_upload_rejects_empty_items(client):
    resp = client.post(
        "/api/iap/review-screenshots/upload",
        cookies={"asc_profile": "myapp"},
        json={"items": []},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "items required"


def test_iap_review_screenshots_task_rejects_stale_target_without_upload(tmp_path):
    import time
    from unittest.mock import MagicMock
    from asc.commands.iap_review_screenshots import (
        ReviewScreenshotScanResult,
        ReviewScreenshotTarget,
        ReviewScreenshotUploadItem,
    )
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus

    screenshot = tmp_path / "review.png"
    screenshot.write_bytes(b"png")
    submitted = [
        ReviewScreenshotUploadItem(
            kind="iap",
            id="crafted-iap-id",
            product_id="coins_100",
            path=str(screenshot),
        )
    ]
    current_scan = ReviewScreenshotScanResult(
        targets=[
            ReviewScreenshotTarget(
                kind="iap",
                id="current-iap-id",
                product_id="coins_100",
                name="100 Coins",
            )
        ]
    )

    with patch("asc.web.routes_iap.Config"), \
         patch("asc.web.routes_iap.make_api_from_config", return_value=(MagicMock(), "app-1")), \
         patch("asc.web.routes_iap.scan_missing_review_screenshots", return_value=current_scan), \
         patch("asc.web.routes_iap.upload_review_screenshots") as mock_upload:
        task_id = routes_api._start_iap_review_screenshots_task(
            profile="myapp",
            items=submitted,
            dry_run=False,
        )

        task = None
        for _ in range(100):
            task = routes_api._task_store.get(task_id)
            if task and task["status"] in {
                TaskStatus.DONE,
                TaskStatus.ERROR,
                TaskStatus.CANCELED,
            }:
                break
            time.sleep(0.02)

    assert task is not None
    assert task["status"] == TaskStatus.ERROR
    assert task["result"]["success"] is False
    assert task["result"]["uploaded"] == 0
    assert task["result"]["failed"] == 1
    assert "no longer eligible" in task["result"]["failures"][0]["error"]
    assert any("no longer eligible" in line for line in task["logs"])
    mock_upload.assert_not_called()


def test_build_options_api_returns_release_choices(client):
    from datetime import datetime, timezone
    from unittest.mock import MagicMock, patch

    from asc.commands.build_inputs import Certificate, ProfileInfo

    mock_config = MagicMock()
    mock_config.build_project = None
    mock_config.build_scheme = None
    mock_config.build_bundle_id = None
    mock_config.build_certificate = ""
    mock_config.build_profile = ""
    mock_config.build_output = "/tmp/build"

    profile = ProfileInfo(
        path="/tmp/acme.mobileprovision",
        uuid="UUID",
        name="ACME AppStore",
        team_id="TEAM123",
        bundle_id="com.acme.app",
        expiration=datetime(2030, 1, 1, tzinfo=timezone.utc),
        cert_sha1s=["SHA1"],
    )

    with patch("asc.web.routes_api.Config", return_value=mock_config), \
         patch("asc.commands.build_inputs.detect_project", return_value=("MyApp.xcworkspace", "workspace")), \
         patch("asc.commands.build_inputs.list_schemes", return_value=["MyApp", "MyAppTests"]), \
         patch("asc.commands.build_inputs.detect_bundle_id", return_value="com.acme.app"), \
         patch("asc.commands.build_inputs.detect_certificates", return_value=[Certificate(sha1="SHA1", name="Apple Distribution: ACME")]), \
         patch("asc.commands.build_inputs.detect_profiles", return_value=[profile]), \
         patch("asc.commands.build_inputs.detect_versions", return_value=("1.0", "42")), \
         patch("asc.commands.build_inputs.scan_archives", return_value=[]), \
         patch("asc.commands.build_inputs.find_matching_archive", return_value=None):
        resp = client.get(
            "/api/build/options",
            cookies={"asc_profile": "myapp"},
            params={
                "project": "MyApp.xcworkspace",
                "scheme": "MyApp",
                "signing": "manual",
                "certificate": "Apple Distribution: ACME",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["project_selected"] == "MyApp.xcworkspace"
    assert data["schemes"] == ["MyApp", "MyAppTests"]
    assert data["selected_scheme"] == "MyApp"
    assert data["bundle_id"] == "com.acme.app"
    assert data["bundle_id_selected"] == "com.acme.app"
    assert data["certificates"][0]["name"] == "Apple Distribution: ACME"
    assert data["selected_certificate"] == "Apple Distribution: ACME"
    assert data["profiles"][0]["path"] == "/tmp/acme.mobileprovision"
    assert data["selected_profile"] == ""
    assert data["version_info"] == {"marketing_version": "1.0", "build_number": "42"}
    assert data["archive_match"] is None


def _web_decoy_and_real_projects(tmp_path):
    decoy_root = tmp_path / "asc-web-cwd"
    real_root = tmp_path / "UserApp"
    decoy_root.mkdir()
    real_root.mkdir()
    (decoy_root / "Decoy.xcodeproj").mkdir()
    (real_root / "Real.xcodeproj").mkdir()
    (decoy_root / ".asc").mkdir()
    (decoy_root / ".asc" / "config.toml").write_text(
        '[build]\nproject = "."\nbundle_id = "com.decoy.app"\nscheme = "Decoy"\n'
    )
    return decoy_root, real_root


def _fake_xcodebuild_for_decoy_vs_real(cmd, **_kwargs):
    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    argv = list(cmd)
    project = ""
    if "-project" in argv:
        project = argv[argv.index("-project") + 1]
    elif "-workspace" in argv:
        project = argv[argv.index("-workspace") + 1]

    if "Real.xcodeproj" in project:
        bundle_id, scheme = "com.real.app", "RealApp"
    elif "Decoy.xcodeproj" in project:
        bundle_id, scheme = "com.decoy.app", "Decoy"
    else:
        raise AssertionError(f"xcodebuild used unexpected project path: {project!r}")

    if "-list" in argv:
        Result.stdout = f"Information about project:\n    Schemes:\n        {scheme}\n"
    else:
        Result.stdout = (
            f"    PRODUCT_BUNDLE_IDENTIFIER = {bundle_id}\n"
            "    MARKETING_VERSION = 1.0\n"
            "    CURRENT_PROJECT_VERSION = 1\n"
        )
    return Result()


def test_build_options_uses_specified_project_not_process_cwd(
    tmp_path, monkeypatch, client
):
    """Bundle ID must come from the UI Xcode path, not the `asc web` cwd."""
    decoy_root, real_root = _web_decoy_and_real_projects(tmp_path)
    monkeypatch.chdir(decoy_root)
    monkeypatch.setattr(
        "asc.commands.build_inputs.subprocess.run", _fake_xcodebuild_for_decoy_vs_real
    )
    monkeypatch.setattr("asc.commands.build_inputs.scan_archives", lambda *a, **kw: [])

    resp = client.get(
        "/api/build/options",
        params={"project": str(real_root), "scheme": "RealApp"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "Real.xcodeproj" in data["project_selected"]
    assert data["bundle_id"] == "com.real.app"
    assert data["bundle_id_selected"] == "com.real.app"
    assert data["bundle_id"] != "com.decoy.app"


def test_build_options_does_not_scan_web_process_cwd(tmp_path, monkeypatch, client):
    """Omitting project (or sending '.') must not pick up a decoy xcodeproj in cwd."""
    decoy_root, _real_root = _web_decoy_and_real_projects(tmp_path)
    monkeypatch.chdir(decoy_root)
    monkeypatch.setattr(
        "asc.commands.build_inputs.subprocess.run", _fake_xcodebuild_for_decoy_vs_real
    )

    for params in ({}, {"project": "."}):
        resp = client.get("/api/build/options", params=params)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is False
        assert data.get("bundle_id") != "com.decoy.app"
        assert "Decoy.xcodeproj" not in str(data.get("project_selected") or "")


def test_task_stream_done_task(client):
    """已完成任务的 SSE 流应立即发送所有日志并关闭。"""
    from asc.web.tasks import task_store, TaskStatus
    task_id = task_store.create("metadata")
    task_store.append_log(task_id, "line 1")
    task_store.append_log(task_id, "line 2")
    task_store.set_status(task_id, TaskStatus.DONE)

    resp = client.get(f"/api/task/{task_id}/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert "line 1" in body
    assert "line 2" in body
    assert "event: done" in body


def test_task_stream_canceled_task(client):
    from asc.web.tasks import task_store, TaskStatus
    task_id = task_store.create("metadata")
    task_store.append_log(task_id, "cancel requested")
    task_store.set_status(task_id, TaskStatus.CANCELED)

    resp = client.get(f"/api/task/{task_id}/stream")
    assert resp.status_code == 200
    body = resp.text
    assert "cancel requested" in body
    assert "event: canceled" in body


def test_task_stream_not_found(client):
    resp = client.get("/api/task/nonexistent/stream")
    assert resp.status_code == 404


def test_task_stream_uses_one_snapshot_per_poll(client, monkeypatch):
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus

    snapshots = [
        {
            "task": {
                "status": TaskStatus.DONE,
                "progress": {"pct": 100, "msg": "done"},
                "result": {"success": True},
            },
            "logs": [{"seq": 8, "message": "last business line"}],
        }
    ]
    calls = []

    def get_snapshot(task_id, after):
        calls.append((task_id, after))
        return snapshots[0]

    monkeypatch.setattr(routes_api._task_store, "get_stream_snapshot", get_snapshot)
    monkeypatch.setattr(
        routes_api._task_store,
        "get_state",
        lambda task_id: pytest.fail("SSE must not call get_state"),
    )
    monkeypatch.setattr(
        routes_api._task_store,
        "get_logs_after",
        lambda task_id, after: pytest.fail("SSE must not call get_logs_after"),
    )

    response = client.get(
        "/api/task/task-1/stream?after=3",
        headers={"Last-Event-ID": "7"},
    )

    assert response.status_code == 200
    assert calls == [("task-1", 7)]
    assert response.text.index("id: 8") < response.text.index("event: progress")
    assert response.text.index("event: progress") < response.text.index("event: done")


def test_task_stream_invalid_last_event_id_falls_back_to_after(client, monkeypatch):
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus

    calls = []

    def get_snapshot(task_id, after):
        calls.append((task_id, after))
        return {
            "task": {"status": TaskStatus.DONE, "progress": None, "result": None},
            "logs": [{"seq": 5, "message": "resumed"}],
        }

    monkeypatch.setattr(routes_api._task_store, "get_stream_snapshot", get_snapshot)

    response = client.get(
        "/api/task/task-2/stream?after=4",
        headers={"Last-Event-ID": "invalid"},
    )

    assert calls == [("task-2", 4)]
    assert 'id: 5\nevent: log\ndata: {"message": "resumed", "level": "info"}' in response.text
    assert response.text.count('"message": "resumed"') == 1


def test_task_stream_preserves_progress_heartbeat_and_error_event_names(client, monkeypatch):
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus

    snapshots = iter(
        [
            {
                "task": {
                    "status": TaskStatus.RUNNING,
                    "progress": {"pct": 25, "msg": "working"},
                    "result": None,
                },
                "logs": [],
            },
            {
                "task": {
                    "status": TaskStatus.ERROR,
                    "progress": {"pct": 25, "msg": "working"},
                    "result": {"success": False},
                },
                "logs": [],
            },
        ]
    )
    monkeypatch.setattr(
        routes_api._task_store,
        "get_stream_snapshot",
        lambda task_id, after: next(snapshots),
    )
    monkeypatch.setattr(routes_api._asyncio, "sleep", lambda delay: _immediate_async())

    response = client.get("/api/task/task-3/stream")

    assert "event: progress" in response.text
    assert ": heartbeat\n\n" in response.text
    assert "event: error_event\ndata: \n\n" in response.text


def test_task_stream_preserves_timeout_error_event(client, monkeypatch):
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus

    monkeypatch.setattr(
        routes_api._task_store,
        "get_stream_snapshot",
        lambda task_id, after: {
            "task": {"status": TaskStatus.RUNNING, "progress": None, "result": None},
            "logs": [],
        },
    )
    monkeypatch.setattr(routes_api, "SSE_ABSOLUTE_TIMEOUT_SEC", 0)

    response = client.get("/api/task/task-4/stream")

    assert "event: error_event\ndata: timeout\n\n" in response.text


def test_task_stream_reports_task_disappearing_after_stream_starts(client, monkeypatch):
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus

    snapshots = iter(
        [
            {
                "task": {"status": TaskStatus.RUNNING, "progress": None, "result": None},
                "logs": [{"seq": 1, "message": "started"}],
            },
            None,
        ]
    )
    calls = []

    def get_snapshot(task_id, after):
        calls.append((task_id, after))
        return next(snapshots)

    monkeypatch.setattr(routes_api._task_store, "get_stream_snapshot", get_snapshot)
    monkeypatch.setattr(routes_api._asyncio, "sleep", lambda delay: _immediate_async())

    response = client.get("/api/task/vanishing-task/stream")

    assert response.status_code == 200
    assert calls == [("vanishing-task", 0), ("vanishing-task", 1)]
    assert "id: 1\nevent: log\ndata: {\"message\": \"started\", \"level\": \"info\"}\n\n" in response.text
    assert "event: error_event\ndata: task not found\n\n" in response.text


@pytest.mark.parametrize("resume_with", ["after", "Last-Event-ID"])
def test_task_stream_reconnects_without_duplicate_or_missing_logs(client, resume_with):
    from asc.web.tasks import task_store, TaskStatus

    task_id = task_store.create("metadata")
    task_store.append_logs(task_id, ["one", "two"])
    task_store.set_status(task_id, TaskStatus.DONE)

    first = client.get(f"/api/task/{task_id}/stream")
    first_ids = [
        int(line.removeprefix("id: "))
        for line in first.text.splitlines()
        if line.startswith("id: ")
    ]
    last_event_id = first_ids[-1]

    task_store.append_logs(task_id, ["three", "four"])
    if resume_with == "after":
        second = client.get(f"/api/task/{task_id}/stream?after={last_event_id}")
    else:
        second = client.get(
            f"/api/task/{task_id}/stream",
            headers={"Last-Event-ID": str(last_event_id)},
        )
    second_ids = [
        int(line.removeprefix("id: "))
        for line in second.text.splitlines()
        if line.startswith("id: ")
    ]

    assert first.status_code == second.status_code == 200
    assert first_ids == [1, 2]
    assert second_ids == [3, 4]
    assert first_ids + second_ids == [1, 2, 3, 4]
    assert len(set(first_ids + second_ids)) == 4


def test_reconnect_cursor_has_no_gaps_and_terminal_has_result(
    client, tmp_path, monkeypatch
):
    from asc.web import routes_api
    from asc.web.tasks import TaskStore, TaskStatus

    store = TaskStore(tmp_path / "tasks.db")
    monkeypatch.setattr(routes_api, "_task_store", store)
    try:
        task_id = store.create("build")
        store.append_logs(task_id, [f"L{index}" for index in range(1, 101)])
        store.set_result(task_id, {"success": True})
        store.set_status(task_id, TaskStatus.DONE)

        first_ids = []
        with client.stream("GET", f"/api/task/{task_id}/stream?after=0") as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if line.startswith("id: "):
                    first_ids.append(int(line.removeprefix("id: ")))
                    if first_ids[-1] == 40:
                        break

        second = client.get(
            f"/api/task/{task_id}/stream?after=40",
            headers={"Last-Event-ID": "40"},
        )
        second_ids = [
            int(line.removeprefix("id: "))
            for line in second.text.splitlines()
            if line.startswith("id: ")
        ]
        frames = [
            frame
            for frame in second.text.split("\n\n")
            if frame.strip()
        ]
        log_frame_indexes = [
            index
            for index, frame in enumerate(frames)
            if "\nevent: log\n" in f"\n{frame}\n"
        ]
        done_frame_index = next(
            index
            for index, frame in enumerate(frames)
            if "\nevent: done\n" in f"\n{frame}\n"
        )
        terminal_snapshot = store.get_stream_snapshot(task_id, 100)

        assert first_ids + second_ids == list(range(1, 101))
        assert second_ids == list(range(41, 101))
        assert log_frame_indexes
        assert max(log_frame_indexes) < done_frame_index
        assert terminal_snapshot is not None
        assert terminal_snapshot["task"]["status"] == TaskStatus.DONE
        assert terminal_snapshot["task"]["result"] == {"success": True}
    finally:
        store.close()


async def _immediate_async():
    return None


def test_task_cancel_endpoint(client):
    from asc.web.tasks import task_store, TaskStatus
    task_id = task_store.create("build")
    task_store.set_status(task_id, TaskStatus.RUNNING)

    resp = client.post(f"/api/task/{task_id}/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == task_id
    assert data["cancel_requested"] is True
    assert data["status"] == "running"
    task = task_store.get(task_id)
    assert task["cancel_requested"] is True
    assert task["status"] == TaskStatus.RUNNING
    assert any("已请求终止" in line for line in task["logs"])
    assert not any("任务已终止" in line for line in task["logs"])


def test_task_cancel_endpoint_keeps_stuck_task_running_until_worker_exits(client):
    from asc.web.tasks import task_store, TaskStatus

    task_id = task_store.create("urls", profile="test")
    task_store.set_status(task_id, TaskStatus.RUNNING)
    task_store.set_progress(task_id, 40, "更新 marketingUrl")

    resp = client.post(f"/api/task/{task_id}/cancel")

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    task = task_store.get(task_id)
    assert task["status"] == TaskStatus.RUNNING
    assert task["result"] is None
    assert task_store.cancel_event(task_id).is_set()


def test_task_status_endpoint(client):
    """GET /api/task/{task_id}/status 返回任务状态 JSON。"""
    from asc.web.tasks import task_store, TaskStatus
    task_id = task_store.create("build")
    task_store.set_status(task_id, TaskStatus.RUNNING)
    resp = client.get(f"/api/task/{task_id}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert data["task_id"] == task_id


def test_profiles_list_api(client):
    from unittest.mock import patch
    with patch("asc.config.Config.list_apps", return_value=["myapp", "staging"]):
        resp = client.get("/api/profiles")
        assert resp.status_code == 200
        assert "myapp" in resp.json()["profiles"]


def test_profiles_list_api_includes_profile_details(client):
    from unittest.mock import patch, MagicMock

    mock_config = MagicMock()
    mock_config.list_apps.return_value = ["myapp"]
    mock_config.app_name = "myapp"
    mock_config.get_app_profile.return_value = {
        "issuer_id": "issuer-123",
        "key_id": "KEY123",
        "key_file": "/Users/me/.config/asc/keys/AuthKey_KEY123.p8",
        "app_id": "123456789",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
    }

    with patch("asc.config.Config", return_value=mock_config):
        resp = client.get("/api/profiles")

    assert resp.status_code == 200
    data = resp.json()
    assert data["profile_details"]["myapp"] == {
        "issuer_id": "••••••-123",
        "key_id": "••Y123",
        "key_file_name": "AuthKey_KEY123.p8",
        "app_id": "123456789",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
        "machine_access": {"current": False, "elsewhere": False, "enabled": True},
        "bundle_ids": [],
        "already_bound": False,
    }


def test_profile_create_api(client, tmp_path, monkeypatch):
    """POST /api/profiles 创建新 profile"""
    p8_content = b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n"
    from unittest.mock import MagicMock, patch
    monkeypatch.setenv("HOME", str(tmp_path))
    guard = MagicMock()
    guard.is_enabled.return_value = False
    with patch("asc.config.Config.save_app_profile") as mock_save, \
         patch("asc.guard.Guard", return_value=guard):
        resp = client.post("/api/profiles", data={
            "name": "newapp",
            "issuer_id": "abc-123",
            "key_id": "KEYID123",
            "app_id": "1234567890",
        }, files={"key_file": ("AuthKey_KEYID123.p8", p8_content, "application/octet-stream")})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_save.assert_called_once()
        args = mock_save.call_args[0]
        assert args[0] == "newapp"
        assert args[1] == "abc-123"
        csv_arg = mock_save.call_args[0][5] if len(mock_save.call_args[0]) > 5 else ""
        shots_arg = mock_save.call_args[0][6] if len(mock_save.call_args[0]) > 6 else ""
        assert not (csv_arg or "").strip()
        assert not (shots_arg or "").strip()


def test_profile_key_upload_uses_content_addressed_path(client, tmp_path, monkeypatch):
    """Same upload filename with different contents must not overwrite another key."""
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("HOME", str(tmp_path))
    guard = MagicMock()
    guard.is_enabled.return_value = False
    contents = [b"first-key", b"second-key"]
    with patch("asc.config.Config.save_app_profile") as mock_save, \
         patch("asc.guard.Guard", return_value=guard):
        for index, content in enumerate(contents):
            response = client.post(
                "/api/profiles",
                data={"name": f"app{index}", "issuer_id": "issuer", "key_id": "key", "app_id": str(index)},
                files={"key_file": ("AuthKey_SHARED.p8", content, "application/octet-stream")},
            )
            assert response.status_code == 200

    paths = [Path(call.args[3]) for call in mock_save.call_args_list]
    assert paths[0] != paths[1]
    assert paths[0].read_bytes() == contents[0]
    assert paths[1].read_bytes() == contents[1]
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in paths)
    assert paths[0].parent.stat().st_mode & 0o777 == 0o700


def test_profile_create_guard_conflict_has_no_file_side_effects(
    client, tmp_path, monkeypatch
):
    from unittest.mock import MagicMock, patch
    from asc.guard import GuardViolationError

    monkeypatch.setenv("HOME", str(tmp_path))
    guard = MagicMock()
    guard.is_enabled.return_value = True
    guard.check_and_enforce.side_effect = GuardViolationError("issuer conflict")

    with patch("asc.guard.Guard", return_value=guard), \
         patch("asc.config.Config.save_app_profile") as save_profile:
        response = client.post(
            "/api/profiles",
            data={
                "name": "newapp",
                "issuer_id": "ISS-NEW",
                "key_id": "KEY-NEW",
                "app_id": "123",
            },
            files={"key_file": ("AuthKey_NEW.p8", b"key", "application/octet-stream")},
        )

    assert response.status_code == 409
    guard.check_and_enforce.assert_called_once_with(
        app_id="123",
        app_name="newapp",
        key_id="KEY-NEW",
        issuer_id="ISS-NEW",
        interactive=False,
    )
    save_profile.assert_not_called()
    assert not (tmp_path / ".config" / "asc" / "keys" / "AuthKey_NEW.p8").exists()


def test_profile_update_guard_conflict_does_not_overwrite_profile(
    client, tmp_path, monkeypatch
):
    from unittest.mock import MagicMock, patch
    from asc.guard import GuardViolationError

    monkeypatch.setenv("HOME", str(tmp_path))
    profiles_dir = tmp_path / ".config" / "asc" / "profiles"
    profiles_dir.mkdir(parents=True)
    profile_path = profiles_dir / "myapp.toml"
    original = (
        '[credentials]\nissuer_id = "ISS-OLD"\nkey_id = "KEY-OLD"\n'
        'key_file = "/tmp/AuthKey_OLD.p8"\napp_id = "111"\n\n'
        '[defaults]\ncsv = "data/old.csv"\nscreenshots = "data/old"\n'
    )
    profile_path.write_text(original)
    guard = MagicMock()
    guard.is_enabled.return_value = True
    guard.check_and_enforce.side_effect = GuardViolationError("issuer conflict")

    with patch("asc.guard.Guard", return_value=guard):
        response = client.put(
            "/api/profiles/myapp",
            data={
                "name": "myapp",
                "issuer_id": "ISS-NEW",
                "key_id": "KEY-NEW",
                "app_id": "222",
                "csv": "data/new.csv",
                "screenshots": "data/new",
            },
        )

    assert response.status_code == 409
    guard.check_and_enforce.assert_called_once_with(
        app_id="222",
        app_name="myapp",
        key_id="KEY-NEW",
        issuer_id="ISS-NEW",
        interactive=False,
    )
    assert profile_path.read_text() == original


def test_switch_profile_rejects_profile_bound_to_other_machine(client):
    from unittest.mock import MagicMock, patch

    config = MagicMock()
    config.list_apps.return_value = ["other-app"]
    config.get_app_profile.return_value = {"app_id": "app-2", "issuer_id": "ISS-2"}
    access = {
        "matched_profile": "current-app",
        "options": {"other-app": {"enabled": False}},
    }
    with patch("asc.config.Config", return_value=config), \
         patch("asc.guard.Guard.profile_access", return_value=access):
        response = client.get("/api/switch-profile?profile=other-app")

    assert response.status_code == 403


def test_metadata_check_requires_profile(client):
    resp = client.post("/api/metadata/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["level"] == "error"
    assert "profile" in data["message"].lower() or "App" in data["message"]


def test_profile_update_api_allows_rename(client, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    profiles_dir = tmp_path / ".config" / "asc" / "profiles"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "oldapp.toml").write_text(
        '[credentials]\n'
        'issuer_id = "old-issuer"\n'
        'key_id = "OLDKEY"\n'
        'key_file = "/tmp/AuthKey_OLDKEY.p8"\n'
        'app_id = "111"\n\n'
        '[defaults]\n'
        'csv = "data/old.csv"\n'
        'screenshots = "data/old-screenshots"\n'
    )
    local_dir = tmp_path / ".asc"
    local_dir.mkdir()
    (local_dir / "config.toml").write_text('[defaults]\ndefault_app = "oldapp"\n')

    from unittest.mock import MagicMock, patch
    guard = MagicMock()
    guard.is_enabled.return_value = False
    with patch("asc.guard.Guard", return_value=guard):
        resp = client.put(
            "/api/profiles/oldapp",
            cookies={"asc_profile": "oldapp"},
            data={
                "name": "newapp",
                "issuer_id": "new-issuer",
                "key_id": "NEWKEY",
                "app_id": "222",
                "csv": "data/new.csv",
                "screenshots": "data/new-screenshots",
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "name": "newapp", "old_name": "oldapp"}
    assert not (profiles_dir / "oldapp.toml").exists()
    new_profile = (profiles_dir / "newapp.toml").read_text()
    assert 'issuer_id = "new-issuer"' in new_profile
    assert 'app_id = "222"' in new_profile
    assert 'default_app = "newapp"' in (local_dir / "config.toml").read_text()
    assert resp.cookies.get("asc_profile") == "newapp"


def test_profile_delete_api(client):
    from unittest.mock import patch
    with patch("asc.config.Config.remove_app_profile") as mock_remove:
        resp = client.delete("/api/profiles/myapp")
        assert resp.status_code == 200
        mock_remove.assert_called_once_with("myapp")


def test_guard_status_returns_json(client):
    from unittest.mock import patch, MagicMock
    mock_guard = MagicMock()
    mock_guard.get_status.return_value = {
        "enabled": True,
        "app_notes": {},
        "bindings": {"machine": {}, "ip": {}, "credential": {}},
    }
    mock_guard.current_environment.return_value = {
        "machine": {
            "fingerprint": "SERIAL-TEST",
            "bound": False,
            "app_id": "",
            "app_name": "",
            "note": "",
        },
        "ip": {
            "address": "1.2.3.4",
            "available": True,
            "bound": False,
            "app_id": "",
            "app_name": "",
            "note": "",
        },
    }
    with patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.get("/api/guard/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert "bindings" in data
    assert "current_profile" in data
    assert data["current_environment"]["machine"]["fingerprint"] == mask_identifier("SERIAL-TEST")
    assert data["current_environment"]["machine"]["bound"] is False
    assert data["current_environment"]["ip"]["address"] == mask_ip("1.2.3.4")


def test_guard_status_returns_full_fingerprint(client):
    from unittest.mock import patch, MagicMock
    long_fp = "a1b2c3d4e5f6g7h8i9j0"
    mock_guard = MagicMock()
    mock_guard.get_status.return_value = {
        "enabled": True,
        "bindings": {
            "machine": {long_fp: {"app_id": "123", "app_name": "myapp", "bound_at": "2026-05-18T10:00:00"}},
            "ip": {},
            "credential": {},
        },
    }
    mock_guard.current_environment.return_value = {
        "machine": {
            "fingerprint": long_fp,
            "bound": True,
            "app_id": "123",
            "app_name": "myapp",
            "note": "",
        },
        "ip": {
            "address": "9.9.9.9",
            "available": True,
            "bound": False,
            "app_id": "",
            "app_name": "",
            "note": "",
        },
    }
    with patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.get("/api/guard/status")
    data = resp.json()
    machine_keys = list(data["bindings"]["machine"].keys())
    assert len(machine_keys) == 1
    assert machine_keys[0] == mask_identifier(long_fp)
    assert data["current_environment"]["machine"]["bound"] is True
    assert data["current_environment"]["machine"]["app_id"] == "123"
    assert data["current_environment"]["machine"]["app_name"] == "myapp"


def test_guard_status_returns_machine_ip_credential_and_profile_name(client):
    """Web Guard page groups these fields; API must not drop any of them."""
    from unittest.mock import patch, MagicMock

    mock_guard = MagicMock()
    mock_guard.get_status.return_value = {
        "enabled": True,
        "app_notes": {"123": "office"},
        "bundle_bindings": {},
        "bindings": {
            "machine": {
                "SERIAL-FULL": {
                    "app_id": "123",
                    "app_name": "myapp",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                    "last_checked": "2026-05-19T11:00:00",
                }
            },
            "ip": {
                "1.2.3.4": {
                    "app_id": "123",
                    "app_name": "myapp",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                }
            },
            "credential": {
                "KEY1": {
                    "app_id": "123",
                    "app_name": "myapp",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                }
            },
        },
    }
    mock_guard.current_environment.return_value = {
        "machine": {
            "fingerprint": "SERIAL-FULL",
            "bound": True,
            "app_id": "123",
            "app_name": "myapp",
            "note": "office",
        },
        "ip": {
            "address": "1.2.3.4",
            "available": True,
            "bound": True,
            "app_id": "123",
            "app_name": "myapp",
            "note": "office",
        },
    }
    mock_config = MagicMock()
    mock_config.list_apps.return_value = ["myapp"]
    mock_config.get_app_profile.return_value = {"app_id": "123"}
    with patch("asc.guard.Guard", return_value=mock_guard), \
         patch("asc.config.Config", return_value=mock_config):
        resp = client.get("/api/guard/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert "error" not in data or not data["error"]
    assert "current_profile" in data
    assert data["app_notes"]["123"] == "office"
    assert list(data["bindings"]["machine"]) == [mask_identifier("SERIAL-FULL")]
    assert list(data["bindings"]["ip"]) == [mask_ip("1.2.3.4")]
    assert list(data["bindings"]["credential"]) == [mask_identifier("KEY1")]
    assert data["bindings"]["machine"][mask_identifier("SERIAL-FULL")]["profile_name"] == "myapp"
    assert data["bindings"]["ip"][mask_ip("1.2.3.4")]["profile_name"] == "myapp"
    assert data["bindings"]["credential"][mask_identifier("KEY1")]["profile_name"] == "myapp"
    assert data["bindings"]["credential"][mask_identifier("KEY1")]["issuer_id"] == mask_identifier("ISS1")
    env = data["current_environment"]
    assert env["machine"]["fingerprint"] == mask_identifier("SERIAL-FULL")
    assert env["machine"]["bound"] is True
    assert env["machine"]["app_id"] == "123"
    assert env["machine"]["profile_name"] == "myapp"
    assert env["machine"]["note"] == "office"
    assert env["ip"]["address"] == mask_ip("1.2.3.4")
    assert env["ip"]["available"] is True
    assert env["ip"]["bound"] is True
    assert env["ip"]["profile_name"] == "myapp"


def test_guard_status_returns_all_bindings_not_just_current(client):
    """Current profile/environment must not trim other machines, IPs, or apps."""
    from unittest.mock import patch, MagicMock

    mock_guard = MagicMock()
    mock_guard.get_status.return_value = {
        "enabled": True,
        "app_notes": {"111": "office", "222": "other desk"},
        "bundle_bindings": {},
        "bindings": {
            "machine": {
                "SERIAL-CURRENT": {
                    "app_id": "111",
                    "app_name": "app-one",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                },
                "SERIAL-OTHER-MAC": {
                    "app_id": "222",
                    "app_name": "app-two",
                    "issuer_id": "ISS2",
                    "bound_at": "2026-04-01T09:00:00",
                },
                "SERIAL-THIRD": {
                    "app_id": "111",
                    "app_name": "app-one",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-03-01T08:00:00",
                },
            },
            "ip": {
                "1.1.1.1": {
                    "app_id": "111",
                    "app_name": "app-one",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                },
                "8.8.8.8": {
                    "app_id": "222",
                    "app_name": "app-two",
                    "issuer_id": "ISS2",
                    "bound_at": "2026-04-01T09:00:00",
                },
            },
            "credential": {
                "KEY-ONE": {
                    "app_id": "111",
                    "app_name": "app-one",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                },
                "KEY-TWO": {
                    "app_id": "222",
                    "app_name": "app-two",
                    "issuer_id": "ISS2",
                    "bound_at": "2026-04-01T09:00:00",
                },
            },
        },
    }
    mock_guard.current_environment.return_value = {
        "machine": {
            "fingerprint": "SERIAL-CURRENT",
            "bound": True,
            "app_id": "111",
            "app_name": "app-one",
            "note": "office",
        },
        "ip": {
            "address": "1.1.1.1",
            "available": True,
            "bound": True,
            "app_id": "111",
            "app_name": "app-one",
            "note": "office",
        },
    }
    mock_config = MagicMock()
    mock_config.list_apps.return_value = ["app-one", "app-two"]
    mock_config.get_app_profile.side_effect = lambda name: {
        "app-one": {"app_id": "111"},
        "app-two": {"app_id": "222"},
    }[name]
    client.cookies.set("asc_profile", "app-one")
    with patch("asc.guard.Guard", return_value=mock_guard), \
         patch("asc.config.Config", return_value=mock_config):
        resp = client.get("/api/guard/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_profile"] == "app-one"
    assert set(data["bindings"]["machine"]) == {
        mask_identifier("SERIAL-CURRENT"),
        mask_identifier("SERIAL-OTHER-MAC"),
        mask_identifier("SERIAL-THIRD"),
    }
    assert set(data["bindings"]["ip"]) == {mask_ip("1.1.1.1"), mask_ip("8.8.8.8")}
    assert set(data["bindings"]["credential"]) == {
        mask_identifier("KEY-ONE"),
        mask_identifier("KEY-TWO"),
    }
    assert data["bindings"]["machine"][mask_identifier("SERIAL-OTHER-MAC")]["profile_name"] == "app-two"
    assert data["bindings"]["machine"][mask_identifier("SERIAL-CURRENT")]["profile_name"] == "app-one"
    assert data["bindings"]["credential"][mask_identifier("KEY-TWO")]["app_id"] == "222"
    assert data["app_notes"]["222"] == "other desk"
    env = data["current_environment"]
    assert env["machine"]["fingerprint"] == mask_identifier("SERIAL-CURRENT")
    assert len(data["bindings"]["machine"]) == 3
    assert len(data["bindings"]["ip"]) == 2
    assert len(data["bindings"]["credential"]) == 2


def test_guard_note_api_updates_app_note(client):
    from unittest.mock import patch, MagicMock
    mock_guard = MagicMock()
    mock_guard.set_app_note.return_value = True
    with patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.post("/api/guard/note", data={
            "app_id": "123456789",
            "note": "办公室 Mac",
        })
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_guard.set_app_note.assert_called_once_with("123456789", "办公室 Mac")


def test_guard_note_api_missing_app_returns_404(client):
    from unittest.mock import patch, MagicMock
    mock_guard = MagicMock()
    mock_guard.set_app_note.return_value = False
    with patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.post("/api/guard/note", data={
            "app_id": "missing.app",
            "note": "home",
        })
    assert resp.status_code == 404


def test_guard_note_api_persists_for_status_refresh(client, tmp_path):
    import json
    from unittest.mock import patch

    guard_file = tmp_path / "guard.json"
    guard_file.write_text(json.dumps({
        "enabled": True,
        "bindings": {
            "machine": {
                "SERIAL-C02ABC123456": {
                    "app_id": "123456789",
                    "app_name": "myapp",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                    "last_checked": "2026-05-18T10:00:00",
                },
            },
            "ip": {},
            "credential": {},
        },
        "app_notes": {},
    }))

    with patch("asc.guard.GUARD_FILE", guard_file):
        save_resp = client.post("/api/guard/note", data={
            "app_id": "123456789",
            "note": "办公室 Mac",
        })
        status_resp = client.get("/api/guard/status")

    assert save_resp.status_code == 200
    assert status_resp.status_code == 200
    assert status_resp.json()["app_notes"]["123456789"] == "办公室 Mac"


def test_guard_note_api_persists_when_binding_app_id_is_numeric(client, tmp_path):
    import json
    from unittest.mock import patch

    guard_file = tmp_path / "guard.json"
    guard_file.write_text(json.dumps({
        "enabled": True,
        "bindings": {
            "machine": {
                "SERIAL-C02ABC123456": {
                    "app_id": 123456789,
                    "app_name": "myapp",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-05-18T10:00:00",
                    "last_checked": "2026-05-18T10:00:00",
                },
            },
            "ip": {},
            "credential": {},
        },
        "app_notes": {},
    }))

    with patch("asc.guard.GUARD_FILE", guard_file):
        save_resp = client.post("/api/guard/note", data={
            "app_id": "123456789",
            "note": "办公室 Mac",
        })
        status_resp = client.get("/api/guard/status")

    assert save_resp.status_code == 200
    assert status_resp.json()["app_notes"]["123456789"] == "办公室 Mac"


def test_guard_manual_bind_api_requires_fingerprint(client):
    # Empty string form values are treated as "missing" by FastAPI's Form(...),
    # so the required-field check surfaces as a 422 before reaching our handler.
    resp = client.post("/api/guard/manual-bind", data={
        "fingerprint": "",
        "profile": "myapp",
    })
    assert resp.status_code == 422


def test_guard_manual_bind_api_requires_profile(client):
    resp = client.post("/api/guard/manual-bind", data={
        "fingerprint": "SERIAL-A",
        "profile": "",
    })
    assert resp.status_code == 422


def test_guard_manual_bind_api_rejects_whitespace_only_fingerprint(client):
    resp = client.post("/api/guard/manual-bind", data={
        "fingerprint": "   ",
        "profile": "myapp",
        "confirm": "true",
    })
    assert resp.status_code == 400


def test_guard_manual_bind_api_unknown_profile_returns_404(client):
    from unittest.mock import patch
    with patch("asc.config.Config.get_app_profile", return_value=None):
        resp = client.post("/api/guard/manual-bind", data={
            "fingerprint": "SERIAL-A",
            "profile": "missing-app",
            "confirm": "true",
        })
    assert resp.status_code == 404


def test_guard_manual_bind_api_success_uses_profile_credentials(client):
    from unittest.mock import patch, MagicMock

    mock_guard = MagicMock()
    mock_guard.manual_bind.return_value = {
        "fingerprint": "SERIAL-A",
        "app_id": "123",
        "app_name": "myapp",
        "issuer_id": "ISS1",
        "key_id": "KEY1",
        "ip": "",
        "note": "",
    }
    with patch("asc.config.Config.get_app_profile", return_value={
        "app_id": "123", "issuer_id": "ISS1", "key_id": "KEY1",
    }), patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.post("/api/guard/manual-bind", data={
            "fingerprint": "SERIAL-A",
            "profile": "myapp",
            "confirm": "true",
        })

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_guard.manual_bind.assert_called_once_with(
        "SERIAL-A",
        "myapp",
        app_id="123",
        issuer_id="ISS1",
        key_id="KEY1",
        ip="",
        note="",
    )


def test_guard_manual_bind_api_ignores_client_supplied_key_id(client):
    """Key ID 始终取自所选 profile，客户端传入的 key_id 应被忽略，不能覆盖。"""
    from unittest.mock import patch, MagicMock

    mock_guard = MagicMock()
    mock_guard.manual_bind.return_value = {}
    with patch("asc.config.Config.get_app_profile", return_value={
        "app_id": "123", "issuer_id": "ISS1", "key_id": "KEY-FROM-PROFILE",
    }), patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.post("/api/guard/manual-bind", data={
            "fingerprint": "SERIAL-A",
            "profile": "myapp",
            "key_id": "KEY-CLIENT-OVERRIDE",
            "ip": "1.2.3.4",
            "note": "office spare mac",
            "confirm": "true",
        })

    assert resp.status_code == 200
    mock_guard.manual_bind.assert_called_once_with(
        "SERIAL-A",
        "myapp",
        app_id="123",
        issuer_id="ISS1",
        key_id="KEY-FROM-PROFILE",
        ip="1.2.3.4",
        note="office spare mac",
    )


def test_guard_manual_bind_api_invalid_fingerprint_returns_400(client):
    from unittest.mock import patch, MagicMock
    from asc.guard import GuardConfigError

    mock_guard = MagicMock()
    mock_guard.manual_bind.side_effect = GuardConfigError("机器指纹不能为空")
    with patch("asc.config.Config.get_app_profile", return_value={
        "app_id": "123", "issuer_id": "ISS1", "key_id": "KEY1",
    }), patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.post("/api/guard/manual-bind", data={
            "fingerprint": "   ",
            "profile": "myapp",
            "confirm": "true",
        })

    assert resp.status_code == 400


def test_guard_manual_bind_api_persists_to_disk(client, tmp_path):
    import json
    from unittest.mock import patch

    guard_file = tmp_path / "guard.json"
    with patch("asc.guard.GUARD_FILE", guard_file), \
         patch("asc.config.Config.get_app_profile", return_value={
             "app_id": "123456789", "issuer_id": "ISS1", "key_id": "KEY1",
         }):
        resp = client.post("/api/guard/manual-bind", data={
            "fingerprint": "SERIAL-NEW-MACHINE",
            "profile": "myapp",
            "confirm": "true",
        })

    assert resp.status_code == 200
    data = json.loads(guard_file.read_text())
    assert data["bindings"]["machine"]["SERIAL-NEW-MACHINE"]["app_id"] == "123456789"
    assert data["bindings"]["machine"]["SERIAL-NEW-MACHINE"]["app_name"] == "myapp"
    assert data["bindings"]["credential"]["KEY1"]["app_id"] == "123456789"


def test_guard_manual_bind_api_rejects_already_bound_app(client):
    from unittest.mock import patch, MagicMock
    from asc.guard import GuardViolationError

    mock_guard = MagicMock()
    mock_guard.manual_bind.side_effect = GuardViolationError("该 App 已绑定到某台机器，请先解绑后再手动添加。")
    with patch("asc.config.Config.get_app_profile", return_value={
        "app_id": "123", "issuer_id": "ISS1", "key_id": "KEY1",
    }), patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.post("/api/guard/manual-bind", data={
            "fingerprint": "SERIAL-A",
            "profile": "myapp",
            "confirm": "true",
        })

    assert resp.status_code == 409
    assert "已绑定" in resp.json()["detail"]


def test_guard_manual_bind_api_rejects_already_bound_app_end_to_end(client, tmp_path):
    """真实 Guard 实例：已绑定的 App 再次手动添加应被拒绝，且不产生新绑定。"""
    import json
    from unittest.mock import patch

    guard_file = tmp_path / "guard.json"
    guard_file.write_text(json.dumps({
        "enabled": True,
        "bindings": {
            "machine": {
                "SERIAL-EXISTING": {
                    "app_id": "123456789",
                    "app_name": "myapp",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-01-01T00:00:00",
                }
            },
            "ip": {},
            "credential": {},
        },
        "app_notes": {},
    }))

    with patch("asc.guard.GUARD_FILE", guard_file), \
         patch("asc.config.Config.get_app_profile", return_value={
             "app_id": "123456789", "issuer_id": "ISS1", "key_id": "KEY1",
         }):
        resp = client.post("/api/guard/manual-bind", data={
            "fingerprint": "SERIAL-NEW",
            "profile": "myapp",
            "confirm": "true",
        })

    assert resp.status_code == 409
    data = json.loads(guard_file.read_text())
    assert "SERIAL-NEW" not in data["bindings"]["machine"]


def test_profiles_api_marks_already_bound_apps(client, tmp_path, monkeypatch):
    """/api/profiles 应标记出已绑定的本地 App，供手动添加表单过滤。"""
    import json

    monkeypatch.setenv("HOME", str(tmp_path))
    profiles_dir = tmp_path / ".config" / "asc" / "profiles"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "bound-app.toml").write_text(
        '[credentials]\n'
        'issuer_id = "ISS1"\n'
        'key_id = "KEY1"\n'
        'key_file = "/tmp/AuthKey_KEY1.p8"\n'
        'app_id = "111"\n\n'
        '[defaults]\n'
        'csv = "data/appstore_info.csv"\n'
        'screenshots = "data/screenshots"\n'
    )
    (profiles_dir / "free-app.toml").write_text(
        '[credentials]\n'
        'issuer_id = "ISS2"\n'
        'key_id = "KEY2"\n'
        'key_file = "/tmp/AuthKey_KEY2.p8"\n'
        'app_id = "222"\n\n'
        '[defaults]\n'
        'csv = "data/appstore_info.csv"\n'
        'screenshots = "data/screenshots"\n'
    )

    guard_file = tmp_path / "guard.json"
    guard_file.write_text(json.dumps({
        "enabled": True,
        "bindings": {
            "machine": {
                "SERIAL-BOUND": {
                    "app_id": "111",
                    "app_name": "bound-app",
                    "issuer_id": "ISS1",
                    "bound_at": "2026-01-01T00:00:00",
                }
            },
            "ip": {},
            "credential": {},
        },
        "app_notes": {},
    }))

    from unittest.mock import patch
    with patch("asc.guard.GUARD_FILE", guard_file):
        resp = client.get("/api/profiles")

    assert resp.status_code == 200
    details = resp.json()["profile_details"]
    assert details["bound-app"]["already_bound"] is True
    assert details["free-app"]["already_bound"] is False


def test_guard_status_error_returns_json(client):
    from unittest.mock import patch
    with patch("asc.guard.Guard", side_effect=Exception("read error")):
        resp = client.get("/api/guard/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["bindings"] == {"machine": {}, "ip": {}, "credential": {}}
    assert "error" in data
    assert "current_environment" in data
    assert data["current_environment"]["machine"]["bound"] is False


def test_task_store_create_with_profile_and_progress():
    from asc.web.tasks import TaskStore
    store = TaskStore()
    task_id = store.create("metadata", profile="myapp")
    task = store.get(task_id)
    assert task["kind"] == "metadata"
    assert task["profile"] == "myapp"
    assert task["progress"] == {
        "pct": 0,
        "msg": "",
        "phase": "",
        "phase_label": "",
        "phase_index": 0,
        "phase_total": 0,
    }


def test_task_store_list_recent_includes_profile():
    from asc.web.tasks import TaskStore
    store = TaskStore()
    store.create("metadata", profile="myapp")
    store.create("build", profile="staging")
    recent = store.list_recent(limit=20)
    assert recent[0]["profile"] == "staging"
    assert recent[1]["profile"] == "myapp"


def test_tasks_recent_endpoint_returns_json(client, monkeypatch):
    from asc.web import routes_api
    from asc.web.tasks import TaskStore

    store = TaskStore()
    task_id = store.create("build", profile="staging")

    def fail_full_logs(limit=20):
        raise AssertionError("recent JSON must not load full logs")

    monkeypatch.setattr(routes_api, "_task_store", store)
    monkeypatch.setattr(store, "list_recent", fail_full_logs)

    resp = client.get("/api/tasks/recent")
    assert resp.status_code == 200
    body = resp.json()
    assert "tasks" in body
    ids = [t["id"] for t in body["tasks"]]
    assert task_id in ids
    row = next(t for t in body["tasks"] if t["id"] == task_id)
    assert row["kind"] == "build"
    assert row["profile"] == "staging"
    assert "status" in row
    assert "progress" in row
    assert "build line" not in resp.text


def test_task_store_set_progress():
    from asc.web.tasks import TaskStore
    store = TaskStore()
    task_id = store.create("build", profile="staging")
    store.set_progress(task_id, 45, "元数据 5/11 语言")
    task = store.get(task_id)
    assert task["progress"] == {
        "pct": 45,
        "msg": "元数据 5/11 语言",
        "phase": "",
        "phase_label": "",
        "phase_index": 0,
        "phase_total": 0,
    }


def test_metadata_check_returns_level(client):
    from unittest.mock import patch, MagicMock
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.2.3", "appStoreState": "PREPARE_FOR_SUBMISSION"},
    }
    mock_config = MagicMock()
    mock_config.app_name = "testapp"
    with patch("asc.config.Config", return_value=mock_config), \
         patch("asc.utils.make_api_from_config", return_value=(mock_api, "app1")):
        resp = client.post("/api/metadata/check", cookies={"asc_profile": "testapp"})
        data = resp.json()
        assert data["level"] == "success"
        assert data["ok"] is True
        assert "detail" in data
        assert data["detail"]["version"] == "1.2.3"


def test_metadata_check_warning_level(client):
    from unittest.mock import patch, MagicMock
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {
        "id": "v1",
        "attributes": {"versionString": "1.2.3", "appStoreState": "WAITING_FOR_REVIEW"},
    }
    mock_config = MagicMock()
    mock_config.app_name = "testapp"
    with patch("asc.config.Config", return_value=mock_config), \
         patch("asc.utils.make_api_from_config", return_value=(mock_api, "app1")):
        resp = client.post("/api/metadata/check", cookies={"asc_profile": "testapp"})
        data = resp.json()
        assert data["level"] == "warning"


def test_metadata_check_error_level(client):
    from unittest.mock import patch, MagicMock
    mock_config = MagicMock()
    mock_config.app_name = "testapp"
    with patch("asc.config.Config", return_value=mock_config), \
         patch("asc.utils.make_api_from_config", side_effect=Exception("conn fail")):
        resp = client.post("/api/metadata/check", cookies={"asc_profile": "testapp"})
        data = resp.json()
        assert data["level"] == "error"
        assert data["ok"] is False


def test_metadata_core_outputs_progress(capsys):
    from asc.commands.metadata import _upload_metadata_core
    from unittest.mock import MagicMock
    mock_api = MagicMock()
    mock_api.get_app_infos.return_value = [{"id": "info1"}]
    mock_api.get_editable_version.return_value = {
        "id": "v1", "attributes": {"versionString": "1.0", "appStoreState": "PREPARE_FOR_SUBMISSION"}
    }
    mock_api.get_app_info_localizations.return_value = []
    mock_api.get_version_localizations.return_value = []
    mock_api.create_app_info_localization.return_value = {"id": "loc1"}
    mock_api.create_version_localization.return_value = {"id": "vloc1"}
    metadata_list = [
        {"locale": "en-US", "name": "Test", "description": "desc"},
        {"locale": "zh-CN", "name": "测试", "description": "描述"},
    ]
    _upload_metadata_core(mock_api, "app1", metadata_list, dry_run=True)
    captured = capsys.readouterr()
    assert "[PROGRESS:" not in captured.out
    assert "[52%] 上传:" in captured.out or "[52%] 上传" in captured.out
    assert "[100%]" in captured.out


def test_screenshots_core_outputs_progress(capsys, tmp_path):
    from asc.commands.screenshots import _upload_screenshots_core
    from unittest.mock import MagicMock, patch
    mock_api = MagicMock()
    mock_api.get_editable_version.return_value = {"id": "v1"}
    mock_api.get_version_localizations.return_value = [
        {"id": "loc1", "attributes": {"locale": "en-US"}},
        {"id": "loc2", "attributes": {"locale": "zh-CN"}},
    ]
    # Create screenshot folders
    en_dir = tmp_path / "en-US"
    en_dir.mkdir()
    (en_dir / "screen1.png").write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
    zh_dir = tmp_path / "zh-CN"
    zh_dir.mkdir()
    (zh_dir / "screen1.png").write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
    with patch("asc.commands.screenshots._detect_display_type", return_value="APP_IPHONE_67"), \
         patch("asc.commands.screenshots._get_sorted_screenshots", return_value=[en_dir / "screen1.png"]):
        _upload_screenshots_core(mock_api, "app1", str(tmp_path), dry_run=True)
    captured = capsys.readouterr()
    assert "[PROGRESS:" not in captured.out
    assert "[100%]" in captured.out
    assert "截图" in captured.out


def test_sse_stream_emits_progress():
    from asc.web.tasks import TaskStore, TaskStatus
    store = TaskStore()
    task_id = store.create("metadata", profile="myapp")
    store.set_status(task_id, TaskStatus.RUNNING)
    store.set_progress(task_id, 50, "测试进度")
    store.append_log(task_id, "some log")
    store.set_status(task_id, TaskStatus.DONE)

    # Verify progress field is accessible
    task = store.get(task_id)
    assert task["progress"]["pct"] == 50
    assert task["progress"]["msg"] == "测试进度"


def test_examples_csv_download(client):
    resp = client.get("/api/examples/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "appstore_info_example.csv" in resp.headers.get("content-disposition", "")
    assert "locale" in resp.text
    assert "name" in resp.text


def test_examples_screenshots_download(client):
    resp = client.get("/api/examples/screenshots")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "screenshots_example.zip" in resp.headers.get("content-disposition", "")
    assert len(resp.content) > 0


def test_examples_iap_download(client):
    resp = client.get("/api/examples/iap.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert "iap_packages_example.json" in resp.headers.get("content-disposition", "")
    assert len(resp.content) > 0

# IAP endpoint tests
def test_iap_check_api(client):
    from unittest.mock import patch, MagicMock
    from pathlib import Path
    mock_config = MagicMock()
    mock_config.iap_path = str(Path('data/iap_packages.json'))
    with patch('asc.web.routes_iap.Config', return_value=mock_config),          patch('pathlib.Path.exists', return_value=True),          patch('asc.web.routes_iap._load_iap_config', return_value=([{'productId': 'com.test.item1'}], [])):
        resp = client.post('/api/iap/check', cookies={'asc_profile': 'testapp'})
        assert resp.status_code == 200, f'Got {resp.status_code}'
        data = resp.json()
        assert data['ok'] is True
        assert data['level'] == 'success'
        print('test_iap_check_api: PASS')

def test_iap_run_api_starts_task(client):
    from unittest.mock import patch, MagicMock
    mock_config = MagicMock()
    mock_config.iap_path = 'data/iap_packages.json'
    with patch('asc.web.routes_iap.Config', return_value=mock_config),          patch('asc.web.routes_iap._task_store') as mock_store:
        mock_store.create.return_value = 'fake-task-id'
        resp = client.post(
            '/api/iap/run',
            data={'iap_file': 'data/iap_packages.json'},
            cookies={'asc_profile': 'testapp'},
        )
        assert resp.status_code == 200, f'Got {resp.status_code}: {resp.text}'
        data = resp.json()
        assert 'task_id' in data
        mock_store.create.assert_called_once()
        print('test_iap_run_api_starts_task: PASS')

def test_iap_check_missing_file(client):
    from unittest.mock import patch, MagicMock
    from pathlib import Path
    mock_config = MagicMock()
    mock_config.iap_path = 'nonexistent.json'
    with patch('asc.web.routes_iap.Config', return_value=mock_config),          patch('pathlib.Path.exists', return_value=False):
        resp = client.post('/api/iap/check', cookies={'asc_profile': 'testapp'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['ok'] is False
        assert data['level'] == 'error'
        print('test_iap_check_missing_file: PASS')


def test_profiles_discover_local_empty_when_no_env(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resp = client.get("/api/profiles/discover-local")
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidates"] == []
    assert data["cwd"] == str(tmp_path.resolve())


def test_profiles_discover_local_returns_candidate(client, tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch

    config_dir = tmp_path / "AppStore" / "Config"
    config_dir.mkdir(parents=True)
    (config_dir / ".env").write_text(
        "ISSUER_ID=issuer-1\nKEY_ID=KEY1\nKEY_FILE=AuthKey.p8\nAPP_ID=999\n",
        encoding="utf-8",
    )
    (config_dir / "AuthKey.p8").write_text("private-key", encoding="utf-8")
    nested = tmp_path / "subdir"
    nested.mkdir()
    monkeypatch.chdir(nested)

    mock_config = MagicMock()
    mock_config.list_apps.return_value = []
    mock_config.get_app_profile.return_value = None
    with patch("asc.config.Config", return_value=mock_config):
        resp = client.get("/api/profiles/discover-local")

    assert resp.status_code == 200
    candidates = resp.json()["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["app_id"] == "999"
    assert candidates[0]["key_file_exists"] is True
    assert candidates[0]["suggested_name"] == tmp_path.name


def test_profiles_discover_local_filters_already_imported(client, tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch

    config_dir = tmp_path / "AppStore" / "Config"
    config_dir.mkdir(parents=True)
    (config_dir / ".env").write_text(
        "ISSUER_ID=issuer-1\nKEY_ID=KEY1\nKEY_FILE=AuthKey.p8\nAPP_ID=999\n",
        encoding="utf-8",
    )
    (config_dir / "AuthKey.p8").write_text("private-key", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    mock_config = MagicMock()
    mock_config.list_apps.return_value = ["existing"]
    mock_config.get_app_profile.return_value = {
        "issuer_id": "issuer-1",
        "key_id": "KEY1",
        "app_id": "999",
    }
    with patch("asc.config.Config", return_value=mock_config):
        resp = client.get("/api/profiles/discover-local")

    assert resp.status_code == 200
    assert resp.json()["candidates"] == []


def test_profiles_import_local_api(client, tmp_path, monkeypatch):
    """POST /api/profiles/import 复用 CLI import 逻辑创建 profile"""
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config_dir = tmp_path / "AppStore" / "Config"
    config_dir.mkdir(parents=True)
    (config_dir / ".env").write_text(
        "ISSUER_ID=issuer-1\nKEY_ID=KEY1\nKEY_FILE=AuthKey.p8\nAPP_ID=999\n",
        encoding="utf-8",
    )
    (config_dir / "AuthKey.p8").write_text("private-key", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    guard = MagicMock()
    guard.is_enabled.return_value = False
    mock_config = MagicMock()
    mock_config.list_apps.return_value = []
    mock_config.get_app_profile.return_value = None

    with patch("asc.config.Config", return_value=mock_config), \
         patch("asc.guard.Guard", return_value=guard), \
         patch("asc.commands.app_config.Config", return_value=mock_config):
        resp = client.post(
            "/api/profiles/import",
            json={"name": "from-local", "set_default": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["name"] == "from-local"
    mock_config.save_app_profile.assert_called_once()
    assert (tmp_path / ".asc" / "config.toml").exists()
    assert 'default_app = "from-local"' in (tmp_path / ".asc" / "config.toml").read_text()


def test_profiles_import_local_api_404_when_none(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resp = client.post("/api/profiles/import", json={})
    assert resp.status_code == 404


def test_homepage_returns_spa(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text('<html><script src="/static/spa/assets/app.js"></script></html>', encoding="utf-8")
    monkeypatch.setattr("asc.web.server.SPA_INDEX", index)
    resp = TestClient(create_app()).get("/")
    assert resp.status_code == 200
    assert 'src="/static/spa/' in resp.text


def test_listing_returns_spa(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text('<html><script src="/static/spa/assets/app.js"></script></html>', encoding="utf-8")
    monkeypatch.setattr("asc.web.server.SPA_INDEX", index)
    resp = TestClient(create_app()).get("/listing")
    assert resp.status_code == 200
    assert 'src="/static/spa/' in resp.text


def test_spa_fallback_unknown_path_returns_index(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text('<html><script src="/static/spa/assets/app.js"></script></html>', encoding="utf-8")
    monkeypatch.setattr("asc.web.server.SPA_INDEX", index)
    resp = TestClient(create_app()).get("/listing")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert 'src="/static/spa/' in resp.text
    assert resp.headers.get("cache-control") == "no-cache"


def test_spa_fallback_missing_index_returns_503(monkeypatch):
    monkeypatch.setattr("asc.web.server.SPA_INDEX", Path("/nonexistent/spa/index.html"))
    resp = TestClient(create_app()).get("/system/profiles")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "spa_not_built"
    assert "npm run build" in body["message"]


def test_unknown_api_path_still_404(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text("<html>spa</html>", encoding="utf-8")
    monkeypatch.setattr("asc.web.server.SPA_INDEX", index)
    resp = TestClient(create_app()).get("/api/does-not-exist")
    assert resp.status_code == 404


