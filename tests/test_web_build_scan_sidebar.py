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
    assert 'value="reuse"' in src
    assert 'value="rebuild"' in src
    assert "build.reuse_auto" in src
    assert "build.reuse_rebuild" in src
    assert 'reuseArchive.value ? "true"' not in src
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
    # Old Jinja form posted the .mobileprovision path, not the display Name.
    assert ':value="item.path"' in src
    assert ':value="item.name"' not in src

    # Scheme / certificate / profile: empty state is "Please select", not Auto-detect.
    assert 'v-model="scheme" :placeholder="t(\'common.please_select\')"' in src
    assert 'v-model="certificate"' in src
    assert 'v-model="profileName"' in src
    assert ":placeholder=\"t('common.please_select')\"" in src
    assert "<t-option value=\"\" :label=\"t('build.auto_detect')\" />" not in src
    # Project path input still hints that empty means auto-detect.
    assert 'v-model="project" :placeholder="t(\'build.auto_detect\')"' in src

    # Start build/upload stays clickable; missing required fields toast on click.
    assert ':disabled="empty || optionsLoading"' not in src
    assert ':disabled="empty"' not in src
    assert "MessagePlugin" in src
    assert "nav.select_app" in src
    assert "build.need_ipa" in src
    assert "build.need_certificate" in src
    assert "build.need_profile" in src
    run = src.split("async function run()", 1)[1].split("\n}\n", 1)[0]
    assert "if (!scheme" not in run
    assert "if (!project" not in run
    assert 'mode.value === "deploy"' in run
    assert "ipaPath" in run
    assert 'signing.value === "manual"' in run
    assert "build.need_certificate" in run
    assert "build.need_profile" in run
    # Click-to-validate required selects/inputs get TDesign error status; scheme stays optional.
    assert "fieldErrors" in src
    assert "fieldStatus('certificate')" in src
    assert "fieldStatus('profile')" in src
    assert "fieldStatus('ipa')" in src
    assert "fieldErrors.certificate" in src
    assert "fieldErrors.profile" in src
    assert "fieldErrors.ipa" in src
    assert ':tips="fieldErrors.certificate || undefined"' in src
    assert ':tips="fieldErrors.profile || undefined"' in src
    assert ':tips="fieldErrors.ipa || undefined"' in src
    overrides = (ROOT / "frontend" / "src" / "styles" / "tdesign-overrides.css").read_text(encoding="utf-8")
    tips = overrides.split(".t-input__wrap > .t-input__tips", 1)[1].split("}", 1)[0]
    assert ".t-select-input > .t-input__tips" in overrides
    assert "position: static" in tips
    assert "position: absolute" not in tips
    assert "overflow: visible" in overrides
    scheme = src.split('v-model="scheme"', 1)[1].split("</t-select>", 1)[0]
    assert ":status" not in scheme
    assert "fieldStatus('scheme')" not in src
    assert "fieldErrors.scheme" not in src
