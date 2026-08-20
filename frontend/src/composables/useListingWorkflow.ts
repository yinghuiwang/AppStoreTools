import { computed, ref } from "vue";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import {
  METADATA_FORM_KEY_PREFIX,
  clearIapDraft,
  formMemoryKey,
  listingDraftKey,
  listingDraftPayload,
  listingFormPayload,
  parseListingDraft,
  readFormMemory,
  readIapDraft,
  writeFormMemory,
  writeIapDraft,
} from "@/composables/useFormMemory";
import { rememberFormPath } from "@/composables/useFormPaths";
import { LISTING_FIELDS, useListingScope, type ListingLocaleRow } from "@/composables/useListingScope";
import { useProfile } from "@/composables/useProfile";
import { useTaskLog } from "@/composables/useTaskLog";

export type ListingShot = {
  file_name: string;
  order: number;
  thumb_url: string;
  local_path: string;
  remote_id: string;
};

export type ListingLocale = {
  locale: string;
  fields: Record<string, string>;
  screenshots: Record<string, ListingShot[]>;
};

export type ListingSnapshot = {
  locales: ListingLocale[];
  version?: { versionString?: string; appStoreState?: string } | null;
};

export type ListingFieldDiff = { field: string; status: string; local: string; asc: string };
export type ListingPlanLocale = {
  locale: string;
  status: string;
  missingScreenshots?: boolean;
  fields: ListingFieldDiff[];
};

function emptyFields(): Record<string, string> {
  return Object.fromEntries(LISTING_FIELDS.map((field) => [field, ""]));
}

function emptySnapshot(): ListingSnapshot {
  return { locales: [] };
}

function blankLocale(locale: string): ListingLocale {
  return { locale, fields: emptyFields(), screenshots: {} };
}

function cloneSnapshot(value: ListingSnapshot | null | undefined): ListingSnapshot {
  const raw = value || emptySnapshot();
  return JSON.parse(JSON.stringify({
    locales: Array.isArray(raw.locales) ? raw.locales : [],
    version: raw.version || null,
  })) as ListingSnapshot;
}

function textOnlySnapshot(value: ListingSnapshot): ListingSnapshot {
  return {
    locales: (value.locales || []).map((row) => ({
      locale: row.locale,
      fields: { ...emptyFields(), ...(row.fields || {}) },
      screenshots: {},
    })),
  };
}

function mergeDiskShots(text: ListingSnapshot, disk: ListingSnapshot): ListingSnapshot {
  const shots: Record<string, Record<string, ListingShot[]>> = {};
  for (const row of disk.locales || []) shots[row.locale] = row.screenshots || {};
  return {
    locales: (text.locales || []).map((row) => ({
      locale: row.locale,
      fields: { ...emptyFields(), ...(row.fields || {}) },
      screenshots: shots[row.locale] || row.screenshots || {},
    })),
    version: text.version || disk.version || null,
  };
}

function hasContent(value: ListingSnapshot | null | undefined): boolean {
  return (value?.locales?.length || 0) > 0;
}

const csvPath = ref("data/appstore_info.csv");
const screenshotsDir = ref("data/screenshots");
const snapshot = ref<ListingSnapshot>(emptySnapshot());
const mtime = ref<number | null>(null);
const dirty = ref(false);
const storeDraft = ref(false);
const exists = ref(false);
const loaded = ref(false);
const loading = ref(false);
const saving = ref(false);
const alert = ref("");
const conflict = ref(false);
const selectedLocale = ref("");
let boundProfile: string | undefined;
let hydrating = false;

const dryRun = ref(false);
const verbose = ref(false);
const includeMetadata = ref(true);
const includeScreenshots = ref(true);
const autoTranslate = ref(true);

export type CompareResult = {
  ok?: boolean;
  error?: string;
  version?: { versionString?: string; appStoreState?: string } | null;
  locales?: ListingPlanLocale[];
};

const planLocales = ref<ListingPlanLocale[]>([]);
const planVersion = ref<{ versionString?: string; appStoreState?: string } | null>(null);
const planError = ref("");
const planOk = ref(true);
const planLoading = ref(false);
const planLoadedKey = ref("");
const compareTaskId = ref("");
const compareStartedAt = ref(0);
let compareInFlight: { key: string; promise: Promise<void> } | null = null;
let compareGen = 0;

function persistMemory() {
  if (hydrating || boundProfile === undefined) return;
  writeFormMemory(
    formMemoryKey(METADATA_FORM_KEY_PREFIX, boundProfile),
    listingFormPayload({
      csv_path: csvPath.value,
      screenshots_dir: screenshotsDir.value,
      include_metadata: includeMetadata.value,
      include_screenshots: includeScreenshots.value,
      dry_run: dryRun.value,
      verbose: verbose.value,
      auto_translate: autoTranslate.value,
    }),
  );
}

function currentDraftKey(): string | null {
  if (boundProfile === undefined) return null;
  return listingDraftKey(boundProfile, csvPath.value);
}

function persistDraft() {
  if (hydrating || boundProfile === undefined || !storeDraft.value) return;
  const key = currentDraftKey();
  if (!key) return;
  writeIapDraft(
    key,
    listingDraftPayload({
      csv_path: csvPath.value,
      snapshot: textOnlySnapshot(snapshot.value),
      store_draft: true,
    }),
  );
}

function restoreDraft(disk: ListingSnapshot): boolean {
  if (boundProfile === undefined) return false;
  const key = currentDraftKey();
  if (!key) return false;
  const stored = parseListingDraft(readIapDraft(key));
  if (!stored?.snapshot) return false;
  const draft = cloneSnapshot(stored.snapshot as ListingSnapshot);
  snapshot.value = mergeDiskShots(draft, disk);
  dirty.value = true;
  storeDraft.value = stored.store_draft !== false;
  loaded.value = true;
  return true;
}

function dropDraft() {
  const key = currentDraftKey();
  if (key) clearIapDraft(key);
  storeDraft.value = false;
}

async function waitForTask(taskId: string): Promise<{ status: string; result?: CompareResult }> {
  for (;;) {
    const state = await httpJson<{ status: string; result?: CompareResult }>(
      `/api/task/${encodeURIComponent(taskId)}/status`,
      { skipNotify: true },
    );
    const status = String(state.status || "");
    if (["done", "error", "canceled"].includes(status)) return state;
    await new Promise((resolve) => window.setTimeout(resolve, 250));
  }
}

function planCacheKey(): string {
  const draft = dirty.value || storeDraft.value ? JSON.stringify(textOnlySnapshot(snapshot.value)) : "";
  return `${csvPath.value}|${screenshotsDir.value}|${mtime.value ?? ""}|${draft}`;
}

async function runCompare(key: string) {
  const { subscribeIfNeeded } = useTaskLog();
  const gen = ++compareGen;
  planLoading.value = true;
  planError.value = "";
  compareStartedAt.value = Date.now();
  try {
    const { task_id } = await httpJson<{ task_id: string }>("/api/listing/compare", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({
        csv_path: csvPath.value,
        screenshots_dir: screenshotsDir.value,
        ...((dirty.value || storeDraft.value) ? { snapshot: textOnlySnapshot(snapshot.value) } : {}),
      }),
    });
    if (gen !== compareGen) return;
    compareTaskId.value = task_id;
    subscribeIfNeeded(task_id);
    const state = await waitForTask(task_id);
    if (gen !== compareGen) return;
    const result = state.result || {};
    if (state.status !== "done") {
      planOk.value = false;
      planError.value = result.error || state.status;
      planLocales.value = [];
      planVersion.value = null;
      planLoadedKey.value = "";
      return;
    }
    planLocales.value = result.locales || [];
    planVersion.value = result.version || null;
    planLoadedKey.value = key;
    planOk.value = result.ok !== false;
    planError.value = planOk.value ? "" : result.error || "";
  } catch (err) {
    if (gen !== compareGen) return;
    planOk.value = false;
    if (err instanceof ApiError) planError.value = apiErrorMessage(err);
    else planError.value = String(err);
    planLocales.value = [];
    planVersion.value = null;
    planLoadedKey.value = "";
  } finally {
    if (gen === compareGen) {
      planLoading.value = false;
      compareTaskId.value = "";
      compareStartedAt.value = 0;
    }
  }
}

async function ensureCompare(opts?: { force?: boolean }) {
  if (boundProfile === undefined || !boundProfile) {
    planLocales.value = [];
    planError.value = "";
    planOk.value = true;
    planLoadedKey.value = "";
    planVersion.value = null;
    return;
  }
  const key = planCacheKey();
  if (!opts?.force && planLoadedKey.value === key && !planLoading.value) return;
  if (compareInFlight && compareInFlight.key === key && !opts?.force) {
    await compareInFlight.promise;
    return;
  }
  const promise = runCompare(key);
  compareInFlight = { key, promise };
  try {
    await promise;
  } finally {
    if (compareInFlight?.promise === promise) compareInFlight = null;
  }
}

function invalidateCompare() {
  planLoadedKey.value = "";
}

const compared = computed(() => !!planLoadedKey.value && planLoadedKey.value === planCacheKey());

function hydrate(profile: string, defaults: { csv: string; screenshots: string }) {
  if (boundProfile === profile) return;
  hydrating = true;
  boundProfile = profile;
  const stored = readFormMemory(formMemoryKey(METADATA_FORM_KEY_PREFIX, profile));
  csvPath.value = (typeof stored?.csv_path === "string" && stored.csv_path) || defaults.csv || "data/appstore_info.csv";
  screenshotsDir.value = (typeof stored?.screenshots_dir === "string" && stored.screenshots_dir)
    || defaults.screenshots
    || "data/screenshots";
  includeMetadata.value = stored?.include_metadata !== false;
  includeScreenshots.value = stored?.include_screenshots !== false;
  dryRun.value = !!stored?.dry_run;
  verbose.value = stored?.verbose !== undefined ? !!stored.verbose : false;
  autoTranslate.value = stored?.auto_translate !== false;
  hydrating = false;
  persistMemory();
  invalidateCompare();
}

function hydrateScope() {
  useListingScope().hydrateFromLocal(snapshot.value.locales as ListingLocaleRow[]);
}

async function load(path?: string) {
  alert.value = "";
  conflict.value = false;
  loading.value = true;
  const file = (path || csvPath.value || "").trim() || "data/appstore_info.csv";
  csvPath.value = file;
  rememberFormPath("listing.csv_path", file);
  rememberFormPath("listing.screenshots_dir", screenshotsDir.value);
  persistMemory();
  try {
    const qs = new URLSearchParams({ csv_path: file, screenshots_dir: screenshotsDir.value });
    const data = await httpJson<{
      ok: boolean;
      exists: boolean;
      hasContent: boolean;
      mtime: number | null;
      snapshot: ListingSnapshot;
      csvPath?: string;
    }>(`/api/listing/local?${qs}`);
    const disk = cloneSnapshot(data.snapshot);
    snapshot.value = disk;
    mtime.value = data.mtime;
    exists.value = !!data.exists;
    dirty.value = false;
    storeDraft.value = false;
    loaded.value = true;
    if (data.csvPath) csvPath.value = data.csvPath;
    restoreDraft(disk);
    hydrateScope();
    invalidateCompare();
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  } finally {
    loading.value = false;
  }
}

async function save() {
  conflict.value = false;
  saving.value = true;
  const draftKey = currentDraftKey();
  try {
    const data = await httpJson<{ mtime: number; csvPath?: string }>("/api/listing/local/save", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({
        csv_path: csvPath.value,
        expected_mtime: mtime.value,
        locales: snapshot.value.locales.map((loc) => ({ locale: loc.locale, fields: loc.fields })),
      }),
    });
    mtime.value = data.mtime;
    if (data.csvPath) csvPath.value = data.csvPath;
    exists.value = true;
    dirty.value = false;
    if (draftKey) clearIapDraft(draftKey);
    storeDraft.value = false;
    invalidateCompare();
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      conflict.value = true;
      return false;
    }
    throw err;
  } finally {
    saving.value = false;
  }
  return true;
}

function applySnapshot(next: ListingSnapshot, opts?: { dirty?: boolean; storeDraft?: boolean }) {
  snapshot.value = cloneSnapshot(next);
  dirty.value = opts?.dirty !== false;
  loaded.value = true;
  if (opts?.storeDraft === true) {
    storeDraft.value = true;
    persistDraft();
  } else if (opts?.storeDraft === false) {
    dropDraft();
  } else if (storeDraft.value && dirty.value) {
    persistDraft();
  }
  hydrateScope();
  invalidateCompare();
}

function markDirty() {
  dirty.value = true;
  persistDraft();
  hydrateScope();
  invalidateCompare();
}

function discard() {
  dropDraft();
  dirty.value = false;
  return load();
}

function setCsvPath(path: string) {
  csvPath.value = path;
  rememberFormPath("listing.csv_path", path);
  persistMemory();
}

function setScreenshotsDir(path: string) {
  screenshotsDir.value = path;
  rememberFormPath("listing.screenshots_dir", path);
  persistMemory();
}

async function refreshLocaleShots(locale: string) {
  const qs = new URLSearchParams({ csv_path: csvPath.value, screenshots_dir: screenshotsDir.value });
  const data = await httpJson<{ snapshot: ListingSnapshot }>(`/api/listing/local?${qs}`, { skipNotify: true });
  const incoming = (data.snapshot?.locales || []).find((row) => row.locale === locale);
  const current = snapshot.value.locales.find((row) => row.locale === locale);
  if (current) {
    current.screenshots = incoming?.screenshots || {};
  } else if (incoming) {
    snapshot.value.locales.push(incoming);
  }
  hydrateScope();
}

export function useListingWorkflow() {
  const { snapshot: profileSnap } = useProfile();
  const profile = computed(() => profileSnap.value?.current_profile || "");
  hydrate(profile.value, {
    csv: profileSnap.value?.paths.csv || "data/appstore_info.csv",
    screenshots: profileSnap.value?.paths.screenshots || "data/screenshots",
  });

  return {
    csvPath,
    screenshotsDir,
    snapshot,
    mtime,
    dirty,
    storeDraft,
    exists,
    loaded,
    loading,
    saving,
    alert,
    conflict,
    selectedLocale,
    dryRun,
    verbose,
    includeMetadata,
    includeScreenshots,
    autoTranslate,
    planLocales,
    planVersion,
    planError,
    planOk,
    planLoading,
    compared,
    compareTaskId,
    compareStartedAt,
    hasContent: computed(() => hasContent(snapshot.value)),
    emptyProfile: computed(() => !profile.value),
    load,
    save,
    reload: () => load(csvPath.value),
    applySnapshot,
    markDirty,
    discard,
    setCsvPath,
    setScreenshotsDir,
    persistMemory,
    cloneSnapshot,
    emptySnapshot,
    blankLocale,
    emptyFields,
    refreshLocaleShots,
    ensureCompare,
    invalidateCompare,
  };
}
