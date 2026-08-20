"""Vue task forms restore the pre-SPA localStorage keys after refresh."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SRC = FRONTEND / "src"
ESBUILD = FRONTEND / "node_modules" / "esbuild" / "bin" / "esbuild"


def test_form_memory_reuses_pre_vue_storage_keys():
    src = (SRC / "composables/useFormMemory.ts").read_text(encoding="utf-8")
    assert 'METADATA_FORM_KEY_PREFIX = "asc_metadata_form_"' in src
    assert 'BUILD_FORM_KEY_PREFIX = "asc_build_form_"' in src
    assert 'IAP_FORM_KEY_PREFIX = "asc_iap_form_"' in src
    assert 'IAP_DRAFT_KEY_PREFIX = "asc_iap_draft_"' in src
    assert "localStorage" in src
    assert "sessionStorage" in src
    assert "iapDraftKey" in src
    assert "pinia" not in src.lower()
    assert "defineStore" not in src


def test_listing_build_iap_views_wire_form_memory():
    upload = (SRC / "views/listing/UploadTab.vue").read_text(encoding="utf-8")
    local = (SRC / "views/listing/LocalTab.vue").read_text(encoding="utf-8")
    diff = (SRC / "views/listing/DiffTab.vue").read_text(encoding="utf-8")
    build = (SRC / "views/BuildView.vue").read_text(encoding="utf-8")
    iap = (SRC / "views/IapView.vue").read_text(encoding="utf-8")
    workflow = (SRC / "composables/useIapWorkflow.ts").read_text(encoding="utf-8")
    assert "hydrateListingForm" in upload
    assert "hydrateListingForm" in local
    assert "hydrateListingForm" in diff
    assert "BUILD_FORM_KEY_PREFIX" in build
    assert "restoreBuildMemory" in build
    assert "saveBuildMemory" in build
    assert "useIapWorkflow" in iap
    assert "IAP_FORM_KEY_PREFIX" in workflow
    assert "IAP_DRAFT_KEY_PREFIX" in (SRC / "composables/useFormMemory.ts").read_text(encoding="utf-8")
    assert "persistMemory" in workflow
    assert "storeDraft" in workflow
    assert "iapDraftKey" in workflow
    create = (SRC / "views/iap/CreateStep.vue").read_text(encoding="utf-8")
    assert "jsonPath" in create
    assert "setIapFile" in create
    assert "hasFile" in create
    assert 'source.value = "json"' in create
    assert 'v-model="source"' in create
    assert 'destroy-on-hide="false"' in create


def test_form_memory_roundtrip_uses_old_keys(tmp_path: Path):
    if not ESBUILD.exists():
        pytest.skip("frontend esbuild is not installed")
    bundled = tmp_path / "formMemory.mjs"
    bundled_run = subprocess.run(
        [
            str(ESBUILD),
            str(SRC / "composables/useFormMemory.ts"),
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
  BUILD_FORM_KEY_PREFIX,
  IAP_FORM_KEY_PREFIX,
  METADATA_FORM_KEY_PREFIX,
  applyListingStored,
  buildFormPayload,
  formMemoryKey,
  hydrateListingForm,
  iapFormPayload,
  parseBuildStored,
  parseIapStored,
  readFormMemory,
  resetFormMemory,
  writeFormMemory,
} from './formMemory.mjs';

const mem = new Map();
globalThis.localStorage = {
  getItem: (key) => (mem.has(key) ? mem.get(key) : null),
  setItem: (key, value) => { mem.set(key, String(value)); },
  removeItem: (key) => { mem.delete(key); },
};

const listingKey = formMemoryKey(METADATA_FORM_KEY_PREFIX, 'myapp');
if (listingKey !== 'asc_metadata_form_myapp') throw new Error('listing key drifted: ' + listingKey);
const buildKey = formMemoryKey(BUILD_FORM_KEY_PREFIX, 'myapp');
if (buildKey !== 'asc_build_form_myapp') throw new Error('build key drifted: ' + buildKey);
const iapKey = formMemoryKey(IAP_FORM_KEY_PREFIX, 'myapp');
if (iapKey !== 'asc_iap_form_myapp') throw new Error('iap key drifted: ' + iapKey);

localStorage.setItem(listingKey, JSON.stringify({
  csv_path: 'custom/appstore_info.csv',
  screenshots_dir: 'custom/shots',
  include_metadata: false,
  include_screenshots: true,
  dry_run: true,
}));

resetFormMemory();
const listing = hydrateListingForm('myapp', {
  csv: 'data/appstore_info.csv',
  screenshots: 'data/screenshots',
});
if (listing.csv_path.value !== 'custom/appstore_info.csv') throw new Error('listing csv not restored');
if (listing.screenshots_dir.value !== 'custom/shots') throw new Error('listing shots not restored');
if (listing.include_metadata.value !== false) throw new Error('listing include_metadata not restored');
if (listing.include_screenshots.value !== true) throw new Error('listing include_screenshots not restored');
if (listing.dry_run.value !== true) throw new Error('listing dry_run not restored');

listing.csv_path.value = 'other/info.csv';
listing.include_metadata.value = true;
const savedListing = readFormMemory(listingKey);
if (savedListing.csv_path !== 'other/info.csv') throw new Error('listing csv not persisted');
if (savedListing.include_metadata !== true) throw new Error('listing checkbox not persisted');

const applied = applyListingStored(
  { include_metadata: false, include_screenshots: false, dry_run: false },
  {
    csv_path: 'data/appstore_info.csv',
    screenshots_dir: 'data/screenshots',
    include_metadata: true,
    include_screenshots: true,
    dry_run: false,
    verbose: false,
  },
);
if (applied.include_metadata !== false || applied.include_screenshots !== false) {
  throw new Error('listing checkboxes must follow stored values');
}

localStorage.setItem(buildKey, JSON.stringify({
  mode: 'deploy',
  project: '/tmp/App.xcodeproj',
  scheme: 'App',
  destination: 'appstore',
  signing: 'manual',
  certificate: 'Apple Distribution',
  provisioning_profile: '/tmp/app.mobileprovision',
  reuse_archive: 'reuse',
  ipa_path: '/tmp/App.ipa',
  verbose: true,
  dry_run: true,
}));
const build = parseBuildStored(readFormMemory(buildKey));
if (build.mode !== 'deploy') throw new Error('build mode not restored');
if (build.project !== '/tmp/App.xcodeproj') throw new Error('build project not restored');
if (build.reuse_archive !== 'reuse') throw new Error('build reuse_archive not restored');
if (build.verbose !== true || build.dry_run !== true) throw new Error('build flags not restored');
writeFormMemory(buildKey, buildFormPayload({
  mode: 'build',
  project: '/tmp/App.xcodeproj',
  scheme: 'App',
  destination: 'testflight',
  signing: 'auto',
  certificate: '',
  provisioning_profile: '',
  reuse_archive: '',
  ipa_path: '',
  verbose: false,
  dry_run: false,
}));
const buildSaved = parseBuildStored(readFormMemory(buildKey));
if (buildSaved.mode !== 'build') throw new Error('build mode not persisted');
if (buildSaved.reuse_archive !== '') throw new Error('build reuse_archive should clear');

localStorage.setItem(iapKey, JSON.stringify({
  iap_file: 'data/custom_iap.json',
  include_items: true,
  include_groups: false,
  dry_run: true,
  update_existing: true,
}));
const iap = parseIapStored(readFormMemory(iapKey));
if (iap.iap_file !== 'data/custom_iap.json') throw new Error('iap file not restored');
if (iap.dry_run !== true || iap.update_existing !== true) throw new Error('iap flags not restored');
writeFormMemory(iapKey, iapFormPayload({
  iap_file: 'data/custom_iap.json',
  dry_run: false,
  update_existing: true,
  verbose: true,
}));
const iapSaved = readFormMemory(iapKey);
if (iapSaved.include_items !== true) throw new Error('iap write must keep legacy include_items');
if (iapSaved.verbose !== true) throw new Error('iap verbose not persisted');
if (iapSaved.dry_run !== false) throw new Error('iap dry_run not persisted');

resetFormMemory();
const other = hydrateListingForm('otherapp', {
  csv: 'data/appstore_info.csv',
  screenshots: 'data/screenshots',
});
if (other.csv_path.value !== 'data/appstore_info.csv') {
  throw new Error('other profile must not inherit myapp listing memory');
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


def test_iap_draft_storage_key_and_roundtrip(tmp_path: Path):
    if not ESBUILD.exists():
        pytest.skip("frontend esbuild is not installed")
    bundled = tmp_path / "formMemory.mjs"
    bundled_run = subprocess.run(
        [
            str(ESBUILD),
            str(SRC / "composables/useFormMemory.ts"),
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
    runner = tmp_path / "run_draft.mjs"
    runner.write_text(
        """
import {
  IAP_DRAFT_KEY_PREFIX,
  clearIapDraft,
  iapDraftKey,
  iapDraftPayload,
  parseIapDraft,
  readIapDraft,
  writeIapDraft,
} from './formMemory.mjs';

const mem = new Map();
globalThis.sessionStorage = {
  getItem: (key) => (mem.has(key) ? mem.get(key) : null),
  setItem: (key, value) => { mem.set(key, String(value)); },
  removeItem: (key) => { mem.delete(key); },
};

const key = iapDraftKey('myapp', 'data/iap_packages.json');
if (key !== 'asc_iap_draft_myapp:data/iap_packages.json') {
  throw new Error('iap draft key drifted: ' + key);
}
if (!key.startsWith(IAP_DRAFT_KEY_PREFIX)) throw new Error('prefix missing');

const snapshot = {
  items: [{ productId: 'com.app.coins', inAppPurchaseType: 'CONSUMABLE' }],
  subscriptionGroups: [],
};
writeIapDraft(key, iapDraftPayload({
  iap_file: 'data/iap_packages.json',
  snapshot,
  store_draft: true,
}));
const stored = parseIapDraft(readIapDraft(key));
if (stored.iap_file !== 'data/iap_packages.json') throw new Error('draft iap_file not restored');
if (stored.store_draft !== true) throw new Error('store_draft not restored');
if (stored.snapshot.items[0].productId !== 'com.app.coins') throw new Error('draft snapshot not restored');

const other = iapDraftKey('otherapp', 'data/iap_packages.json');
if (readIapDraft(other)) throw new Error('other profile must not see myapp draft');

clearIapDraft(key);
if (readIapDraft(key)) throw new Error('draft should clear');

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
