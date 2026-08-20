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

export function useLocaleCatalog(opts?: { presence?: boolean }) {
  const { t, locale } = useI18n();
  const withPresence = opts?.presence === true;
  const rows = ref<LocaleCatalogRow[]>([]);
  const loading = ref(false);
  const error = ref("");
  const presenceAvailable = ref(false);

  function labelFor(code: string): string {
    const row = rows.value.find((item) => item.code === code);
    if (!row) return code;
    return optionLabelFor(row, locale.value);
  }

  async function load() {
    loading.value = true;
    error.value = "";
    presenceAvailable.value = false;
    try {
      const data = await httpJson<{ locales: LocaleCatalogRow[] }>("/api/metadata/locales");
      rows.value = data.locales || [];
      if (!withPresence) return;
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
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : t("metadata.locales_catalog_unavailable");
    } finally {
      loading.value = false;
    }
  }

  return { rows, loading, error, presenceAvailable, load, labelFor };
}
