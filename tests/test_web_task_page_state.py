"""Task page phase/taskId survive unmount; keep-alive covers form fields."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"
ESBUILD = FRONTEND / "node_modules" / "esbuild" / "bin" / "esbuild"

TASK_VIEWS = (
    "views/BuildView.vue",
    "views/IapView.vue",
    "views/WhatsNewView.vue",
    "views/UrlsView.vue",
    "views/ListingView.vue",
)


def test_appshell_keep_alive_includes_task_pages():
    shell = (SRC / "layouts/AppShell.vue").read_text(encoding="utf-8")
    phase = (SRC / "composables/useTaskPagePhase.ts").read_text(encoding="utf-8")
    assert "<keep-alive" in shell
    assert "TASK_KEEP_ALIVE_NAMES" in shell
    assert "bindTaskPageProfile" in shell
    for name in ("ListingView", "WhatsNewView", "UrlsView", "BuildView", "IapView"):
        assert f'"{name}"' in phase
    assert "DashboardView" not in phase.split("TASK_KEEP_ALIVE_NAMES", 1)[1][:400]


def test_task_route_views_declare_keep_alive_names():
    for rel in TASK_VIEWS:
        src = (SRC / rel).read_text(encoding="utf-8")
        name = Path(rel).stem
        assert f'defineOptions({{ name: "{name}" }})' in src, rel


def test_listing_tab_is_module_scoped():
    listing = (SRC / "views/ListingView.vue").read_text(encoding="utf-8")
    assert "useListingTab" in listing
    assert "onActivated" in listing
    phase = (SRC / "composables/useTaskPagePhase.ts").read_text(encoding="utf-8")
    assert "export function useListingTab" in phase


def test_profile_switch_resets_task_pages():
    profile = (SRC / "composables/useProfile.ts").read_text(encoding="utf-8")
    assert "bindTaskPageProfile" in profile
    assert "switchProfile" in profile


def test_phase_and_task_id_survive_unmount(tmp_path: Path):
    if not ESBUILD.exists():
        pytest.skip("frontend esbuild is not installed")
    bundled = tmp_path / "taskPagePhase.mjs"
    bundled_run = subprocess.run(
        [
            str(ESBUILD),
            str(SRC / "composables/useTaskPagePhase.ts"),
            "--bundle",
            "--platform=neutral",
            "--format=esm",
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
import {
  bindTaskPageProfile,
  resetTaskPageState,
  useListingTab,
  useTaskPagePhase,
} from './taskPagePhase.mjs';

const mem = new Map();
globalThis.sessionStorage = {
  getItem: (key) => (mem.has(key) ? mem.get(key) : null),
  setItem: (key, value) => { mem.set(key, String(value)); },
  removeItem: (key) => { mem.delete(key); },
};

resetTaskPageState();
bindTaskPageProfile('app-a');

const first = useTaskPagePhase('build');
first.enterRun('task-1', { runMode: 'full' });
const { setListingTab } = useListingTab();
setListingTab('diff');

const afterUnmount = useTaskPagePhase('build');
if (afterUnmount.phase.value !== 'run') throw new Error('phase lost after unmount');
if (afterUnmount.taskId.value !== 'task-1') throw new Error('taskId lost after unmount');
if (afterUnmount.meta.value.runMode !== 'full') throw new Error('runMode lost after unmount');
if (afterUnmount.isRun.value !== true) throw new Error('isRun should stay true');

const other = useTaskPagePhase('iap');
if (other.phase.value !== 'form' || other.taskId.value) {
  throw new Error('pages must be isolated');
}

const listing = useListingTab();
if (listing.listingTab.value !== 'diff') throw new Error('listing tab lost after unmount');

bindTaskPageProfile('app-b');
if (afterUnmount.phase.value !== 'form' || afterUnmount.taskId.value !== '') {
  throw new Error('switching profile must reset phase/taskId');
}
if (listing.listingTab.value !== 'upload') {
  throw new Error('switching profile must reset listing tab');
}

console.log('ok');
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
