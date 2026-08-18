import { ref } from "vue";

export const LISTING_FIELDS = [
  "name",
  "subtitle",
  "description",
  "keywords",
  "supportUrl",
  "marketingUrl",
  "privacyPolicyUrl",
] as const;

export type ListingField = (typeof LISTING_FIELDS)[number];

export type ListingShot = { file_name: string };
export type ListingLocaleRow = {
  locale: string;
  screenshots?: Record<string, ListingShot[]>;
};
export type ListingFieldDiff = { field: string; status: string };
export type ListingLocaleDiff = { locale: string; fields: ListingFieldDiff[] };

export type LocaleScope = {
  selected: boolean;
  fieldSelected: Record<string, boolean>;
  shotSelected: Record<string, Record<string, boolean>>;
};

const loaded = ref(false);
const dirty = ref(false);
const scopes = ref<Record<string, LocaleScope>>({});

function defaultFields(value = true): Record<string, boolean> {
  return Object.fromEntries(LISTING_FIELDS.map((field) => [field, value]));
}

function emptyScope(selected = true): LocaleScope {
  return { selected, fieldSelected: defaultFields(true), shotSelected: {} };
}

function cloneScope(scope: LocaleScope): LocaleScope {
  const shotSelected: Record<string, Record<string, boolean>> = {};
  for (const [dtype, files] of Object.entries(scope.shotSelected)) {
    shotSelected[dtype] = { ...files };
  }
  return {
    selected: scope.selected,
    fieldSelected: { ...scope.fieldSelected },
    shotSelected,
  };
}

function ensure(locale: string): LocaleScope {
  return scopes.value[locale] || emptyScope();
}

function commit(locale: string, next: LocaleScope) {
  scopes.value = { ...scopes.value, [locale]: next };
}

export function useListingScope() {
  function reset() {
    loaded.value = false;
    dirty.value = false;
    scopes.value = {};
  }

  function markDirty() {
    dirty.value = true;
  }

  function clearDirty() {
    dirty.value = false;
  }

  function hydrateFromLocal(rows: ListingLocaleRow[]) {
    const next = { ...scopes.value };
    for (const row of rows) {
      const existing = next[row.locale];
      const fieldSelected = { ...defaultFields(true), ...(existing?.fieldSelected || {}) };
      const shotSelected: Record<string, Record<string, boolean>> = {
        ...(existing?.shotSelected || {}),
      };
      for (const [dtype, items] of Object.entries(row.screenshots || {})) {
        const prev = shotSelected[dtype] || {};
        const group: Record<string, boolean> = {};
        for (const item of items) {
          group[item.file_name] = prev[item.file_name] ?? true;
        }
        shotSelected[dtype] = group;
      }
      next[row.locale] = {
        selected: existing?.selected ?? true,
        fieldSelected,
        shotSelected,
      };
    }
    scopes.value = next;
    loaded.value = true;
  }

  function setLocaleSelected(locale: string, value: boolean) {
    const cur = cloneScope(ensure(locale));
    cur.selected = value;
    commit(locale, cur);
  }

  function selectAllLocales(value: boolean) {
    const next: Record<string, LocaleScope> = {};
    for (const [locale, scope] of Object.entries(scopes.value)) {
      const copy = cloneScope(scope);
      copy.selected = value;
      next[locale] = copy;
    }
    scopes.value = next;
  }

  function setFieldSelected(locale: string, field: string, value: boolean) {
    const cur = cloneScope(ensure(locale));
    cur.fieldSelected[field] = value;
    commit(locale, cur);
  }

  function selectAllField(field: string, value: boolean) {
    const next: Record<string, LocaleScope> = {};
    for (const [locale, scope] of Object.entries(scopes.value)) {
      const copy = cloneScope(scope);
      copy.fieldSelected[field] = value;
      next[locale] = copy;
    }
    scopes.value = next;
  }

  function allFieldsSelected(field: string): boolean {
    const rows = Object.values(scopes.value);
    return rows.length > 0 && rows.every((scope) => !!scope.fieldSelected[field]);
  }

  function setShotSelected(locale: string, dtype: string, fileName: string, value: boolean) {
    const cur = cloneScope(ensure(locale));
    cur.shotSelected[dtype] = { ...(cur.shotSelected[dtype] || {}), [fileName]: value };
    commit(locale, cur);
  }

  function setGroupSelected(locale: string, dtype: string, fileNames: string[], value: boolean) {
    const cur = cloneScope(ensure(locale));
    const group = { ...(cur.shotSelected[dtype] || {}) };
    for (const name of fileNames) group[name] = value;
    cur.shotSelected[dtype] = group;
    commit(locale, cur);
  }

  function groupAllSelected(locale: string, dtype: string, fileNames: string[]): boolean {
    if (!fileNames.length) return false;
    const group = scopes.value[locale]?.shotSelected[dtype] || {};
    return fileNames.every((name) => group[name]);
  }

  function isLocaleSelected(locale: string): boolean {
    return !!scopes.value[locale]?.selected;
  }

  function isFieldSelected(locale: string, field: string): boolean {
    return !!scopes.value[locale]?.fieldSelected[field];
  }

  function isShotSelected(locale: string, dtype: string, fileName: string): boolean {
    return !!scopes.value[locale]?.shotSelected[dtype]?.[fileName];
  }

  function selectDiffsOnly(diffLocales: ListingLocaleDiff[]) {
    const byLocale: Record<string, Set<string>> = {};
    for (const loc of diffLocales) {
      byLocale[loc.locale] = new Set(
        loc.fields
          .filter((field) => field.status === "changed" || field.status === "local_only")
          .map((field) => field.field),
      );
    }
    const next: Record<string, LocaleScope> = {};
    for (const [locale, scope] of Object.entries(scopes.value)) {
      const set = byLocale[locale];
      const copy = cloneScope(scope);
      if (!set) {
        copy.selected = false;
        copy.fieldSelected = defaultFields(false);
      } else {
        copy.selected = set.size > 0;
        copy.fieldSelected = Object.fromEntries(
          LISTING_FIELDS.map((field) => [field, set.has(field)]),
        );
      }
      next[locale] = copy;
    }
    for (const loc of diffLocales) {
      if (next[loc.locale]) continue;
      const set = byLocale[loc.locale] || new Set();
      if (!set.size) continue;
      next[loc.locale] = {
        selected: true,
        fieldSelected: Object.fromEntries(LISTING_FIELDS.map((field) => [field, set.has(field)])),
        shotSelected: {},
      };
    }
    scopes.value = next;
    loaded.value = true;
  }

  function localesJson(): string {
    if (!loaded.value) return "";
    return JSON.stringify(
      Object.entries(scopes.value)
        .filter(([, scope]) => scope.selected)
        .map(([locale]) => locale),
    );
  }

  function fieldsByLocaleJson(): string {
    if (!loaded.value) return "";
    const out: Record<string, string[]> = {};
    for (const [locale, scope] of Object.entries(scopes.value)) {
      if (!scope.selected) continue;
      out[locale] = LISTING_FIELDS.filter((field) => scope.fieldSelected[field]);
    }
    return JSON.stringify(out);
  }

  function screenshotScopesJson(): string {
    if (!loaded.value) return "";
    const out: Record<string, Record<string, string[]>> = {};
    for (const [locale, scope] of Object.entries(scopes.value)) {
      for (const [dtype, files] of Object.entries(scope.shotSelected)) {
        const names = Object.entries(files)
          .filter(([, on]) => on)
          .map(([name]) => name);
        if (!names.length) continue;
        out[locale] = out[locale] || {};
        out[locale][dtype] = names;
      }
    }
    return JSON.stringify(out);
  }

  function hasMetadataSelection(): boolean {
    if (!loaded.value) return false;
    return Object.values(scopes.value).some(
      (scope) => scope.selected && LISTING_FIELDS.some((field) => scope.fieldSelected[field]),
    );
  }

  function hasScreenshotSelection(): boolean {
    if (!loaded.value) return false;
    return Object.values(scopes.value).some((scope) =>
      Object.values(scope.shotSelected).some((files) => Object.values(files).some(Boolean)),
    );
  }

  return {
    loaded,
    dirty,
    scopes,
    reset,
    markDirty,
    clearDirty,
    hydrateFromLocal,
    setLocaleSelected,
    selectAllLocales,
    setFieldSelected,
    selectAllField,
    allFieldsSelected,
    setShotSelected,
    setGroupSelected,
    groupAllSelected,
    isLocaleSelected,
    isFieldSelected,
    isShotSelected,
    selectDiffsOnly,
    localesJson,
    fieldsByLocaleJson,
    screenshotScopesJson,
    hasMetadataSelection,
    hasScreenshotSelection,
  };
}
