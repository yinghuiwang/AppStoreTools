# tests/test_web_server.py
from __future__ import annotations
from datetime import datetime
import inspect
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from asc.web.server import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def isolated_web_task_guard(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr(
        "asc.web.routes_api.enforce_config_guard",
        MagicMock(),
    )


def test_homepage_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "AppStore Tools" in resp.text


def test_homepage_loads_dashboard_script_once_in_document_head(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.text.count('src="/static/dashboard.js') == 1
    assert resp.text.index('src="/static/dashboard.js') < resp.text.index("</head>")
    assert "dashboard.js?v=" in resp.text
    assert "dashboard.css?v=" in resp.text


def test_dashboard_javascript_is_served_with_refresh_and_cancel_contract(client):
    resp = client.get("/static/dashboard.js")

    assert resp.status_code == 200
    assert "AbortController" in resp.text
    assert "/api/dashboard/summary" in resp.text
    assert "Number(state.metrics && state.metrics.active_count) > 0" in resp.text
    assert 'retryPaths.indexOf(task.retry_path) !== -1' in resp.text
    assert "data-dashboard-cancel-task" in resp.text
    assert 'function cancelRunningTask(taskId, button)' in resp.text
    assert '"/cancel"' in resp.text
    assert "确定要终止该任务吗？" in resp.text
    # Log streaming/rendering now lives entirely in the shared TaskLogDrawer.
    assert "EventSource" not in resp.text
    assert "logPreflightController" not in resp.text


def test_dashboard_running_tasks_expose_cancel_control(client, monkeypatch):
    from asc.web import server

    created_at = datetime.now().isoformat()
    monkeypatch.setattr(
        server.task_store,
        "list_recent_states",
        lambda limit=500: [
            {
                "id": "running-1",
                "kind": "urls",
                "title": "URL 更新",
                "profile": "test",
                "status": "running",
                "created_at": created_at,
                "updated_at": created_at,
                "completed_at": None,
                "progress": {"pct": 40, "msg": "更新中"},
            }
        ],
    )

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'data-dashboard-cancel-task="running-1"' in resp.text
    assert 'aria-label="终止URL 更新"' in resp.text
    assert ">终止</button>" in resp.text
    assert 'class="dashboard-running-task__actions"' in resp.text


def test_dashboard_javascript_wires_progress_callback_through_task_log_drawer(client):
    script = client.get("/static/dashboard.js")
    page = client.get("/")

    assert script.status_code == 200
    assert page.status_code == 200
    assert "function updateTaskProgress(taskId, progress)" in script.text
    assert "onProgress: function (pct, msg)" in script.text
    assert "updateTaskProgress(taskId, { pct: pct, msg: msg })" in script.text
    # Error filter/copy tooling now lives in the shared drawer markup, not dashboard.js.
    assert "renderLogEntries" not in script.text
    assert 'data-task-log-errors aria-pressed="false"' in page.text
    assert ">仅错误</button>" in page.text


def test_task_log_drawer_javascript_pauses_follow_without_moving_viewport(client):
    resp = client.get("/static/task-log-drawer.js")

    assert resp.status_code == 200
    assert "function pauseAtCurrentViewport()" in resp.text
    assert "var scrollTop = output.scrollTop;" in resp.text
    assert "setFollow(false);" in resp.text
    assert "output.scrollTop = scrollTop;" in resp.text
    assert "copyControl.addEventListener" in resp.text
    assert "errorsControl.addEventListener" in resp.text


def test_dashboard_javascript_preserves_keyboard_focus_across_re_renders(client):
    resp = client.get("/static/dashboard.js")

    assert resp.status_code == 200
    assert "captureTaskFocus" in resp.text
    assert "restoreTaskFocus" in resp.text
    assert 'section.querySelectorAll("[data-task-id]")' in resp.text
    assert 'action = "retry"' in resp.text
    assert 'action = "log"' in resp.text
    assert 'action = "cancel"' in resp.text
    assert 'snapshot.action === "cancel"' in resp.text
    # Drawer overlay/focus-trap concerns now live in the shared TaskLogDrawer.
    assert "trapDrawerFocus" not in resp.text


def test_task_log_drawer_javascript_traps_focus_in_overlay_mode(client):
    resp = client.get("/static/task-log-drawer.js")

    assert resp.status_code == 200
    assert 'window.matchMedia("(max-width: 1360px)")' in resp.text
    assert 'drawer.setAttribute("aria-modal", modal ? "true" : "false")' in resp.text
    assert 'element.setAttribute("inert", "")' in resp.text
    assert 'element.removeAttribute("inert")' in resp.text
    assert 'document.querySelector("body > aside")' in resp.text
    assert 'element.setAttribute("aria-hidden", "true")' in resp.text
    assert 'event.key !== "Tab"' in resp.text
    assert "previouslyFocused" in resp.text


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


def test_homepage_exposes_dashboard_root_and_current_profile(client, monkeypatch):
    monkeypatch.setattr("asc.config.Config.list_apps", lambda self: ["myapp"])
    monkeypatch.setattr(
        "asc.config.Config.get_app_profile",
        lambda self, name: {"app_id": "123"},
    )
    monkeypatch.setattr(
        "asc.guard.Guard.profile_access",
        lambda self, profiles: {
            "options": {"myapp": {"enabled": True}},
            "matched_profile": "myapp",
        },
    )

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'id="dashboard-root"' in resp.text
    assert 'data-current-profile="myapp"' in resp.text


def test_homepage_contains_command_workspace_landmarks(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert 'id="dashboard-summary"' in resp.text
    assert 'id="dashboard-task-list"' in resp.text
    assert 'id="task-log-dock"' in resp.text
    assert 'id="task-log-drawer"' in resp.text
    assert 'id="task-log-output"' in resp.text
    assert 'data-dashboard-filter="range"' in resp.text
    assert 'href="/metadata?action=check"' in resp.text
    assert 'href="/metadata?action=all"' in resp.text
    assert 'href="/metadata?action=metadata"' in resp.text
    assert 'href="/metadata?action=screenshots"' in resp.text
    assert 'href="/build?action=build-upload"' in resp.text
    assert "发布版本" not in resp.text
    assert 'class="dashboard-filters" role="group" aria-label="任务筛选"' in resp.text
    assert 'role="dialog"' in resp.text
    assert 'aria-modal="false"' in resp.text
    assert 'data-dashboard-filter="kind"' in resp.text
    assert '<option value="pending">等待中</option>' in resp.text
    assert "检查环境" in resp.text
    assert "预计节省时间如何计算" in resp.text


def test_homepage_dashboard_modules_follow_priority_order(client):
    resp = client.get("/")
    css = client.get("/static/dashboard.css")

    assert resp.status_code == 200
    assert css.status_code == 200
    # DOM source order encodes functional priority for a11y / narrow-screen stack:
    # running → history → quick → metrics.
    running_at = resp.text.index('class="dashboard-running"')
    history_at = resp.text.index('class="dashboard-history"')
    workspace_at = resp.text.index('class="dashboard-workspace"')
    summary_at = resp.text.index('id="dashboard-summary"')
    assert running_at < history_at < workspace_at < summary_at
    assert 'class="dashboard-metrics-rail"' in resp.text
    assert resp.text.index('class="dashboard-workspace"') < resp.text.index('class="dashboard-metrics-rail"')
    # Desktop board: left stack (running/quick/metrics), history alone on the right.
    assert 'grid-template-areas:' in css.text
    assert '"running history"' in css.text
    assert '"quick history"' in css.text
    assert '"metrics history"' in css.text
    assert "grid-area: running" in css.text
    assert "grid-area: history" in css.text
    assert "grid-area: quick" in css.text
    assert "grid-area: metrics" in css.text


def test_homepage_does_not_render_untrusted_retry_path(client, monkeypatch):
    from asc.web import server

    task = {"id": "bad", "kind": "metadata", "profile": "test", "status": "error", "created_at": datetime.now().isoformat(), "retry_path": "//evil.example"}
    monkeypatch.setattr(server.task_store, "list_recent_states", lambda limit: [task])

    resp = client.get("/")
    assert 'href="//evil.example"' not in resp.text


def test_homepage_loads_dashboard_stylesheet_in_document_head(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.text.count('href="/static/dashboard.css') == 1
    assert resp.text.index('href="/static/dashboard.css') < resp.text.index("</head>")


def test_homepage_summary_uses_range_neutral_accessible_name(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert 'id="dashboard-summary" class="dashboard-summary" aria-label="任务概览"' in resp.text
    assert 'aria-label="30 天任务概览"' not in resp.text


def test_dashboard_stylesheet_is_served_with_workspace_and_dock_layout(client):
    resp = client.get("/static/dashboard.css")

    assert resp.status_code == 200
    assert ".dashboard-shell" in resp.text
    assert ".dashboard-metrics-rail" in resp.text
    assert "height: calc(100vh - 4rem)" in resp.text
    assert "body > aside { display: none" not in resp.text
    assert "body > aside { width: 56px !important; }" in resp.text
    assert "@media (max-width: 980px)" in resp.text
    assert "overflow-y: auto;" in resp.text
    assert "flex: 0 0 40px;" in resp.text
    assert ".dashboard-running-task__actions" in resp.text
    assert ".dashboard-running-task__actions .dashboard-cancel-button:hover" in resp.text
    assert "rgba(248, 113, 113, .14)" in resp.text
    assert "#f87171" in resp.text
    assert ".dashboard-cancel-button { border-color: rgba(248, 113, 113, .25)" not in resp.text
    # Drawer chrome / dock host now live solely in task-log-drawer.css.
    assert ".dashboard-log-drawer" not in resp.text
    assert ".task-log-dock" not in resp.text


def test_task_log_drawer_stylesheet_defines_drawer_and_dock_modes(client):
    resp = client.get("/static/task-log-drawer.css")

    assert resp.status_code == 200
    assert ".task-log-drawer" in resp.text
    assert ".task-log-drawer.is-overlay" in resp.text
    assert ".task-log-drawer.is-docked" in resp.text
    assert ".task-log-dock" in resp.text
    assert "@media (max-width: 1360px)" in resp.text


def test_mobile_sidebar_navigation_links_have_accessible_tooltips(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert 'aria-label="仪表盘" title="仪表盘"' in resp.text
    assert 'aria-label="元数据上传" title="元数据上传"' in resp.text
    assert 'aria-label="构建上传" title="构建上传"' in resp.text


def test_homepage_dashboard_context_avoids_loading_task_logs(client, monkeypatch):
    from asc.web import server

    monkeypatch.setattr(
        server.task_store,
        "list_recent",
        lambda **kwargs: pytest.fail("homepage must not load task logs"),
    )
    calls = []

    def list_recent_states(*, limit):
        calls.append(limit)
        return []

    monkeypatch.setattr(server.task_store, "list_recent_states", list_recent_states)

    resp = client.get("/")

    assert resp.status_code == 200
    assert calls == [500]


def test_metadata_page_returns_200(client):
    resp = client.get("/metadata")
    assert resp.status_code == 200
    assert ">locale</code>" in resp.text
    assert ">name</code>" in resp.text
    assert "仍兼容中文表头" in resp.text


def test_metadata_page_uses_shared_task_log_drawer(client):
    resp = client.get("/metadata")
    assert resp.status_code == 200
    assert "TaskLogDrawer.open" in resp.text
    assert "data-task-log-open" in resp.text
    assert "new EventSource(`/api/task/${taskId}/stream`)" not in resp.text
    assert 'id="log-panel"' not in resp.text


@pytest.mark.parametrize("path", ["/urls", "/whats-new", "/iap", "/update"])
def test_feature_page_uses_shared_task_log_drawer(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "TaskLogDrawer.open" in resp.text
    assert "data-task-log-open" in resp.text
    assert "new EventSource(" not in resp.text or "TaskLogDrawer" in resp.text
    assert "function startSSE" not in resp.text
    assert "function startIapSSE" not in resp.text
    assert 'id="log-panel"' not in resp.text
    assert 'id="iap-log-panel"' not in resp.text


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("check", 'data-workflow-action="check"'),
        ("all", 'data-workflow-action="all"'),
        ("metadata", 'data-workflow-action="metadata"'),
        ("screenshots", 'data-workflow-action="screenshots"'),
    ],
)
def test_metadata_quick_actions_select_a_valid_workflow(client, action, expected):
    resp = client.get("/metadata", params={"action": action})

    assert resp.status_code == 200
    assert expected in resp.text


def test_metadata_quick_action_rejects_unknown_workflow(client):
    resp = client.get("/metadata", params={"action": "unknown"})

    assert resp.status_code == 200
    assert 'data-workflow-action=""' in resp.text


def test_build_page_returns_200(client):
    resp = client.get("/build")
    assert resp.status_code == 200


def test_build_quick_action_selects_build_upload_workflow(client):
    resp = client.get("/build", params={"action": "build-upload"})

    assert resp.status_code == 200
    assert 'data-workflow-action="build-upload"' in resp.text


def test_build_page_uses_shared_task_log_drawer_and_keeps_scan_panel(client):
    resp = client.get("/build")
    assert resp.status_code == 200
    assert "TaskLogDrawer.open" in resp.text
    assert "data-task-log-open" in resp.text
    assert "data-task-log-yield" in resp.text
    assert "自动检测结果" in resp.text
    assert "startBuildSSE" not in resp.text
    assert 'id="build-log-panel"' not in resp.text


def test_iap_page_contains_review_screenshot_tools(client):
    resp = client.get("/iap")
    assert resp.status_code == 200
    assert "补审核截图" in resp.text
    assert "/api/iap/review-screenshots/scan" in resp.text
    assert "/api/iap/review-screenshots/upload" in resp.text


def test_blocking_web_probes_run_in_threadpool():
    from asc.web import routes_api

    assert not inspect.iscoroutinefunction(routes_api.dashboard_summary)
    assert not inspect.iscoroutinefunction(routes_api.build_schemes)
    assert not inspect.iscoroutinefunction(routes_api.build_options)
    assert not inspect.iscoroutinefunction(routes_api.whats_new_check)


def test_homepage_dashboard_storage_query_runs_in_threadpool():
    app = create_app()
    homepage = next(route.endpoint for route in app.routes if route.path == "/")

    assert not inspect.iscoroutinefunction(homepage)


def test_update_check_includes_current_commit(client):
    from unittest.mock import patch

    with patch("asc.commands.update_cmd._current_version", return_value="0.1.17"), \
            patch("asc.commands.update_cmd._latest_version_from_github", return_value="0.1.18"), \
            patch("asc.commands.update_cmd._resolve_git_ref_commit", return_value="abcdef1234567890"), \
            patch("asc.cli._installed_commit_short", return_value="15e4b3a"):
        resp = client.get("/api/update/check")

    assert resp.status_code == 200
    data = resp.json()
    assert data["detail"]["current"] == "0.1.17"
    assert data["detail"]["current_commit"] == "15e4b3a"
    assert data["detail"]["latest"] == "0.1.18"
    assert data["detail"]["latest_commit"] == "abcdef1"
    assert "commit 15e4b3a" in data["message"]
    assert "最新版本: 0.1.18 (commit abcdef1)" in data["message"]


def test_update_branches_returns_options(client):
    from unittest.mock import patch

    with patch("asc.commands.update_cmd._branches_from_github", return_value=["develop", "main"]):
        resp = client.get("/api/update/branches")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["branches"] == ["develop", "main"]


def test_update_page_contains_always_available_advanced_install(client):
    resp = client.get("/update")

    assert resp.status_code == 200
    assert "高级安装" in resp.text
    assert "指定版本" in resp.text
    assert "指定分支" in resp.text
    assert "runUpdate('', 'latest')" in resp.text
    assert "runUpdate($el.querySelector('[name=version]').value, 'specific')" in resp.text
    assert "runUpdateBranch(selectedBranch || $el.querySelector('[name=branch]')?.value || '')" in resp.text
    assert "/api/update/run" in resp.text
    assert "/api/update/branches" in resp.text


def test_profiles_page_returns_200(client):
    resp = client.get("/profiles")
    assert resp.status_code == 200
    assert ">locale</code>" in resp.text
    assert ">name</code>" in resp.text
    assert "仍兼容中文表头" in resp.text


def test_settings_page_returns_200(client):
    resp = client.get("/settings")
    assert resp.status_code == 200


def test_guard_page_returns_200(client):
    resp = client.get("/guard")
    assert resp.status_code == 200


def test_filebrowser_returns_html(client, tmp_path):
    resp = client.get(f"/api/browse?path={tmp_path}&mode=dir")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]

def test_filebrowser_lists_files(client, tmp_path):
    (tmp_path / "test.csv").write_text("a,b")
    resp = client.get(f"/api/browse?path={tmp_path}&mode=file&ext=.csv")
    assert resp.status_code == 200
    assert "test.csv" in resp.text


def test_filebrowser_accepts_comma_separated_extensions_case_insensitive(client, tmp_path):
    (tmp_path / "image.jpg").write_bytes(b"jpg")
    (tmp_path / "image.jpeg").write_bytes(b"jpeg")
    (tmp_path / "image.PNG").write_bytes(b"png")
    (tmp_path / "notes.txt").write_text("text")

    resp = client.get(f"/api/browse?path={tmp_path}&mode=file&ext=.png,.jpg,.jpeg")

    assert resp.status_code == 200
    assert "image.jpg" in resp.text
    assert "image.jpeg" in resp.text
    assert "image.PNG" in resp.text
    assert "notes.txt" not in resp.text


def test_filebrowser_directory_click_browses_into_directory(client, tmp_path):
    (tmp_path / "nested").mkdir()
    resp = client.get(f"/api/browse?path={tmp_path}&mode=dir")
    assert resp.status_code == 200
    assert 'data-fb-action="browse"' in resp.text
    assert "nested" in resp.text


def test_filebrowser_rejects_outside_home(client):
    resp = client.get("/api/browse?path=/etc&mode=dir")
    assert resp.status_code == 403


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

    with patch("asc.web.routes_api.Config") as mock_config_cls, \
         patch("asc.web.routes_api.make_api_from_config", return_value=(MagicMock(), "app-1")), \
         patch("asc.web.routes_api.scan_missing_review_screenshots", return_value=scan_result):
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
    with patch("asc.web.routes_api._scan_iap_review_screenshot_targets") as mock_scan, \
         patch("asc.web.routes_api.scan_missing_review_screenshots") as mock_scan_helper:
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
    with patch("asc.web.routes_api._scan_iap_review_screenshot_targets") as mock_scan:
        resp = client.post(
            "/api/iap/review-screenshots/scan",
            cookies={"asc_profile": "myapp"},
            json={"iapFile": 123},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "iapFile must be a string"
    mock_scan.assert_not_called()


def test_iap_review_screenshots_upload_starts_task_with_items(client):
    with patch("asc.web.routes_api._start_iap_review_screenshots_task") as mock_start:
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
    with patch("asc.web.routes_api._start_iap_review_screenshots_task") as mock_start:
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
    with patch("asc.web.routes_api._start_iap_review_screenshots_task") as mock_start:
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
    with patch("asc.web.routes_api._start_iap_review_screenshots_task") as mock_start:
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
    with patch("asc.web.routes_api._start_iap_review_screenshots_task") as mock_start:
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

    with patch("asc.web.routes_api.Config"), \
         patch("asc.web.routes_api.make_api_from_config", return_value=(MagicMock(), "app-1")), \
         patch("asc.web.routes_api.scan_missing_review_screenshots", return_value=current_scan), \
         patch("asc.web.routes_api.upload_review_screenshots") as mock_upload:
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
                "project": ".",
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


def test_task_cancel_endpoint(client):
    from asc.web.tasks import task_store, TaskStatus
    task_id = task_store.create("build")
    task_store.set_status(task_id, TaskStatus.RUNNING)

    resp = client.post(f"/api/task/{task_id}/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == task_id
    assert data["cancel_requested"] is True
    assert data["status"] == "canceled"
    task = task_store.get(task_id)
    assert task["cancel_requested"] is True
    assert task["status"] == TaskStatus.CANCELED
    assert any("已请求终止" in line for line in task["logs"])
    assert any("任务已终止" in line for line in task["logs"])


def test_task_cancel_endpoint_force_finishes_stuck_urls_task(client):
    from asc.web.tasks import task_store, TaskStatus

    task_id = task_store.create("urls", profile="test")
    task_store.set_status(task_id, TaskStatus.RUNNING)
    task_store.set_progress(task_id, 40, "更新 marketingUrl")

    resp = client.post(f"/api/task/{task_id}/cancel")

    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"
    task = task_store.get(task_id)
    assert task["status"] == TaskStatus.CANCELED
    assert task["result"] == {"success": False, "canceled": True}
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
        "issuer_id": "issuer-123",
        "key_id": "KEY123",
        "key_file_name": "AuthKey_KEY123.p8",
        "app_id": "123456789",
        "csv": "data/appstore_info.csv",
        "screenshots": "data/screenshots",
        "machine_access": {"current": False, "elsewhere": False, "enabled": True},
        "bundle_ids": [],
    }


def test_profiles_page_shows_profile_detail_fields(client):
    resp = client.get("/profiles")
    assert resp.status_code == 200
    assert "App ID" in resp.text
    assert "Issuer ID" in resp.text
    assert "Key ID" in resp.text
    assert "CSV" in resp.text
    assert "截图" in resp.text

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
            "csv": "data/appstore_info.csv",
            "screenshots": "data/screenshots",
        }, files={"key_file": ("AuthKey_KEYID123.p8", p8_content, "application/octet-stream")})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_save.assert_called_once()


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


def test_sidebar_disables_other_machine_profile(client):
    from unittest.mock import MagicMock, patch

    config = MagicMock()
    config.list_apps.return_value = ["current-app", "other-app"]
    config.app_name = "other-app"
    config.csv_path = "data/appstore_info.csv"
    config.screenshots_path = "data/screenshots"
    config.iap_path = None
    config.get_app_profile.side_effect = lambda name: {
        "app_id": "app-1" if name == "current-app" else "app-2",
        "issuer_id": "ISS-1" if name == "current-app" else "ISS-2",
    }
    access = {
        "matched_profile": "current-app",
        "options": {
            "current-app": {"enabled": True, "current": True, "elsewhere": False},
            "other-app": {"enabled": False, "current": False, "elsewhere": True},
        },
    }
    with patch("asc.config.Config", return_value=config), \
         patch("asc.guard.Guard.profile_access", return_value=access):
        response = client.get("/", cookies={"asc_profile": "other-app"})

    assert response.status_code == 200
    assert 'value="current-app"' in response.text
    assert 'data-current-profile="current-app"' in response.text
    assert "current-app" in response.text
    assert 'value="other-app"' in response.text
    assert "disabled" in response.text
    assert response.cookies.get("asc_profile") == "current-app"


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
    with patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.get("/api/guard/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert "bindings" in data
    assert "current_profile" in data


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
    with patch("asc.guard.Guard", return_value=mock_guard):
        resp = client.get("/api/guard/status")
    data = resp.json()
    machine_keys = list(data["bindings"]["machine"].keys())
    assert len(machine_keys) == 1
    assert machine_keys[0] == long_fp


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


def test_guard_page_has_guard_note_editor(client):
    resp = client.get("/guard")
    assert resp.status_code == 200
    assert "/api/guard/note" in resp.text
    assert "保存备注" in resp.text
    assert "App ID" in resp.text
    assert "凭证 Key ID" not in resp.text


def test_guard_status_error_returns_json(client):
    from unittest.mock import patch
    with patch("asc.guard.Guard", side_effect=Exception("read error")):
        resp = client.get("/api/guard/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["bindings"] == {"machine": {}, "ip": {}, "credential": {}}
    assert "error" in data


def test_task_store_create_with_profile_and_progress():
    from asc.web.tasks import TaskStore
    store = TaskStore()
    task_id = store.create("metadata", profile="myapp")
    task = store.get(task_id)
    assert task["kind"] == "metadata"
    assert task["profile"] == "myapp"
    assert task["progress"] == {"pct": 0, "msg": ""}


def test_task_store_list_recent_includes_profile():
    from asc.web.tasks import TaskStore
    store = TaskStore()
    store.create("metadata", profile="myapp")
    store.create("build", profile="staging")
    recent = store.list_recent(limit=20)
    assert recent[0]["profile"] == "staging"
    assert recent[1]["profile"] == "myapp"


def test_tasks_recent_endpoint(client):
    resp = client.get("/api/tasks/recent")
    assert resp.status_code == 200


def test_tasks_recent_markup_preserves_log_toggle_state(client, monkeypatch):
    from asc.web import routes_api
    from asc.web.tasks import TaskStatus, TaskStore

    store = TaskStore()
    task_id = store.create("build", profile="staging")
    store.set_status(task_id, TaskStatus.RUNNING)
    store.append_log(task_id, "build line")
    monkeypatch.setattr(routes_api, "_task_store", store)

    resp = client.get("/api/tasks/recent")

    assert resp.status_code == 200
    assert f'data-task-id="{task_id}"' in resp.text
    assert f"toggleTaskLogs('{task_id}')" in resp.text
    assert f'data-task-log-panel="{task_id}"' in resp.text


def test_task_store_set_progress():
    from asc.web.tasks import TaskStore
    store = TaskStore()
    task_id = store.create("build", profile="staging")
    store.set_progress(task_id, 45, "元数据 5/11 语言")
    task = store.get(task_id)
    assert task["progress"] == {"pct": 45, "msg": "元数据 5/11 语言"}


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
    assert "[PROGRESS:50:元数据 1/2 语言]" in captured.out
    assert "[PROGRESS:100:元数据 2/2 语言]" in captured.out


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
    assert "[PROGRESS:" in captured.out
    assert "截图" in captured.out


def test_progress_parsing_in_drain_loop():
    import re
    line = "[PROGRESS:45:元数据 5/11 语言]"
    match = re.match(r"\[PROGRESS:(\d+):(.+)\]", line)
    assert match is not None
    assert match.group(1) == "45"
    assert match.group(2) == "元数据 5/11 语言"


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
    with patch('asc.web.routes_api.Config', return_value=mock_config),          patch('pathlib.Path.exists', return_value=True),          patch('asc.web.routes_api._load_iap_config', return_value=([{'productId': 'com.test.item1'}], [])):
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
    with patch('asc.web.routes_api.Config', return_value=mock_config),          patch('asc.web.routes_api._task_store') as mock_store:
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
    with patch('asc.web.routes_api.Config', return_value=mock_config),          patch('pathlib.Path.exists', return_value=False):
        resp = client.post('/api/iap/check', cookies={'asc_profile': 'testapp'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['ok'] is False
        assert data['level'] == 'error'
        print('test_iap_check_missing_file: PASS')

def test_task_log_drawer_javascript_closes_on_outside_click_in_overlay_mode(client):
    resp = client.get("/static/task-log-drawer.js")

    assert resp.status_code == 200
    assert 'document.addEventListener("click", function (event)' in resp.text
    assert 'if (!isDrawerOpen() || drawer.contains(event.target)) return;' in resp.text
    assert 'if (!isOverlayMode()) return;' in resp.text
    assert "close();" in resp.text


def test_task_log_drawer_slide_animation(client):
    css = client.get("/static/task-log-drawer.css")
    js = client.get("/static/task-log-drawer.js")

    assert css.status_code == 200
    assert js.status_code == 200
    assert "translateX(100%)" in css.text
    assert "translateX(0)" in css.text
    assert ".is-open" in css.text
    assert "transition:" in css.text
    assert "function openDrawerPanel()" in js.text
    assert "function beginCloseDrawerPanel()" in js.text
    assert 'void drawer.offsetWidth;' in js.text
    assert 'event.propertyName !== "transform"' in js.text
    assert "drawer.hidden = true;" in js.text
    assert 'drawer.classList.add("is-open")' in js.text
    assert 'drawer.classList.remove("is-open")' in js.text


def test_dashboard_javascript_delegates_logs_to_task_log_drawer(client):
    resp = client.get("/static/dashboard.js")
    assert resp.status_code == 200
    assert "TaskLogDrawer.open" in resp.text
    assert "TaskLogDrawer.attachDock" in resp.text


def test_task_log_drawer_javascript_exposes_public_api(client):
    resp = client.get("/static/task-log-drawer.js")
    assert resp.status_code == 200
    body = resp.text
    assert "window.TaskLogDrawer" in body
    assert "function open(" in body or "open: function" in body or "open(" in body
    assert "attachDock" in body
    assert "preferOverlay" in body
    assert 'getElementById("task-log-dock")' in body
    assert "data-task-log-yield" in body
    assert "/api/task/" in body
    assert '"/status"' in body or "/status" in body
    assert "stream?after=0" in body
    assert "data-task-log-errors" in body
    assert "data-task-log-follow" in body
    assert "任务不存在或已被清理" in body


def test_base_layout_includes_task_log_drawer_assets(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "task-log-drawer.css?v=" in resp.text
    assert "task-log-drawer.js?v=" in resp.text
    assert 'id="task-log-drawer"' in resp.text
    assert 'id="task-log-dock"' in resp.text
    assert "data-task-log-close" in resp.text


def test_base_layout_has_no_cdn_asset_urls(client):
    import re

    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    for needle in (
        "cdn.tailwindcss.com",
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "unpkg.com",
    ):
        assert needle not in body
    assert "/static/fonts.css?v=" in body
    assert "/static/tailwind.css?v=" in body
    assert "/static/vendor/htmx-1.9.12.min.js" in body
    assert re.search(r"/static/vendor/alpine-[^\"']+\.min\.js", body)


def test_vendored_web_assets_are_served(client):
    import re

    for path in (
        "/static/fonts.css",
        "/static/tailwind.css",
        "/static/vendor/htmx-1.9.12.min.js",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
    home = client.get("/").text
    match = re.search(r"/static/vendor/(alpine-[^\"']+\.min\.js)", home)
    assert match, "alpine vendor script not linked"
    assert client.get(f"/static/vendor/{match.group(1)}").status_code == 200
