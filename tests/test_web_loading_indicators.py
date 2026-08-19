"""Ensure PageLoading and button :loading are not stacked for the same intent."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"


def _read(rel: str) -> str:
    return (FRONTEND / rel).read_text(encoding="utf-8")


def test_urls_first_check_uses_page_loading_without_button_spinner():
    src = _read("views/UrlsView.vue")
    assert 'PageLoading v-if="checking && !check"' in src
    assert ':loading="checking && !!check"' in src
    assert ':disabled="checking && !check"' in src
    assert ':loading="checking"' not in src.replace(':loading="checking && !!check"', "")


def test_whats_new_avoids_duplicate_check_spinners():
    src = _read("views/WhatsNewView.vue")
    assert "PageLoading v-else-if=\"checking\"" in src
    assert ':loading="checking && !!check"' in src
    assert src.count("<PageLoading") == 1


def test_whats_new_translate_mode_is_workflow_block_not_under_check():
    src = _read("views/WhatsNewView.vue")
    start = src.find("<template>")
    end = src.rfind("</template>")
    template = src[start:end]
    check_pos = template.find('class="field-row check-row"')
    mode_pos = template.find('class="mode-block"')
    translate_pos = template.find('v-model="translateMode"')
    source_pos = template.find('whats_new.source_lang')
    text_pos = template.find('whats_new.text')
    preview_pos = template.find('whats_new.preview_translate')
    upload_pos = template.find('whats_new.translate_upload')
    direct_pos = template.find('whats_new.upload_direct')
    between_check_and_mode = template[check_pos:mode_pos]
    assert check_pos != -1 and mode_pos != -1
    assert between_check_and_mode.count("</div>") >= 2
    assert "translateMode" not in between_check_and_mode
    assert mode_pos < translate_pos < source_pos < text_pos
    assert 'v-if="translateMode"' in template
    assert 'v-if="isForm && translateMode && Object.keys(translations).length"' in template
    assert preview_pos > source_pos
    assert preview_pos != -1 and upload_pos != -1 and direct_pos != -1
    assert preview_pos < upload_pos
    assert "runTranslateAndUpload" in src
    assert "translate: true" in src


def test_iap_check_and_scan_use_single_indicator_each():
    src = _read("views/IapView.vue")
    assert 'PageLoading v-if="checking && !checkMsg"' in src
    assert ':loading="checking && !!checkMsg"' in src
    assert ':loading="scanning"' in src
    assert 'PageLoading v-if="scanning"' not in src
    assert ".png,.jpg,.jpeg" in src


def test_listing_tabs_block_first_load_without_button_spinner():
    local = _read("views/listing/LocalTab.vue")
    diff = _read("views/listing/DiffTab.vue")
    assert 'PageLoading v-if="listingTab === \'local\' && loading && !loaded"' in local
    assert 'size="page"' in local
    assert ':loading="loading && loaded"' in local
    assert 'PageLoading v-if="listingTab === \'diff\' && loading && !loaded"' in diff
    assert 'size="page"' in diff
    assert ':loading="loading && loaded"' in diff


def test_listing_hidden_tabs_do_not_fetch_until_selected():
    local = _read("views/listing/LocalTab.vue")
    diff = _read("views/listing/DiffTab.vue")
    assert "useListingTab" in local
    assert 'tab === "local"' in local
    assert "onMounted(() => { if (!empty.value) void load(); })" not in local
    assert "useListingTab" in diff
    assert 'tab !== "diff"' in diff
    assert "!loaded.value && !loading.value" in diff
    assert "onMounted(() => { void load(); })" not in diff


def test_locale_picker_refresh_uses_button_only_when_rows_exist():
    src = _read("views/listing/LocalePicker.vue")
    assert 'PageLoading v-if="loading && !rows.length"' in src
    assert ':loading="loading && rows.length > 0"' in src
    assert 'PageLoading v-if="loading && rows.length"' not in src


def test_update_tab_first_check_prefers_page_loading():
    src = _read("views/system/UpdateTab.vue")
    assert 'PageLoading v-if="checking && !checkResult"' in src
    assert ':loading="checking && !!checkResult"' in src


def test_dashboard_refresh_uses_status_text_not_second_spinner():
    src = _read("views/DashboardView.vue")
    assert src.count("<PageLoading") == 1
    assert 'v-if="loading && !summary"' in src
    assert 'size="page"' in src
    assert "dashboard.refreshing" not in src
    assert "PageLoading v-if=\"refreshing\"" not in src
    assert 'size="inline"' not in src
    assert "refreshError" in src
    assert "onActivated" in src
    assert "onDeactivated" in src


def test_build_refresh_prefers_button_after_first_scan():
    src = _read("views/BuildView.vue")
    assert "scannedOnce" in src
    assert ':loading="optionsLoading && scannedOnce"' in src
    assert 'PageLoading v-if="optionsLoading && !scannedOnce"' in src
    assert "if (scannedOnce.value) return" in src


def test_page_loading_stays_in_route_so_leave_hides_it():
    src = _read("components/PageLoading.vue")
    assert 'size === \'page\'' in src or 'size === "page"' in src
    assert "/static/logo.svg" in src
    assert "LoadingIcon" in src
    assert "common.loading" in src
    assert "Teleport" not in src
    assert "position: fixed" not in src
    assert "position: absolute" not in src
    assert "100vw" not in src
    assert "justify-content: center" in src
    assert "align-items: center" in src
    assert "flex-direction: column" in src
    assert "page-loading__logo" in src
    assert "keep-alive" in src.lower() or "in-route" in src or "in-tree" in src


def test_spa_boot_is_pre_mount_only():
    main = _read("main.ts")
    router = _read("router/index.ts")
    tokens = _read("styles/tokens.css")
    assert "renderBootLoading" in main
    assert "spa.booting" in main
    assert "clearBootChrome" in main
    assert "spaMounted" in main
    assert "/static/logo.svg" in main
    assert "spa-boot__stack" in main
    assert "app.mount" in main
    mount_at = main.find("app.mount")
    assert mount_at != -1
    assert main.find("clearBootChrome(root)", mount_at) != -1
    assert "beforeEach" not in router
    assert "spa-boot" not in router
    assert "PageLoading" not in _read("layouts/AppShell.vue")
    assert "PageLoading" not in _read("App.vue")
    assert "spa-boot__logo" in tokens
    boot = tokens[tokens.find(".spa-boot {") : tokens.find(".spa-boot__stack")]
    assert "position: fixed" in boot
    assert "inset: 0" in boot
    assert "flex-direction: column" in boot
    assert "justify-content: center" in boot
    assert "#app.spa-boot" in tokens


def test_system_pages_do_not_cover_existing_content_on_refresh():
    profiles = _read("views/system/ProfilesTab.vue")
    guard = _read("views/system/GuardTab.vue")
    settings = _read("views/system/SettingsTab.vue")
    update = _read("views/system/UpdateTab.vue")
    assert 'PageLoading v-if="loading && !loaded"' in profiles
    assert 'size="page"' in profiles
    assert 'PageLoading v-if="loading"' not in profiles.replace(
        'PageLoading v-if="loading && !loaded"', ""
    )
    assert 'PageLoading v-if="loading && !loaded"' in guard
    assert 'size="page"' in guard
    assert 'PageLoading v-if="loading && !loaded"' in settings
    assert settings.count('PageLoading v-if="loading && !loaded"') == 1
    assert 'size="page"' in settings
    assert 'PageLoading v-if="versionsLoading && !versions.length"' in update
    assert 'PageLoading v-if="branchesLoading && !branches.length"' in update
    assert 'PageLoading v-if="versionsLoading"' not in update.replace(
        'PageLoading v-if="versionsLoading && !versions.length"', ""
    )
