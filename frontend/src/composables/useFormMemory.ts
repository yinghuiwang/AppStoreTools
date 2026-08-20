import { ref, watch, type Ref } from "vue";

/** Pre-Vue Jinja keys: `asc_<page>_form_<profile>`. */
export const METADATA_FORM_KEY_PREFIX = "asc_metadata_form_";
export const BUILD_FORM_KEY_PREFIX = "asc_build_form_";
export const IAP_FORM_KEY_PREFIX = "asc_iap_form_";
/** sessionStorage draft of an unsaved store pull, keyed by profile + iapFile. */
export const IAP_DRAFT_KEY_PREFIX = "asc_iap_draft_";

export type ListingFormMemory = {
  csv_path: string;
  screenshots_dir: string;
  include_metadata: boolean;
  include_screenshots: boolean;
  dry_run: boolean;
  verbose: boolean;
};

export type BuildFormMemory = {
  mode: "full" | "build" | "deploy";
  project: string;
  scheme: string;
  destination: string;
  signing: string;
  certificate: string;
  provisioning_profile: string;
  reuse_archive: string;
  ipa_path: string;
  verbose: boolean;
  dry_run: boolean;
};

export type IapFormMemory = {
  iap_file: string;
  dry_run: boolean;
  update_existing: boolean;
  verbose: boolean;
  auto_translate?: boolean;
};

export type IapDraftMemory = {
  iap_file: string;
  snapshot: unknown;
  store_draft: boolean;
};

type ListingBucket = {
  csv_path: Ref<string>;
  screenshots_dir: Ref<string>;
  include_metadata: Ref<boolean>;
  include_screenshots: Ref<boolean>;
  dry_run: Ref<boolean>;
  verbose: Ref<boolean>;
};

function getLocal(): Pick<Storage, "getItem" | "setItem"> | null {
  try {
    if (typeof localStorage === "undefined") return null;
    return localStorage;
  } catch {
    return null;
  }
}

export function formMemoryKey(prefix: string, profile: string): string {
  return `${prefix}${profile || ""}`;
}

export function readFormMemory(key: string): Record<string, unknown> | null {
  const store = getLocal();
  if (!store) return null;
  const raw = store.getItem(key);
  if (!raw) return null;
  try {
    const data = JSON.parse(raw) as unknown;
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    return data as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function writeFormMemory(key: string, data: Record<string, unknown>): void {
  const store = getLocal();
  if (!store) return;
  try {
    const prev = readFormMemory(key) || {};
    store.setItem(key, JSON.stringify({ ...prev, ...data }));
  } catch {
    /* quota / private mode */
  }
}

function getSession(): Pick<Storage, "getItem" | "setItem" | "removeItem"> | null {
  try {
    if (typeof sessionStorage !== "undefined") return sessionStorage;
  } catch {
    /* private mode */
  }
  try {
    if (typeof localStorage !== "undefined") return localStorage;
  } catch {
    return null;
  }
  return null;
}

export function iapDraftKey(profile: string, iapFile: string): string {
  return `${IAP_DRAFT_KEY_PREFIX}${profile || ""}:${iapFile || ""}`;
}

export function readIapDraft(key: string): Record<string, unknown> | null {
  const store = getSession();
  if (!store) return null;
  const raw = store.getItem(key);
  if (!raw) return null;
  try {
    const data = JSON.parse(raw) as unknown;
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    return data as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function writeIapDraft(key: string, data: Record<string, unknown>): void {
  const store = getSession();
  if (!store) return;
  try {
    store.setItem(key, JSON.stringify(data));
  } catch {
    /* quota / private mode */
  }
}

export function clearIapDraft(key: string): void {
  const store = getSession();
  if (!store) return;
  try {
    store.removeItem(key);
  } catch {
    /* private mode */
  }
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function applyListingStored(
  data: Record<string, unknown> | null,
  target: ListingFormMemory,
): ListingFormMemory {
  if (!data) return target;
  const next = { ...target };
  if (asText(data.csv_path)) next.csv_path = asText(data.csv_path);
  if (asText(data.screenshots_dir)) next.screenshots_dir = asText(data.screenshots_dir);
  next.include_metadata = data.include_metadata !== false;
  next.include_screenshots = data.include_screenshots !== false;
  next.dry_run = !!data.dry_run;
  if (data.verbose !== undefined) next.verbose = !!data.verbose;
  return next;
}

export function listingFormPayload(fields: ListingFormMemory): Record<string, unknown> {
  return {
    csv_path: fields.csv_path,
    screenshots_dir: fields.screenshots_dir,
    include_metadata: fields.include_metadata,
    include_screenshots: fields.include_screenshots,
    dry_run: fields.dry_run,
    verbose: fields.verbose,
  };
}

export function parseBuildStored(data: Record<string, unknown> | null): Partial<BuildFormMemory> | null {
  if (!data) return null;
  const mode = data.mode;
  const reuse = data.reuse_archive;
  return {
    mode: mode === "full" || mode === "build" || mode === "deploy" ? mode : undefined,
    project: asText(data.project) || undefined,
    scheme: asText(data.scheme) || undefined,
    destination: asText(data.destination) || undefined,
    signing: asText(data.signing) || undefined,
    certificate: asText(data.certificate) || undefined,
    provisioning_profile: asText(data.provisioning_profile) || undefined,
    reuse_archive: reuse === undefined
      ? undefined
      : reuse === "reuse" || reuse === true
        ? "reuse"
        : reuse === "rebuild"
          ? "rebuild"
          : "",
    ipa_path: asText(data.ipa_path) || undefined,
    verbose: !!data.verbose,
    dry_run: !!data.dry_run,
  };
}

export function buildFormPayload(fields: BuildFormMemory): Record<string, unknown> {
  return {
    mode: fields.mode,
    project: fields.project,
    scheme: fields.scheme,
    destination: fields.destination,
    signing: fields.signing,
    certificate: fields.certificate,
    provisioning_profile: fields.provisioning_profile,
    reuse_archive: fields.reuse_archive === "reuse" || fields.reuse_archive === "true"
      ? "reuse"
      : fields.reuse_archive === "rebuild"
        ? "rebuild"
        : "",
    ipa_path: fields.ipa_path,
    verbose: fields.verbose,
    dry_run: fields.dry_run,
  };
}

export function parseIapStored(data: Record<string, unknown> | null): Partial<IapFormMemory> | null {
  if (!data) return null;
  return {
    iap_file: asText(data.iap_file) || undefined,
    dry_run: !!data.dry_run,
    update_existing: !!data.update_existing,
    verbose: data.verbose !== undefined ? !!data.verbose : undefined,
    auto_translate: data.auto_translate !== undefined ? !!data.auto_translate : undefined,
  };
}

export function iapFormPayload(fields: IapFormMemory): Record<string, unknown> {
  return {
    iap_file: fields.iap_file,
    dry_run: fields.dry_run,
    update_existing: fields.update_existing,
    verbose: fields.verbose,
    auto_translate: fields.auto_translate !== false,
  };
}

export function parseIapDraft(data: Record<string, unknown> | null): Partial<IapDraftMemory> | null {
  if (!data) return null;
  const snapshot = data.snapshot;
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return null;
  return {
    iap_file: asText(data.iap_file) || undefined,
    snapshot,
    store_draft: data.store_draft !== false,
  };
}

export function iapDraftPayload(fields: IapDraftMemory): Record<string, unknown> {
  return {
    iap_file: fields.iap_file,
    snapshot: fields.snapshot,
    store_draft: fields.store_draft !== false,
  };
}

const listing: ListingBucket = {
  csv_path: ref(""),
  screenshots_dir: ref(""),
  include_metadata: ref(true),
  include_screenshots: ref(true),
  dry_run: ref(false),
  verbose: ref(false),
};

let listingProfile: string | undefined;
let listingWatchStarted = false;
let listingHydrating = false;

function listingSnapshot(): ListingFormMemory {
  return {
    csv_path: listing.csv_path.value,
    screenshots_dir: listing.screenshots_dir.value,
    include_metadata: listing.include_metadata.value,
    include_screenshots: listing.include_screenshots.value,
    dry_run: listing.dry_run.value,
    verbose: listing.verbose.value,
  };
}

function persistListing() {
  if (listingHydrating || listingProfile === undefined) return;
  writeFormMemory(
    formMemoryKey(METADATA_FORM_KEY_PREFIX, listingProfile),
    listingFormPayload(listingSnapshot()),
  );
}

function ensureListingWatch() {
  if (listingWatchStarted) return;
  listingWatchStarted = true;
  watch(
    [
      listing.csv_path,
      listing.screenshots_dir,
      listing.include_metadata,
      listing.include_screenshots,
      listing.dry_run,
      listing.verbose,
    ],
    persistListing,
    { flush: "sync" },
  );
}

/** Shared Listing fields so Upload / Local / Diff read the same remembered paths. */
export function hydrateListingForm(
  profile: string,
  defaults: { csv: string; screenshots: string },
): ListingBucket {
  if (listingProfile !== profile) {
    listingHydrating = true;
    listingProfile = profile;
    const stored = readFormMemory(formMemoryKey(METADATA_FORM_KEY_PREFIX, profile));
    listing.csv_path.value = defaults.csv;
    listing.screenshots_dir.value = defaults.screenshots;
    listing.include_metadata.value = true;
    listing.include_screenshots.value = true;
    listing.dry_run.value = false;
    listing.verbose.value = false;
    const applied = applyListingStored(stored, listingSnapshot());
    listing.csv_path.value = applied.csv_path;
    listing.screenshots_dir.value = applied.screenshots_dir;
    listing.include_metadata.value = applied.include_metadata;
    listing.include_screenshots.value = applied.include_screenshots;
    listing.dry_run.value = applied.dry_run;
    listing.verbose.value = applied.verbose;
    listingHydrating = false;
  }
  ensureListingWatch();
  return listing;
}

export function resetFormMemory() {
  listingProfile = undefined;
  listingWatchStarted = false;
  listingHydrating = false;
  listing.csv_path.value = "";
  listing.screenshots_dir.value = "";
  listing.include_metadata.value = true;
  listing.include_screenshots.value = true;
  listing.dry_run.value = false;
  listing.verbose.value = false;
}
