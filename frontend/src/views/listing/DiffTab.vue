<script setup lang="ts">
import { computed, inject, onActivated, ref, watch, type Ref } from "vue";
import { useI18n } from "vue-i18n";
import { DialogPlugin, MessagePlugin } from "tdesign-vue-next";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import PageLoading from "@/components/PageLoading.vue";
import { hydrateListingForm } from "@/composables/useFormMemory";
import { rememberFormPath } from "@/composables/useFormPaths";
import { useImageViewer } from "@/composables/useImageViewer";
import { useListingScope } from "@/composables/useListingScope";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";
import { useListingTab } from "@/composables/useTaskPagePhase";

type Shot = { file_name: string; order: number; thumb_url: string; local_path: string; remote_id: string };
type FieldDiff = { field: string; status: string; local: string; asc: string };
type ShotDiff = { display_type: string; local: Shot[]; asc: Shot[] };
type LocaleDiff = { locale: string; fields: FieldDiff[]; screenshots: ShotDiff[] };
type Version = { versionString?: string; appStoreState?: string };

const { t } = useI18n();
const { snapshot } = useProfile();
const scope = useListingScope();
const viewer = useImageViewer();
const rail = useRightRail();
const { listingTab } = useListingTab();
const { setActiveTask, channelOf } = useTaskLog();
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
const mtime = ref<number | null>(null);
const version = ref<Version | null>(null);
const locales = ref<LocaleDiff[]>([]);
const filter = ref<"all" | "diff" | "local" | "asc">("all");
const selected = ref<Record<string, string[]>>({});
const selectedScopes = ref<Record<string, boolean>>({});
const alert = ref<{ level: string; message: string } | null>(null);
const conflict = ref(false);
const pullTaskId = ref("");
const pullLog = channelOf(pullTaskId);
const loading = ref(false);
const loaded = ref(false);

function fieldVisible(field: FieldDiff): boolean {
  if (filter.value === "all") return true;
  if (filter.value === "diff") return field.status !== "equal";
  if (filter.value === "local") return field.status === "local_only";
  if (filter.value === "asc") return field.status === "asc_only";
  return true;
}

const visible = computed(() =>
  locales.value.filter((loc) => loc.fields.some(fieldVisible) || loc.screenshots.length > 0),
);

const diffColumns = computed(() => [
  { colKey: "check", title: "", width: 48 },
  { colKey: "field", title: t("metadata.diff_col_field") },
  { colKey: "status", title: t("metadata.diff_status_changed") },
  { colKey: "local", title: t("metadata.diff_local") },
  { colKey: "asc", title: t("metadata.diff_asc") },
]);

function visibleFields(loc: LocaleDiff) {
  return loc.fields.filter(fieldVisible);
}

function guardDirty(): boolean {
  if (!scope.dirty.value) return false;
  MessagePlugin.warning(t("metadata.diff_dirty_block"));
  return true;
}

function selectDiffsOnly() {
  scope.selectDiffsOnly(locales.value);
}

function scopeKey(locale: string, dtype: string) {
  return `${locale}::${dtype}`;
}

function toggleField(locale: string, field: string, on: boolean) {
  const cur = selected.value[locale] || [];
  selected.value = {
    ...selected.value,
    [locale]: on ? Array.from(new Set([...cur, field])) : cur.filter((item) => item !== field),
  };
}

function ascSrc(item: Shot, full = false) {
  const id = item.remote_id;
  if (!id) return item.thumb_url;
  return full
    ? `/api/listing/asc-image?screenshot_id=${encodeURIComponent(id)}`
    : `/api/listing/asc-thumb?screenshot_id=${encodeURIComponent(id)}`;
}

function openAsc(group: Shot[], start: number) {
  viewer.show(group.map((item) => ({ src: ascSrc(item, true) || ascSrc(item), title: item.file_name })), start);
}

function openLocal(group: Shot[], start: number) {
  viewer.show(group.map((item) => ({ src: item.thumb_url, title: item.file_name })), start);
}

async function load() {
  if (guardDirty()) return;
  alert.value = null;
  conflict.value = false;
  loading.value = true;
  try {
    const qs = new URLSearchParams({ csv_path: csvPath.value, screenshots_dir: shotsDir.value });
    const data = await httpJson<{
      ok: boolean;
      level?: string;
      message?: string;
      mtime: number | null;
      version?: Version;
      diff?: { locales: LocaleDiff[] };
    }>(`/api/listing/diff?${qs}`, { skipNotify: true });
    if (data.ok === false && data.message) {
      alert.value = { level: data.level || "error", message: data.message };
      locales.value = [];
      return;
    }
    mtime.value = data.mtime;
    version.value = data.version || null;
    locales.value = data.diff?.locales || [];
  } catch (err) {
    if (err instanceof ApiError) {
      const d = err.detail as { level?: string; message?: string };
      if (d && typeof d === "object" && d.message) {
        alert.value = { level: d.level || "error", message: d.message };
        return;
      }
      alert.value = { level: "error", message: apiErrorMessage(err) };
      return;
    }
    throw err;
  } finally {
    loaded.value = true;
    loading.value = false;
  }
}

async function pullText() {
  if (guardDirty()) return;
  const selections = Object.entries(selected.value)
    .map(([locale, fields]) => ({ locale, fields }))
    .filter((row) => row.fields.length);
  if (!selections.length) {
    alert.value = { level: "warning", message: t("metadata.diff_no_selection") };
    return;
  }
  try {
    await httpJson("/api/listing/pull/text", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({
        csv_path: csvPath.value,
        expected_mtime: mtime.value,
        selections,
      }),
    });
    reloadTick.value += 1;
    await load();
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      conflict.value = true;
      return;
    }
    throw err;
  }
}

async function pullShots() {
  if (guardDirty()) return;
  const scopes = Object.entries(selectedScopes.value)
    .filter(([, on]) => on)
    .map(([key]) => {
      const [locale, display_type] = key.split("::");
      return { locale, display_type };
    });
  if (!scopes.length) {
    alert.value = { level: "warning", message: t("metadata.diff_shots_no_selection") };
    return;
  }
  const confirmed = await new Promise<boolean>((resolve) => {
    const dia = DialogPlugin.confirm({
      body: t("metadata.diff_shots_confirm", { count: scopes.length }),
      onConfirm: () => {
        resolve(true);
        dia.hide();
      },
      onClose: () => resolve(false),
    });
  });
  if (!confirmed) return;
  const { task_id } = await httpJson<{ task_id: string }>("/api/listing/pull/screenshots", {
    method: "POST",
    body: JSON.stringify({ screenshots_dir: shotsDir.value, scopes }),
  });
  pullTaskId.value = task_id;
  rail.openLogs(task_id);
}

watch(
  () => pullLog.status.value,
  (st) => {
    if (pullTaskId.value && st === "done") {
      reloadTick.value += 1;
      void load();
    }
  },
);

watch(listingTab, (tab) => {
  if (tab !== "diff") return;
  if (pullTaskId.value) setActiveTask(pullTaskId.value);
  if (!loaded.value && !loading.value) void load();
}, { immediate: true });

onActivated(() => {
  if (listingTab.value === "diff" && pullTaskId.value) setActiveTask(pullTaskId.value);
});
</script>

<template>
  <div class="page-stack">
    <t-alert v-if="alert" :theme="(alert.level === 'warning' ? 'warning' : 'error')" :title="alert.message" />
    <t-alert v-if="conflict" theme="warning" :title="t('metadata.wb_conflict')">
      <t-button size="small" @click="load">{{ t("metadata.diff_reload") }}</t-button>
    </t-alert>
    <div class="card">
      <p>{{ t("metadata.diff_hint") }}</p>
      <p v-if="version">{{ t("metadata.diff_version", { version: version.versionString || "", state: version.appStoreState || "" }) }}</p>
      <div class="field-row">
        <t-button
          :loading="loading && loaded"
          :disabled="loading && !loaded"
          @click="load"
        >{{ t("metadata.diff_load") }}</t-button>
        <t-radio-group v-model="filter" variant="default-filled" size="small">
          <t-radio-button value="all">{{ t("metadata.diff_filter_all") }}</t-radio-button>
          <t-radio-button value="diff">{{ t("metadata.diff_filter_diff") }}</t-radio-button>
          <t-radio-button value="local">{{ t("metadata.diff_filter_local") }}</t-radio-button>
          <t-radio-button value="asc">{{ t("metadata.diff_filter_asc") }}</t-radio-button>
        </t-radio-group>
        <t-button @click="selectDiffsOnly">{{ t("metadata.diff_select_diffs") }}</t-button>
        <t-button theme="primary" @click="pullText">{{ t("metadata.diff_pull") }}</t-button>
        <t-button @click="pullShots">{{ t("metadata.diff_shots_pull") }}</t-button>
      </div>
    </div>
    <PageLoading v-if="listingTab === 'diff' && loading && !loaded" size="page" />
    <t-empty v-else-if="!locales.length" :description="t('metadata.diff_empty')" />
    <section v-for="loc in visible" :key="loc.locale" class="card">
      <h3>{{ loc.locale }}</h3>
      <t-table :data="visibleFields(loc)" :columns="diffColumns" row-key="field" size="small">
        <template #check="{ row }">
          <t-checkbox
            :checked="(selected[loc.locale] || []).includes(row.field)"
            @change="(on: boolean) => toggleField(loc.locale, row.field, on)"
          />
        </template>
        <template #field="{ row }">{{ t(`metadata.field_${row.field}`) }}</template>
        <template #status="{ row }">{{ t(`metadata.diff_status_${row.status}`) }}</template>
        <template #local="{ row }"><span class="mono">{{ row.local }}</span></template>
        <template #asc="{ row }"><span class="mono">{{ row.asc }}</span></template>
      </t-table>
      <h4>{{ t("metadata.diff_shots_heading") }}</h4>
      <p class="muted">{{ t("metadata.diff_shots_note") }}</p>
      <div v-for="shot in loc.screenshots" :key="shot.display_type" class="shot-block">
        <t-checkbox v-model="selectedScopes[scopeKey(loc.locale, shot.display_type)]">
          {{ shot.display_type }}
        </t-checkbox>
        <div class="cols">
          <div>
            <strong>{{ t("metadata.diff_local") }}</strong>
            <img v-for="(item, idx) in shot.local" :key="item.local_path || item.file_name" :src="item.thumb_url" :alt="item.file_name" @click="openLocal(shot.local, idx)" />
          </div>
          <div>
            <strong>{{ t("metadata.diff_asc") }}</strong>
            <img v-for="(item, idx) in shot.asc" :key="item.remote_id || item.file_name" :src="ascSrc(item)" :alt="item.file_name" @click="openAsc(shot.asc, idx)" />
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
h3, h4 { margin: 0 0 8px; }
.muted { color: var(--text-muted); font-size: 12px; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.cols img { width: 72px; height: 128px; object-fit: cover; margin: 4px; border-radius: 6px; cursor: zoom-in; border: 1px solid var(--border); }
.shot-block { margin-top: 10px; }
</style>
