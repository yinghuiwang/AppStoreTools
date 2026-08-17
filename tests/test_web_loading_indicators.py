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
    template = src.split("<template>", 1)[1].split("</template>", 1)[0]
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


def test_listing_tabs_block_first_load_without_button_spinner():
    local = _read("views/listing/LocalTab.vue")
    diff = _read("views/listing/DiffTab.vue")
    assert 'PageLoading v-if="loading && !loaded"' in local
    assert ':loading="loading && loaded"' in local
    assert 'PageLoading v-if="loading && !loaded"' in diff
    assert ':loading="loading && loaded"' in diff


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
    assert "dashboard.refreshing" in src
    assert "PageLoading v-if=\"refreshing\"" not in src
    assert 'size="inline"' not in src


def test_build_refresh_prefers_button_after_first_scan():
    src = _read("views/BuildView.vue")
    assert "scannedOnce" in src
    assert ':loading="optionsLoading && scannedOnce"' in src
    assert 'PageLoading v-if="optionsLoading && !scannedOnce"' in src
