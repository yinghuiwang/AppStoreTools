<script setup lang="ts">
import { computed, inject, onMounted, ref, watch, type Ref } from "vue";
import { useI18n } from "vue-i18n";
import { AddIcon, ChevronDownIcon, ChevronUpIcon } from "tdesign-icons-vue-next";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import ExampleHelp from "@/components/ExampleHelp.vue";
import PageLoading from "@/components/PageLoading.vue";
import { useBrowse } from "@/composables/useBrowse";
import { hydrateListingForm } from "@/composables/useFormMemory";
import { rememberFormPath } from "@/composables/useFormPaths";
import { useImageViewer } from "@/composables/useImageViewer";
import { LISTING_FIELDS, useListingScope } from "@/composables/useListingScope";
import { useProfile } from "@/composables/useProfile";
import LocaleSelectTabs from "@/components/LocaleSelectTabs.vue";
import LocalePicker from "./LocalePicker.vue";

type Shot = { file_name: string; order: number; thumb_url: string; local_path: string; remote_id: string };
type LocaleRow = { locale: string; fields: Record<string, string>; screenshots: Record<string, Shot[]> };
type ShotPick = { kind: "add"; locale: string; displayType: string } | { kind: "replace"; path: string };

const FIELDS = LISTING_FIELDS;

const { t } = useI18n();
const browse = useBrowse();
const viewer = useImageViewer();
const scope = useListingScope();
const { snapshot } = useProfile();
const reloadTick = inject<Ref<number>>("listingReload", ref(0));
const listing = hydrateListingForm(snapshot.value?.current_profile || "", {
  csv: snapshot.value?.paths.csv || "data/appstore_info.csv",
  screenshots: snapshot.value?.paths.screenshots || "data/screenshots",
});
const csvPath = listing.csv_path;
const shotsDir = listing.screenshots_dir;
watch([csvPath, shotsDir], ([csv, shots]) => {
  rememberFormPath("listing.csv_path", csv);
  rememberFormPath("listing.screenshots_dir", shots);
}, { immediate: true });
const locales = ref<LocaleRow[]>([]);
const mtime = ref<number | null>(null);
const conflict = ref(false);
const pickerOpen = ref(false);
const active = ref("");
const alert = ref("");
const loading = ref(false);
const loaded = ref(false);
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const current = computed(() => locales.value.find((row) => row.locale === active.value) || locales.value[0]);
const localeCodes = computed(() => locales.value.map((row) => row.locale));
const selectedCodes = computed(() => localeCodes.value.filter((code) => scope.isLocaleSelected(code)));

function syncSelected(next: string[]) {
  const set = new Set(next);
  const all = localeCodes.value;
  if (next.length === all.length && all.every((code) => set.has(code))) {
    scope.selectAllLocales(true);
    return;
  }
  if (next.length === 0) {
    scope.selectAllLocales(false);
    return;
  }
  for (const code of all) {
    const on = set.has(code);
    if (scope.isLocaleSelected(code) !== on) scope.setLocaleSelected(code, on);
  }
}
const shotFileInput = ref<HTMLInputElement | null>(null);
const shotPick = ref<ShotPick | null>(null);

async function load() {
  alert.value = "";
  conflict.value = false;
  loading.value = true;
  const qs = new URLSearchParams({ csv_path: csvPath.value, screenshots_dir: shotsDir.value });
  try {
    const data = await httpJson<{ ok: boolean; mtime: number | null; snapshot: { locales: LocaleRow[] } }>(
      `/api/listing/local?${qs}`,
    );
    locales.value = data.snapshot?.locales || [];
    mtime.value = data.mtime;
    scope.hydrateFromLocal(locales.value);
    if (!active.value || !locales.value.some((row) => row.locale === active.value)) {
      active.value = locales.value[0]?.locale || "";
    }
    loaded.value = true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  } finally {
    loading.value = false;
  }
}

async function save() {
  conflict.value = false;
  try {
    const data = await httpJson<{ mtime: number }>("/api/listing/local/save", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({
        csv_path: csvPath.value,
        expected_mtime: mtime.value,
        locales: locales.value.map((loc) => ({ locale: loc.locale, fields: loc.fields })),
      }),
    });
    mtime.value = data.mtime;
    scope.clearDirty();
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      conflict.value = true;
      return;
    }
    throw err;
  }
}

async function addShot(locale: string, displayType: string, file: File) {
  const body = new FormData();
  body.set("root", shotsDir.value);
  body.set("locale", locale);
  body.set("display_type", displayType);
  body.set("filename", file.name);
  body.set("file", file);
  await httpJson("/api/listing/screenshots/add", { method: "POST", body });
  await load();
}

async function replaceShot(path: string, file: File) {
  const body = new FormData();
  body.set("root", shotsDir.value);
  body.set("path", path);
  body.set("new_name", file.name);
  body.set("file", file);
  await httpJson("/api/listing/screenshots/replace", { method: "POST", body });
  await load();
}

async function deleteShot(path: string) {
  if (!window.confirm(t("metadata.shots_confirm_delete"))) return;
  await httpJson("/api/listing/screenshots/delete", {
    method: "POST",
    body: JSON.stringify({ root: shotsDir.value, path }),
  });
  await load();
}

async function moveShot(locale: string, displayType: string, index: number, delta: number) {
  const group = current.value?.screenshots[displayType] || [];
  const next = index + delta;
  if (next < 0 || next >= group.length) return;
  const names = group.map((item) => item.file_name);
  const [item] = names.splice(index, 1);
  names.splice(next, 0, item);
  await httpJson("/api/listing/screenshots/reorder", {
    method: "POST",
    body: JSON.stringify({
      root: shotsDir.value,
      locale,
      display_type: displayType,
      file_names: names,
    }),
  });
  await load();
}

function openShots(group: Shot[], start: number) {
  viewer.show(group.map((item) => ({ src: item.thumb_url, title: item.file_name })), start);
}

function openAddShot(locale: string, displayType: string) {
  shotPick.value = { kind: "add", locale, displayType };
  shotFileInput.value?.click();
}

function openReplaceShot(path: string) {
  shotPick.value = { kind: "replace", path };
  shotFileInput.value?.click();
}

function onShotFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  const pick = shotPick.value;
  input.value = "";
  shotPick.value = null;
  if (!file || !pick) return;
  if (pick.kind === "add") void addShot(pick.locale, pick.displayType, file);
  else void replaceShot(pick.path, file);
}

function shotNames(group: Shot[]): string[] {
  return group.map((item) => item.file_name);
}

function dtypeLabel(dtype: string): string {
  return dtype === "UNKNOWN" ? t("metadata.shots_unknown_type") : dtype;
}

watch(
  () => snapshot.value?.current_profile,
  (name, prev) => {
    if (prev !== undefined && name !== prev) scope.reset();
  },
);

onMounted(() => { if (!empty.value) void load(); });
watch(reloadTick, () => { if (!empty.value) void load(); });
</script>

<template>
  <div class="page-stack">
    <t-alert v-if="empty" theme="warning" :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </t-alert>
    <t-alert v-if="alert" theme="error" :title="alert" />
    <t-alert v-if="conflict" theme="warning" :title="t('metadata.wb_conflict')">
      <t-button size="small" @click="load">{{ t("metadata.load_preview") }}</t-button>
    </t-alert>
    <div class="card">
      <p>{{ t("metadata.wb_hint") }}</p>
      <div class="field">
        <ExampleHelp kind="csv" :label="t('metadata.csv_path')" />
        <div class="field-row">
          <input v-model="csvPath" class="field-input" />
          <t-button @click="browse.pick({ mode: 'file', ext: '.csv', initialPath: csvPath }).then((p) => { if (p) csvPath = p; })">{{ t("filebrowser.browse") }}</t-button>
        </div>
      </div>
      <div class="field">
        <ExampleHelp kind="shots" :label="t('metadata.shots_dir')" />
        <div class="field-row">
          <input v-model="shotsDir" class="field-input" />
          <t-button @click="browse.pick({ mode: 'dir', initialPath: shotsDir }).then((p) => { if (p) shotsDir = p; })">{{ t("filebrowser.browse") }}</t-button>
        </div>
      </div>
      <div class="field-row">
        <t-button
          :disabled="empty || (loading && !loaded)"
          :loading="loading && loaded"
          @click="load"
        >{{ t("metadata.load_preview") }}</t-button>
        <t-button theme="primary" :disabled="empty" @click="save">{{ t("metadata.save_csv") }}</t-button>
        <t-button @click="pickerOpen = true">{{ t("metadata.locales_btn") }}</t-button>
        <span v-if="scope.dirty.value" class="unsaved">{{ t("metadata.unsaved") }}</span>
      </div>
    </div>
    <PageLoading v-if="loading && !loaded" size="page" />
    <p v-else-if="!locales.length" class="empty-state">{{ t("metadata.wb_empty") }}</p>
    <div v-else class="workbench">
      <LocaleSelectTabs
        v-model="active"
        :locales="localeCodes"
        :selected="selectedCodes"
        @update:selected="syncSelected"
      >
      <div v-if="current" class="card editors">
        <div class="col-select">
          <span class="lbl">{{ t("metadata.col_upload") }}</span>
          <label v-for="field in FIELDS" :key="`col-${field}`" class="check">
            <input
              type="checkbox"
              :checked="scope.allFieldsSelected(field)"
              @change="scope.selectAllField(field, ($event.target as HTMLInputElement).checked)"
            />
            {{ t(`metadata.field_${field}`) }}
          </label>
        </div>
        <label v-for="field in FIELDS" :key="field" class="field field-with-check">
          <span>
            <input
              type="checkbox"
              :checked="scope.isFieldSelected(current.locale, field)"
              @change="scope.setFieldSelected(current.locale, field, ($event.target as HTMLInputElement).checked)"
            />
            {{ t(`metadata.field_${field}`) }}
          </span>
          <textarea
            v-if="field === 'description'"
            v-model="current.fields[field]"
            rows="6"
            class="field-input"
            @input="scope.markDirty()"
          />
          <input
            v-else
            v-model="current.fields[field]"
            class="field-input"
            @input="scope.markDirty()"
          />
        </label>
        <h3>{{ t("metadata.shots_section") }}</h3>
        <input
          ref="shotFileInput"
          class="file-hidden"
          type="file"
          accept="image/png,image/jpeg"
          tabindex="-1"
          @change="onShotFileChange"
        />
        <div v-if="!Object.keys(current.screenshots || {}).length" class="empty-shots">
          <p class="muted">{{ t("metadata.shots_empty") }}</p>
          <t-button size="small" @click="openAddShot(current.locale, '')">
            <template #icon><AddIcon /></template>
            {{ t("metadata.shots_add") }}
          </t-button>
        </div>
        <div v-for="(group, dtype) in current.screenshots" :key="dtype" class="shots">
          <div class="shot-head">
            <label class="check">
              <input
                type="checkbox"
                :checked="scope.groupAllSelected(current.locale, String(dtype), shotNames(group))"
                @change="scope.setGroupSelected(current.locale, String(dtype), shotNames(group), ($event.target as HTMLInputElement).checked)"
              />
              <strong>{{ dtypeLabel(String(dtype)) }}</strong>
            </label>
            <t-button size="small" @click="openAddShot(current.locale, String(dtype))">
              <template #icon><AddIcon /></template>
              {{ t("metadata.shots_add") }}
            </t-button>
          </div>
          <div class="thumbs">
            <figure v-for="(item, idx) in group" :key="item.local_path || item.file_name" class="thumb">
              <div class="thumb-frame">
                <img :src="item.thumb_url" :alt="item.file_name" @click="openShots(group, idx)" />
                <input
                  type="checkbox"
                  class="thumb-check"
                  :checked="scope.isShotSelected(current.locale, String(dtype), item.file_name)"
                  @change="scope.setShotSelected(current.locale, String(dtype), item.file_name, ($event.target as HTMLInputElement).checked)"
                  @click.stop
                />
              </div>
              <figcaption :title="item.file_name">{{ item.file_name }}</figcaption>
              <div class="thumb-actions">
                <t-button
                  size="small"
                  shape="square"
                  :disabled="idx === 0"
                  :title="t('metadata.shots_move_up')"
                  :aria-label="t('metadata.shots_move_up')"
                  @click="moveShot(current.locale, String(dtype), idx, -1)"
                >
                  <template #icon><ChevronUpIcon /></template>
                </t-button>
                <t-button
                  size="small"
                  shape="square"
                  :disabled="idx === group.length - 1"
                  :title="t('metadata.shots_move_down')"
                  :aria-label="t('metadata.shots_move_down')"
                  @click="moveShot(current.locale, String(dtype), idx, 1)"
                >
                  <template #icon><ChevronDownIcon /></template>
                </t-button>
                <t-button size="small" @click="openReplaceShot(item.local_path)">{{ t("metadata.shots_replace") }}</t-button>
                <t-button size="small" theme="danger" variant="outline" @click="deleteShot(item.local_path)">{{ t("metadata.shots_delete") }}</t-button>
              </div>
            </figure>
          </div>
        </div>
      </div>
      </LocaleSelectTabs>
    </div>
  </div>
  <LocalePicker v-model:open="pickerOpen" />
</template>

<style scoped>
.workbench {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-width: 0;
}
.editors { position: relative; display: flex; flex-direction: column; gap: 10px; }
.unsaved { color: var(--accent); font-size: 12px; }
.col-select { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; }
.field-with-check span { display: flex; align-items: center; gap: 8px; }
.check { display: flex; gap: 8px; align-items: center; }
.lbl { font-size: 12px; color: var(--text-muted); }
.muted { color: var(--text-muted); }
.empty-shots { display: flex; align-items: center; gap: 12px; }
.thumbs { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
.thumb { margin: 0; width: 148px; display: flex; flex-direction: column; gap: 6px; }
.thumb-frame { position: relative; }
.thumb img { width: 148px; height: 254px; object-fit: cover; border-radius: 8px; border: 1px solid var(--border); cursor: zoom-in; display: block; }
.thumb-check { position: absolute; top: 6px; left: 6px; }
figcaption { font-size: 11px; color: var(--text-muted); word-break: break-all; line-height: 1.3; }
.thumb-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
.thumb-actions :deep(.t-button) { margin: 0; width: 100%; }
.file-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
  opacity: 0;
  pointer-events: none;
}
.shot-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 8px 0; }
</style>
