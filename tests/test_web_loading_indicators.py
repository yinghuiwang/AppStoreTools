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


def test_build_refresh_prefers_button_after_first_scan():
    src = _read("views/BuildView.vue")
    assert "scannedOnce" in src
    assert ':loading="optionsLoading && scannedOnce"' in src
    assert 'PageLoading v-if="optionsLoading && !scannedOnce"' in src
