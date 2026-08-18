from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from asc.web.server import create_app

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"


@pytest.fixture
def spa_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    index = tmp_path / "index.html"
    index.write_text(
        '<html><script src="/static/spa/assets/app.js"></script></html>',
        encoding="utf-8",
    )
    monkeypatch.setattr("asc.web.server.SPA_INDEX", index)
    return TestClient(create_app())


@pytest.mark.parametrize(
    "path",
    [
        "/profiles",
        "/guard",
        "/settings",
        "/update",
        "/system",
        "/system/profiles",
        "/system/guard",
        "/system/settings",
        "/system/update",
        "/system?tab=guard",
    ],
)
def test_system_pages_return_spa(spa_client: TestClient, path: str) -> None:
    resp = spa_client.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert 'src="/static/spa/' in resp.text


def test_system_router_uses_flat_pages_like_listing() -> None:
    src = (FRONTEND / "router" / "index.ts").read_text(encoding="utf-8")
    for path in ('"/profiles"', '"/guard"', '"/settings"', '"/update"'):
        assert f"path: {path}" in src
        assert f"redirect: {path}" not in src
    assert 'path: "/listing"' in src
    assert 'path: "/whats-new"' in src
    assert 'path: "/urls"' in src
    assert 'path: "/system"' in src
    assert "redirect: redirectSystemRoot" in src
    assert "redirect: redirectSystemTab" in src
    assert "to.query" in src
    assert "to.hash" in src
    assert "SystemView" not in src
    assert 'component: SystemView' not in src


def test_system_views_reuse_existing_tabs() -> None:
    mapping = {
        "ProfilesView.vue": "ProfilesTab",
        "GuardView.vue": "GuardTab",
        "SettingsView.vue": "SettingsTab",
        "UpdateView.vue": "UpdateTab",
    }
    for view, tab in mapping.items():
        src = (FRONTEND / "views" / view).read_text(encoding="utf-8")
        assert tab in src
        assert "el-tabs" not in src
        assert "el-tab-pane" not in src


def test_system_sidebar_has_independent_links() -> None:
    src = (FRONTEND / "components" / "AppSidebar.vue").read_text(encoding="utf-8")
    assert 'labelKey: "nav.group.system"' in src
    assert 'to: "/profiles"' in src
    assert 'to: "/guard"' in src
    assert 'to: "/settings"' in src
    assert 'to: "/update"' in src
    assert 'labelKey: "nav.profiles"' in src
    assert 'labelKey: "nav.guard"' in src
    assert 'labelKey: "nav.settings"' in src
    assert 'labelKey: "nav.update"' in src
    assert 'to: "/listing"' in src
    assert 'to: "/whats-new"' in src
    assert 'to: "/urls"' in src
    assert "/system/profiles" not in src
    assert 'labelKey: "nav.system"' not in src


def test_update_tab_keeps_status_in_check_card() -> None:
    src = (FRONTEND / "views" / "system" / "UpdateTab.vue").read_text(encoding="utf-8")
    assert "checkResult.message" in src
    assert 't("update.found")' in src
    assert 't("update.install_now")' in src
    assert 't("update.up_to_date")' not in src
    assert 't("update.badge_latest")' in src
    assert 't("update.current_short")' in src
    assert "version-num" in src
    assert "badge-latest" in src
    assert 't("update.current_version"' not in src
    assert 'class="page-stack"' in src
    assert 'class="form-stack"' in src
    assert src.count('class="page-stack"') == 1
    assert "dryRun" not in src
    assert 't("common.dry_run")' not in src
    assert "verbose" in src
    assert 't("build.verbose")' in src
    assert 't("update.open_github")' in src
    assert "https://github.com/yinghuiwang/AppStoreTools" in src
    assert 'target="_blank"' in src
    assert 'rel="noopener"' in src


def test_guard_tab_restores_old_information_architecture() -> None:
    src = (FRONTEND / "views" / "system" / "GuardTab.vue").read_text(encoding="utf-8")
    assert "el-table" not in src
    assert "el-table-column" not in src
    assert "rebuildAppRows" in src
    assert "app_notes" in src
    assert "current_profile" in src
    assert 't("guard.current_env")' in src
    assert 't("guard.bindings")' in src
    assert 't("guard.ip_address")' in src
    assert 't("guard.machine")' in src
    assert 't("guard.ip")' in src
    assert 't("guard.credential")' in src
    assert 'appendValue(ensure(info), "credential"' in src
    assert 'v-if="row.credential"' in src
    assert 'v-if="row.machine"' in src
    assert 'v-if="row.ip"' in src
    assert 'class="detail-grid"' in src
    assert ":key=\"row.app_id || row.profile_name\"" not in src
    assert 't("guard.app_id")' in src
    assert 't("guard.manual_add")' in src
    assert 't("guard.save_note")' in src
    assert 't("guard.help1")' in src
    assert 't("guard.help2")' in src
    assert "asc guard enable/disable/unbind" in src
    assert src.find('t("guard.current_env")') < src.find('t("guard.bindings")')
    assert src.find('t("guard.bindings")') < src.find('t("guard.help1")')
    assert src.find('t("guard.enabled")') < src.find('t("guard.current_env")')
    assert ":label=\"t('guard.machine')\"" not in src
    from asc.web.i18n import load_catalog, t
    load_catalog.cache_clear()
    assert t("guard.credential", lang="zh") == "凭证 Key ID"
    assert t("guard.credential", lang="en") == "Credential key ID"
    assert t("guard.app_id", lang="en") == "App ID"
    assert "<t-dialog" in src
    assert "dialog-form" in src
    assert src.find('class="page-stack"') < src.find("<t-dialog")


def test_guard_tab_lists_every_binding_not_just_current() -> None:
    """Binding details must render every machine/ip/credential, not only current."""
    src = (FRONTEND / "views" / "system" / "GuardTab.vue").read_text(encoding="utf-8")
    rebuild = src[src.find("function rebuildAppRows") : src.find("function appLabel")]
    assert "function rebuildAppRows" in rebuild
    assert ".filter(" not in rebuild
    assert "current_environment" not in rebuild
    assert 'appendValue(ensure(info), "machine"' in rebuild
    assert 'appendValue(ensure(info), "ip"' in rebuild
    assert 'appendValue(ensure(info), "credential"' in rebuild
    assert "bindings.machine" in rebuild
    assert "bindings.ip" in rebuild
    assert "bindings.credential" in rebuild
    assert "{{ row.machine }}" in src
    assert "{{ row.ip }}" in src
    assert "{{ row.credential }}" in src
    assert 'v-if="row.machine"' in src
    assert 'v-if="row.ip"' in src
    assert 'v-if="row.credential"' in src
    assert "isCurrentApp" in src
    assert ":key=\"row.app_id || row.profile_name\"" not in src
    assert "cardKey" in src


def test_profiles_tab_uses_full_width_wrapping_cards() -> None:
    src = (FRONTEND / "views" / "system" / "ProfilesTab.vue").read_text(encoding="utf-8")
    assert "el-table" not in src
    assert "el-table-column" not in src
    assert 'class="profiles-table"' not in src
    assert "table-layout: fixed" not in src
    assert "text-overflow: ellipsis" not in src
    assert "white-space: nowrap" not in src
    assert 'class="profile-list"' in src
    assert 'class="profile-card"' in src
    assert 'class="profile-meta"' in src
    assert "overflow-wrap: anywhere" in src
    assert 'class="badge"' in src
    assert 't("common.default")' in src
    assert 'v-if="!row.isDefault"' in src
    assert "profiles-page" in src
    assert "max-width: none" in src
    assert "<t-dialog" in src
    assert src.find("profiles-page") < src.find("<t-dialog")
    assert "dialog-form" in src
    assert "importCandidates" in src
    assert "profiles.import_hint" in src
    assert "profiles.import_skip" in src
    assert "importSetDefault" in src
    assert "candidates[0]" not in src or "importName.value = candidates[0]" in src


def test_retry_paths_map_legacy_system_tabs() -> None:
    types_src = (FRONTEND / "api" / "types.ts").read_text(encoding="utf-8")
    assert '"/system/update": "/update"' in types_src
    assert '"/system/profiles": "/profiles"' in types_src
    dash = (FRONTEND / "views" / "DashboardView.vue").read_text(encoding="utf-8")
    assert '"/update"' in dash
    assert "/system/update" not in dash


def test_dashboard_restores_workspace_capabilities() -> None:
    dash = (FRONTEND / "views" / "DashboardView.vue").read_text(encoding="utf-8")
    assert "showNoApp" not in dash
    assert "/api/dashboard/summary" in dash
    assert 'range: range.value' in dash or 'range: range.value, profile:' in dash
    assert 't("index.range_7d")' in dash or "index.range_${item}" in dash
    assert 't("index.all_apps")' in dash
    assert 't("index.all_statuses")' in dash
    assert 't("index.all_kinds")' in dash
    assert 't("index.metric_saved")' in dash
    assert 't("index.metric_success")' in dash
    assert 't("index.running_title")' in dash
    assert 't("index.history_title")' in dash
    assert "rail.openLogs" in dash
    assert "/api/task/" in dash and "/cancel" in dash
    assert "openAgent" in dash
    assert "retryTo" in dash
    assert '"/listing?tab=upload"' in dash
    assert 'tab: "upload"' in dash
    assert 'action: "check"' in dash
    assert 'action: "all"' in dash
    assert 'action: "metadata"' in dash
    assert 'action: "screenshots"' in dash
    assert 'action: "build-upload"' in dash
    assert 'path: "/listing"' in dash
    assert 'path: "/build"' in dash
    assert "schedulePoll" in dash
    assert "dashboard.refresh_failed" in dash
    assert "dashboard.refreshing" not in dash
    assert "dashboard.canceling" in dash
    assert "align-items: stretch" in dash
    assert "dash-toolbar" in dash
    assert "dash-split" in dash
    assert "minmax(0, 1.15fr) minmax(0, 1fr)" in dash
    assert "overflow: auto" not in dash
    assert "flex: 1.35 1 0" not in dash
    assert "min-height: 0" not in dash


def test_page_modules_grow_and_main_column_scrolls() -> None:
    shell = (FRONTEND / "layouts" / "AppShell.vue").read_text(encoding="utf-8")
    tokens = (FRONTEND / "styles" / "tokens.css").read_text(encoding="utf-8")
    listing = (FRONTEND / "views" / "ListingView.vue").read_text(encoding="utf-8")
    local = (FRONTEND / "views" / "listing" / "LocalTab.vue").read_text(encoding="utf-8")
    diff = (FRONTEND / "views" / "listing" / "DiffTab.vue").read_text(encoding="utf-8")
    build = (FRONTEND / "views" / "BuildView.vue").read_text(encoding="utf-8")
    run = (FRONTEND / "components" / "TaskRunBar.vue").read_text(encoding="utf-8")
    logs = (FRONTEND / "components" / "TaskLogPanel.vue").read_text(encoding="utf-8")
    agent = (FRONTEND / "components" / "AgentPanel.vue").read_text(encoding="utf-8")

    assert ".shell-main" in shell
    assert "overflow: auto" in shell
    assert ".page-stack > :last-child" in tokens
    assert ".page-stack > :last-child.card" in tokens
    assert ":is(button, .t-button)" in tokens
    assert "flex: 0 0 auto" in tokens
    assert "listing-tabs" in listing
    assert "overflow: visible" in listing
    assert "overflow: auto" not in local
    assert "overflow: auto" not in diff
    assert "overflow: auto" not in build
    assert "align-items: stretch" in build
    assert "flex: 1 1 auto" in run
    assert "overflow: auto" in logs
    assert "overflow: auto" in agent
