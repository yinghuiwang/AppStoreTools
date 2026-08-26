import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { httpJson } from "@/api/http";

export type LocaleCatalogRow = {
  code: string;
  name_en: string;
  name_zh: string;
  present?: boolean;
};

export function displayNameFor(row: LocaleCatalogRow, uiLocale: string): string {
  return uiLocale.startsWith("zh") ? row.name_zh : row.name_en;
}

export function optionLabelFor(row: LocaleCatalogRow, uiLocale: string): string {
  const name = displayNameFor(row, uiLocale);
  return name ? `${row.code} ${name}` : row.code;
}

/** Session cache: one catalog (+ optional presence) shared by Create/Preview/LocalePicker. */
const rows = ref<LocaleCatalogRow[]>([]);
const loading = ref(false);
const error = ref("");
const presenceAvailable = ref(false);

let catalogReady = false;
let presenceReady = false;
let catalogInflight: Promise<void> | null = null;
let presenceInflight: Promise<void> | null = null;
let cacheGeneration = 0;
let loadCount = 0;

async function fetchCatalog(unavailable: string): Promise<void> {
  if (catalogInflight) return catalogInflight;
  const pending = (async () => {
    error.value = "";
    try {
      const data = await httpJson<{ locales: LocaleCatalogRow[] }>("/api/metadata/locales");
      rows.value = data.locales || [];
      catalogReady = true;
      cacheGeneration += 1;
      presenceReady = false;
      presenceAvailable.value = false;
    } catch (err) {
      catalogReady = false;
      error.value = err instanceof Error ? err.message : unavailable;
    }
  })().finally(() => {
    if (catalogInflight === pending) catalogInflight = null;
  });
  catalogInflight = pending;
  return pending;
}

async function fetchPresence(): Promise<void> {
  if (presenceInflight) return presenceInflight;
  const pending = (async () => {
    try {
      const presence = await httpJson<{ codes: string[]; presenceAvailable: boolean }>(
        "/api/metadata/locales/presence",
      );
      presenceAvailable.value = presence.presenceAvailable === true;
      const codes = new Set(presence.codes || []);
      if (presenceAvailable.value) {
        rows.value = rows.value.map((row) => ({ ...row, present: codes.has(row.code) }));
      }
    } catch {
      presenceAvailable.value = false;
    } finally {
      presenceReady = true;
    }
  })().finally(() => {
    if (presenceInflight === pending) presenceInflight = null;
  });
  presenceInflight = pending;
  return pending;
}

/** Wipe the session cache (explicit reset in tests). */
export function resetLocaleCatalog(): void {
  rows.value = [];
  loading.value = false;
  error.value = "";
  presenceAvailable.value = false;
  catalogReady = false;
  presenceReady = false;
  catalogInflight = null;
  presenceInflight = null;
  cacheGeneration = 0;
  loadCount = 0;
}

/**
 * App Store locale catalog for listing + IAP pickers.
 * Reuses the last catalog in this session; fills presence on demand.
 * A second load() on the same instance refetches (LocalePicker refresh).
 */
export function useLocaleCatalog(opts?: { presence?: boolean }) {
  const { t, locale } = useI18n();
  const withPresence = opts?.presence === true;
  let seenGeneration = 0;

  function labelFor(code: string): string {
    const row = rows.value.find((item) => item.code === code);
    if (!row) return code;
    return optionLabelFor(row, locale.value);
  }

  async function load() {
    const refresh = catalogReady && seenGeneration > 0 && seenGeneration === cacheGeneration;
    const needCatalog = refresh || !catalogReady;
    const needPresence = withPresence && (refresh || !presenceReady);
    if (!needCatalog && !needPresence) {
      seenGeneration = cacheGeneration;
      return;
    }

    loadCount += 1;
    loading.value = true;
    if (needPresence) presenceAvailable.value = false;
    try {
      if (needCatalog) await fetchCatalog(t("metadata.locales_catalog_unavailable"));
      if (withPresence && needPresence) await fetchPresence();
    } finally {
      loadCount -= 1;
      if (loadCount === 0) loading.value = false;
    }
    seenGeneration = cacheGeneration;
  }

  return { rows, loading, error, presenceAvailable, load, labelFor };
}
