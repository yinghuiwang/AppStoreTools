import { computed, ref, watch } from "vue";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import {
  IAP_FORM_KEY_PREFIX,
  clearIapDraft,
  formMemoryKey,
  iapDraftKey,
  iapDraftPayload,
  iapFormPayload,
  parseIapDraft,
  parseIapStored,
  readFormMemory,
  readIapDraft,
  writeFormMemory,
  writeIapDraft,
} from "@/composables/useFormMemory";
import { rememberFormPath } from "@/composables/useFormPaths";
import { useProfile } from "@/composables/useProfile";
import { useTaskLog } from "@/composables/useTaskLog";

export type LocEntry = { name: string; description?: string };
export type LocMap = Record<string, LocEntry>;
export type IapPrice = {
  baseTerritory?: string;
  baseAmount?: string;
  pricePointId?: string;
  applyEqualizedPrices?: boolean;
};
export type IapReview = { screenshot?: string; note?: string };
export type IapItem = {
  productId: string;
  name?: string;
  inAppPurchaseType?: string;
  availableInAllTerritories?: boolean;
  price?: IapPrice;
  localizations?: LocMap;
  review?: IapReview;
  reviewNote?: string;
};
export type IapSubscription = {
  productId: string;
  name?: string;
  subscriptionPeriod?: string;
  groupLevel?: number | null;
  familySharable?: boolean;
  availableInAllTerritories?: boolean;
  price?: IapPrice;
  localizations?: LocMap;
  introductoryOffer?: Record<string, unknown>;
  promotionalOffers?: unknown[];
  review?: IapReview;
};
export type IapGroup = {
  referenceName: string;
  localizations?: LocMap;
  subscriptions?: IapSubscription[];
};
export type IapSnapshot = {
  items: IapItem[];
  subscriptionGroups: IapGroup[];
};

export type PlanField = { field: string; local: string; asc: string };
export type PlanItem = {
  productId: string;
  kind: string;
  type: string;
  name: string;
  groupName: string;
  action: string;
  status: string;
  fields: PlanField[];
  missingScreenshot?: boolean;
};

export function isAbsoluteFsPath(path: string): boolean {
  const value = (path || "").trim();
  return value.startsWith("/") || /^[A-Za-z]:[\\/]/.test(value);
}

export function parentDir(path: string): string {
  const normalized = (path || "").replace(/[/\\]+$/, "");
  const idx = Math.max(normalized.lastIndexOf("/"), normalized.lastIndexOf("\\"));
  return idx >= 0 ? normalized.slice(0, idx) : ".";
}

export function resolveReviewShotPath(shot: string, iapFile: string): string {
  const value = (shot || "").trim();
  if (!value) return "";
  if (isAbsoluteFsPath(value)) return value;
  const base = parentDir((iapFile || "").trim() || ".");
  const rel = value.replace(/^\.[/\\]/, "");
  const sep = base.includes("\\") && !base.includes("/") ? "\\" : "/";
  return `${base.replace(/[/\\]+$/, "")}${sep}${rel}`;
}

export function reviewShotThumbUrl(shot: string, iapFile: string): string {
  const resolved = resolveReviewShotPath(shot, iapFile);
  if (!resolved) return "";
  const root = parentDir(resolved) || ".";
  return `/api/listing/thumb?path=${encodeURIComponent(resolved)}&root=${encodeURIComponent(root)}`;
}

function emptySnapshot(): IapSnapshot {
  return { items: [], subscriptionGroups: [] };
}

function cloneSnapshot(value: IapSnapshot | null | undefined): IapSnapshot {
  const raw = value || emptySnapshot();
  return JSON.parse(JSON.stringify({
    items: Array.isArray(raw.items) ? raw.items : [],
    subscriptionGroups: Array.isArray(raw.subscriptionGroups) ? raw.subscriptionGroups : [],
  })) as IapSnapshot;
}

function hasContent(value: IapSnapshot | null | undefined): boolean {
  if (!value) return false;
  return (value.items?.length || 0) > 0 || (value.subscriptionGroups?.length || 0) > 0;
}

const iapFile = ref("data/iap_packages.json");
const snapshot = ref<IapSnapshot>(emptySnapshot());
const mtime = ref<number | null>(null);
const dirty = ref(false);
const storeDraft = ref(false);
const exists = ref(false);
const loaded = ref(false);
const loading = ref(false);
const saving = ref(false);
const alert = ref("");
const conflict = ref(false);
const selectedKey = ref("");
let boundProfile: string | undefined;
let hydrating = false;

function persistMemory() {
  if (hydrating || boundProfile === undefined) return;
  writeFormMemory(
    formMemoryKey(IAP_FORM_KEY_PREFIX, boundProfile),
    iapFormPayload({
      iap_file: iapFile.value,
      dry_run: dryRun.value,
      update_existing: updateExisting.value,
      verbose: verbose.value,
      auto_translate: autoTranslate.value,
    }),
  );
}

function currentDraftKey(): string | null {
  if (boundProfile === undefined) return null;
  return iapDraftKey(boundProfile, iapFile.value);
}

function persistDraft() {
  if (hydrating || boundProfile === undefined || !storeDraft.value) return;
  const key = currentDraftKey();
  if (!key) return;
  writeIapDraft(
    key,
    iapDraftPayload({
      iap_file: iapFile.value,
      snapshot: cloneSnapshot(snapshot.value),
      store_draft: true,
    }),
  );
}

function restoreDraft(): boolean {
  if (boundProfile === undefined) return false;
  const key = currentDraftKey();
  if (!key) return false;
  const stored = parseIapDraft(readIapDraft(key));
  if (!stored?.snapshot) return false;
  snapshot.value = cloneSnapshot(stored.snapshot as IapSnapshot);
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

const dryRun = ref(false);
const updateExisting = ref(false);
const verbose = ref(false);
const autoTranslate = ref(true);

type CompareResult = {
  ok?: boolean;
  error?: string;
  items?: PlanItem[];
  missingOnStore?: string[];
};

const planItems = ref<PlanItem[]>([]);
const planError = ref("");
const planOk = ref(true);
const planLoading = ref(false);
const planLoadedKey = ref("");
const missingOnStore = ref<Record<string, true>>({});
const scanLoadedKey = ref("");
const scanLoading = ref(false);
const compareTaskId = ref("");
const compareStartedAt = ref(0);
let compareInFlight: { key: string; promise: Promise<void> } | null = null;
let compareGen = 0;

function applyMissingOnStore(ids: string[]) {
  const next: Record<string, true> = {};
  for (const raw of ids) {
    const pid = String(raw || "").trim();
    if (pid) next[pid] = true;
  }
  missingOnStore.value = next;
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
  return `${iapFile.value}|${updateExisting.value ? "1" : "0"}|${mtime.value ?? ""}`;
}

function applyPlanItems(items: PlanItem[]) {
  planItems.value = items;
}

async function loadPlan(opts?: { force?: boolean }) {
  if (boundProfile === undefined || !boundProfile) {
    planItems.value = [];
    planError.value = "";
    planOk.value = true;
    planLoadedKey.value = "";
    return;
  }
  const key = planCacheKey();
  if (compareInFlight && compareInFlight.key === key && !opts?.force) {
    await compareInFlight.promise;
    return;
  }
  if (!opts?.force && planLoadedKey.value === key && !planLoading.value) return;
  planLoading.value = true;
  planError.value = "";
  try {
    const data = await httpJson<{ ok: boolean; error?: string; items?: PlanItem[] }>(
      `/api/iap/plan?iap_file=${encodeURIComponent(iapFile.value)}&update_existing=${updateExisting.value ? "true" : ""}`,
    );
    applyPlanItems(data.items || []);
    planLoadedKey.value = key;
    planOk.value = data.ok !== false;
    if (!planOk.value) planError.value = data.error || "";
  } catch (err) {
    planOk.value = false;
    if (err instanceof ApiError) planError.value = apiErrorMessage(err);
    else planError.value = String(err);
    planItems.value = [];
    planLoadedKey.value = "";
  } finally {
    planLoading.value = false;
  }
}

async function ensurePlan() {
  if (dirty.value || storeDraft.value) {
    await ensureCompare();
    return;
  }
  await loadPlan();
}

async function loadShotScan(opts?: { force?: boolean }) {
  if (boundProfile === undefined || !boundProfile) {
    missingOnStore.value = {};
    scanLoadedKey.value = "";
    return;
  }
  const key = `${iapFile.value}|${mtime.value ?? ""}`;
  if (compareInFlight && !opts?.force) {
    await compareInFlight.promise;
    return;
  }
  if (!opts?.force && scanLoadedKey.value === key && !scanLoading.value) return;
  scanLoading.value = true;
  try {
    const data = await httpJson<{ targets?: Array<{ productId?: string }> }>(
      "/api/iap/review-screenshots/scan",
      { method: "POST", skipNotify: true, body: JSON.stringify({ iapFile: iapFile.value }) },
    );
    applyMissingOnStore((data.targets || []).map((item) => String(item.productId || "")));
    scanLoadedKey.value = key;
  } catch {
    missingOnStore.value = {};
    scanLoadedKey.value = key;
  } finally {
    scanLoading.value = false;
  }
}

async function runCompare(key: string) {
  const { subscribeIfNeeded } = useTaskLog();
  const gen = ++compareGen;
  planLoading.value = true;
  planError.value = "";
  compareStartedAt.value = Date.now();
  try {
    const { task_id } = await httpJson<{ task_id: string }>("/api/iap/compare", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({
        iapFile: iapFile.value,
        update_existing: updateExisting.value,
        ...((dirty.value || storeDraft.value) ? { snapshot: snapshot.value } : {}),
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
      planItems.value = [];
      missingOnStore.value = {};
      planLoadedKey.value = "";
      scanLoadedKey.value = "";
      return;
    }
    applyPlanItems(result.items || []);
    applyMissingOnStore(result.missingOnStore || []);
    planLoadedKey.value = key;
    scanLoadedKey.value = key;
    planOk.value = result.ok !== false;
    planError.value = planOk.value ? "" : result.error || "";
  } catch (err) {
    if (gen !== compareGen) return;
    planOk.value = false;
    if (err instanceof ApiError) planError.value = apiErrorMessage(err);
    else planError.value = String(err);
    planItems.value = [];
    missingOnStore.value = {};
    planLoadedKey.value = "";
    scanLoadedKey.value = "";
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
    planItems.value = [];
    planError.value = "";
    planOk.value = true;
    planLoadedKey.value = "";
    missingOnStore.value = {};
    scanLoadedKey.value = "";
    return;
  }
  const key = planCacheKey();
  if (!opts?.force && planLoadedKey.value === key && scanLoadedKey.value === key && !planLoading.value) {
    return;
  }
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
  scanLoadedKey.value = "";
}

const compared = computed(() => !!planLoadedKey.value && planLoadedKey.value === planCacheKey());

function hydrate(profile: string, defaultFile: string) {
  if (boundProfile === profile) return;
  hydrating = true;
  boundProfile = profile;
  const stored = parseIapStored(readFormMemory(formMemoryKey(IAP_FORM_KEY_PREFIX, profile)));
  iapFile.value = stored?.iap_file || defaultFile || "data/iap_packages.json";
  dryRun.value = !!stored?.dry_run;
  updateExisting.value = !!stored?.update_existing;
  verbose.value = stored?.verbose !== undefined ? !!stored.verbose : false;
  autoTranslate.value = stored?.auto_translate !== false;
  hydrating = false;
  persistMemory();
  invalidateCompare();
}

async function load(path?: string) {
  alert.value = "";
  conflict.value = false;
  loading.value = true;
  const file = (path || iapFile.value || "").trim() || "data/iap_packages.json";
  iapFile.value = file;
  rememberFormPath("iap.iap_file", file);
  persistMemory();
  try {
    const data = await httpJson<{
      ok: boolean;
      exists: boolean;
      hasContent: boolean;
      mtime: number | null;
      snapshot: IapSnapshot;
      iapFile?: string;
    }>(`/api/iap/local?iap_file=${encodeURIComponent(file)}`);
    snapshot.value = cloneSnapshot(data.snapshot);
    mtime.value = data.mtime;
    exists.value = !!data.exists;
    dirty.value = false;
    storeDraft.value = false;
    loaded.value = true;
    if (data.iapFile) iapFile.value = data.iapFile;
    restoreDraft();
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
    const data = await httpJson<{ mtime: number; iapFile?: string }>("/api/iap/local/save", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({
        iap_file: iapFile.value,
        expected_mtime: mtime.value,
        snapshot: snapshot.value,
      }),
    });
    mtime.value = data.mtime;
    if (data.iapFile) iapFile.value = data.iapFile;
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

function applySnapshot(next: IapSnapshot, opts?: { dirty?: boolean; storeDraft?: boolean }) {
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
  invalidateCompare();
}

function markDirty() {
  dirty.value = true;
  persistDraft();
}

function discard() {
  dropDraft();
  dirty.value = false;
  return load();
}

function setIapFile(path: string) {
  iapFile.value = path;
  rememberFormPath("iap.iap_file", path);
  persistMemory();
}

const fieldErrors = ref({ file: "" });
watch(iapFile, (value) => {
  if (String(value || "").trim() && fieldErrors.value.file) fieldErrors.value.file = "";
});

export function useIapWorkflow() {
  const { snapshot: profileSnap } = useProfile();
  const profile = computed(() => profileSnap.value?.current_profile || "");
  hydrate(profile.value, profileSnap.value?.paths.iap || "data/iap_packages.json");

  return {
    iapFile,
    fieldErrors,
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
    selectedKey,
    dryRun,
    updateExisting,
    verbose,
    autoTranslate,
    planItems,
    planError,
    planOk,
    planLoading,
    compared,
    compareTaskId,
    compareStartedAt,
    missingOnStore,
    scanLoading,
    hasContent: computed(() => hasContent(snapshot.value)),
    emptyProfile: computed(() => !profile.value),
    load,
    save,
    reload: () => load(iapFile.value),
    applySnapshot,
    markDirty,
    discard,
    setIapFile,
    persistMemory,
    cloneSnapshot,
    emptySnapshot,
    loadPlan,
    ensurePlan,
    loadShotScan,
    ensureCompare,
    invalidateCompare,
  };
}
