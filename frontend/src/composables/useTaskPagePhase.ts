import { computed, ref, type Ref } from "vue";

export type TaskPagePhase = "form" | "run";
export type TaskPageId = "build" | "iap" | "whats-new" | "urls" | "listing-upload";

export const TASK_PAGE_IDS: readonly TaskPageId[] = [
  "build",
  "iap",
  "whats-new",
  "urls",
  "listing-upload",
];

/** Route component names for task form pages. AppShell keep-alive caches all routes. */
export const TASK_KEEP_ALIVE_NAMES: string[] = [
  "ListingView",
  "WhatsNewView",
  "UrlsView",
  "BuildView",
  "IapView",
];

export const LISTING_TABS = new Set(["upload", "local", "diff"]);
export const DEFAULT_LISTING_TAB = "upload";

const STORAGE_KEY = "asc.taskPages";

type PageMeta = Record<string, string>;

type PageBucket = {
  phase: Ref<TaskPagePhase>;
  taskId: Ref<string>;
  meta: Ref<PageMeta>;
};

type StoredPage = {
  phase: TaskPagePhase;
  taskId: string;
  meta: PageMeta;
};

type StoredState = {
  profile: string;
  listingTab: string;
  pages: Partial<Record<TaskPageId, StoredPage>>;
};

function emptyMeta(): PageMeta {
  return {};
}

function makeBucket(): PageBucket {
  return {
    phase: ref<TaskPagePhase>("form"),
    taskId: ref(""),
    meta: ref<PageMeta>(emptyMeta()),
  };
}

const pages: Record<TaskPageId, PageBucket> = {
  build: makeBucket(),
  iap: makeBucket(),
  "whats-new": makeBucket(),
  urls: makeBucket(),
  "listing-upload": makeBucket(),
};

const listingTab = ref(DEFAULT_LISTING_TAB);
let boundProfile: string | undefined;
let storedProfile: string | undefined;
let didHydrate = false;

function getSession(): Pick<Storage, "getItem" | "setItem" | "removeItem"> | null {
  try {
    if (typeof sessionStorage === "undefined") return null;
    return sessionStorage;
  } catch {
    return null;
  }
}

function serialize(): StoredState {
  const storedPages: StoredState["pages"] = {};
  for (const id of TASK_PAGE_IDS) {
    storedPages[id] = {
      phase: pages[id].phase.value,
      taskId: pages[id].taskId.value,
      meta: { ...pages[id].meta.value },
    };
  }
  return {
    profile: boundProfile ?? "",
    listingTab: listingTab.value,
    pages: storedPages,
  };
}

function applyStored(stored: StoredState) {
  listingTab.value = LISTING_TABS.has(stored.listingTab)
    ? stored.listingTab
    : DEFAULT_LISTING_TAB;
  for (const id of TASK_PAGE_IDS) {
    const row = stored.pages?.[id];
    pages[id].phase.value = row?.phase === "run" ? "run" : "form";
    pages[id].taskId.value = String(row?.taskId || "");
    pages[id].meta.value = row?.meta && typeof row.meta === "object" ? { ...row.meta } : emptyMeta();
  }
}

function clearPages() {
  listingTab.value = DEFAULT_LISTING_TAB;
  for (const id of TASK_PAGE_IDS) {
    pages[id].phase.value = "form";
    pages[id].taskId.value = "";
    pages[id].meta.value = emptyMeta();
  }
}

function persist() {
  const store = getSession();
  if (!store) return;
  store.setItem(STORAGE_KEY, JSON.stringify(serialize()));
}

function hydrate() {
  if (didHydrate) return;
  didHydrate = true;
  const store = getSession();
  const raw = store?.getItem(STORAGE_KEY);
  if (!raw) return;
  try {
    const stored = JSON.parse(raw) as StoredState;
    if (!stored || typeof stored !== "object") return;
    applyStored(stored);
    storedProfile = String(stored.profile || "");
  } catch {
    /* ignore invalid session */
  }
}

/** Wipe form/run snapshots (profile switch or tests). */
export function resetTaskPageState() {
  hydrate();
  clearPages();
  persist();
}

/**
 * Bind snapshots to the current App profile.
 * Switching profile resets every page; the first bind keeps sessionStorage
 * state when it belongs to the same profile.
 */
export function bindTaskPageProfile(profile: string) {
  hydrate();
  if (boundProfile === profile) return;
  if (boundProfile === undefined) {
    boundProfile = profile;
    if (storedProfile !== undefined && storedProfile !== profile) {
      clearPages();
    }
    persist();
    return;
  }
  boundProfile = profile;
  clearPages();
  persist();
}

export function useListingTab() {
  hydrate();

  function setListingTab(value: string) {
    listingTab.value = LISTING_TABS.has(value) ? value : DEFAULT_LISTING_TAB;
    persist();
  }

  return { listingTab, setListingTab };
}

/** Module-level form/run switch keyed by page. Survives view unmount. */
export function useTaskPagePhase(page: TaskPageId) {
  hydrate();
  const bucket = pages[page];
  const isForm = computed(() => bucket.phase.value === "form");
  const isRun = computed(() => bucket.phase.value === "run");

  function enterRun(nextTaskId: string, extra?: PageMeta) {
    bucket.taskId.value = nextTaskId;
    if (extra) bucket.meta.value = { ...bucket.meta.value, ...extra };
    bucket.phase.value = "run";
    persist();
  }

  function backToForm() {
    bucket.phase.value = "form";
    persist();
  }

  return {
    phase: bucket.phase,
    taskId: bucket.taskId,
    meta: bucket.meta,
    isForm,
    isRun,
    enterRun,
    backToForm,
  };
}
