"""Build page restores the auto-detect / env-scan sidebar beside the form."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "frontend" / "src" / "views" / "BuildView.vue"


def test_build_view_restores_env_scan_sidebar():
    src = VIEW.read_text(encoding="utf-8")

    assert "build.scan_title" in src
    assert "build.refresh" in src
    assert "/api/build/options" in src
    assert "build.scheme_candidates" in src
    assert "build.cert_candidates" in src
    assert "build.profile_candidates" in src
    assert "build.archive_reuse" in src
    assert "bundle_id_selected" in src
    assert "archive_match" in src
    assert "version_info" in src

    # Form + scan share the form phase; run phase hides both with the form.
    assert 'v-if="isForm"' in src
    assert "build-layout" in src or "build-scan" in src
    assert 'mode !== "deploy"' in src or "mode !== 'deploy'" in src
    assert "align-items: stretch" in src
    assert "overflow: auto" not in src
    assert "max-height" not in src

    # Local scan spinner — not a whole-page gate on first paint.
    assert "optionsLoading && !optionsReady" not in src
    assert 'size="inline"' in src or "PageLoading" in src

    # Refresh / scan status messaging from the old right panel.
    assert "build.scanning" in src or "scanStatus" in src
    assert "build.scan_hint" in src
    assert "build.step_detect" in src
