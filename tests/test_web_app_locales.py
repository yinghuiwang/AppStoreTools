"""What's New / URLs reuse session locale checks until the App profile changes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"
ESBUILD = FRONTEND / "node_modules" / "esbuild" / "bin" / "esbuild"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def test_whats_new_and_urls_use_shared_app_locales_cache() -> None:
    composable = _read("composables/useAppLocales.ts")
    whats = _read("views/WhatsNewView.vue")
    urls = _read("views/UrlsView.vue")
    assert "export function useAppLocales" in composable
    assert "export function resetAppLocales" in composable
    assert "boundProfile" in composable
    assert 'httpJson<AppLocaleCheck>(ENDPOINTS[source])' in composable
    assert "pinia" not in composable.lower()
    assert "defineStore" not in composable
    assert "useAppLocales" in whats
    assert "useAppLocales" in urls
    assert 'useAppLocales("whats-new")' in whats
    assert 'useAppLocales("urls")' in urls
    assert "ensure()" in whats
    assert "ensure()" in urls
    assert "onActivated" in whats
    assert "onActivated" in urls
    assert "await refresh()" in whats
    assert "await refresh()" in urls
    assert '"/api/whats-new/check"' not in whats
    assert '"/api/urls/check"' not in urls


def test_manual_recheck_still_force_refreshes() -> None:
    whats = _read("views/WhatsNewView.vue")
    urls = _read("views/UrlsView.vue")
    assert "@click=\"loadCheck\"" in whats
    assert "@click=\"loadCheck\"" in urls
    assert "async function loadCheck" in whats
    assert "async function loadCheck" in urls
    assert "await refresh()" in whats
    assert "await refresh()" in urls


def test_app_locales_cache_survives_remount_until_profile_switch(tmp_path: Path) -> None:
    if not ESBUILD.exists():
        pytest.skip("frontend esbuild is not installed")

    http_mock = tmp_path / "http-mock.mjs"
    http_mock.write_text(
        """
export function httpJson(url) {
  globalThis.__httpCalls = globalThis.__httpCalls || [];
  globalThis.__httpCalls.push(url);
  return Promise.resolve(globalThis.__httpResult);
}
""",
        encoding="utf-8",
    )
    profile_mock = tmp_path / "profile-mock.mjs"
    profile_mock.write_text(
        """
export const snapshot = { value: { current_profile: "app-a" } };
export function useProfile() {
  return { snapshot };
}
globalThis.__profileSnapshot = snapshot;
""",
        encoding="utf-8",
    )
    bundled = tmp_path / "useAppLocales.mjs"
    bundled_run = subprocess.run(
        [
            str(ESBUILD),
            str(SRC / "composables" / "useAppLocales.ts"),
            "--bundle",
            "--platform=neutral",
            "--format=esm",
            f"--alias:@/api/http={http_mock}",
            f"--alias:@/composables/useProfile={profile_mock}",
            f"--outfile={bundled}",
        ],
        cwd=str(FRONTEND),
        capture_output=True,
        text=True,
    )
    assert bundled_run.returncode == 0, bundled_run.stdout + bundled_run.stderr

    runner = tmp_path / "run.mjs"
    runner.write_text(
        """
import { resetAppLocales, useAppLocales } from './useAppLocales.mjs';

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

globalThis.__httpCalls = [];
globalThis.__httpResult = {
  ok: true,
  message: "ready",
  detail: { version: "1.2.0", locales: ["en-US", "zh-Hans"] },
};

resetAppLocales();
const first = useAppLocales("whats-new");
first.ensure();
await first.check.value === null
  ? new Promise((resolve) => setTimeout(resolve, 0))
  : Promise.resolve();
await new Promise((resolve) => setTimeout(resolve, 0));

assert(globalThis.__httpCalls.length === 1, "first visit must fetch");
assert(globalThis.__httpCalls[0] === "/api/whats-new/check", "first fetch uses what's new check");
assert(first.check.value.detail.locales.join(",") === "en-US,zh-Hans", "locales stored");

globalThis.__httpCalls = [];
first.ensure();
useAppLocales("whats-new").ensure();
useAppLocales("urls").ensure();
await new Promise((resolve) => setTimeout(resolve, 0));
assert(globalThis.__httpCalls.length === 0, "re-enter and the other page must reuse locales");

await first.refresh();
assert(globalThis.__httpCalls.length === 1, "manual recheck must refetch");
assert(globalThis.__httpCalls[0] === "/api/whats-new/check", "what's new refresh hits its endpoint");

globalThis.__httpCalls = [];
const urls = useAppLocales("urls");
await urls.refresh();
assert(globalThis.__httpCalls.length === 1, "urls recheck must refetch");
assert(globalThis.__httpCalls[0] === "/api/urls/check", "urls refresh hits its endpoint");

globalThis.__httpCalls = [];
globalThis.__httpResult = {
  ok: true,
  message: "app-b ready",
  detail: { locales: ["ja"] },
};
globalThis.__profileSnapshot.value = { current_profile: "app-b" };
urls.ensure();
await new Promise((resolve) => setTimeout(resolve, 0));
assert(globalThis.__httpCalls.length === 1, "switching profile must refetch");
assert(urls.check.value.detail.locales.join(",") === "ja", "new profile locales replace cache");

console.log("ok");
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(runner)],
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout
