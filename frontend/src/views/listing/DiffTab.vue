<script setup lang="ts">
import { computed, inject, onActivated, onMounted, ref, watch, type Ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import PageLoading from "@/components/PageLoading.vue";
import { rememberFormPath } from "@/composables/useFormPaths";
import { useImageViewer } from "@/composables/useImageViewer";
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
const viewer = useImageViewer();
const rail = useRightRail();
const { listingTab } = useListingTab();
const { setActiveTask, channelOf } = useTaskLog();
const reloadTick = inject<Ref<number>>("listingReload", ref(0));
const csvPath = ref(snapshot.value?.paths.csv || "data/appstore_info.csv");
const shotsDir = ref(snapshot.value?.paths.screenshots || "data/screenshots");
watch([csvPath, shotsDir], ([csv, shots]) => {
  rememberFormPath("listing.csv_path", csv);
  rememberFormPath("listing.screenshots_dir", shots);
}, { immediate: true });
const mtime = ref<number | null>(null);
const version = ref<Version | null>(null);
const locales = ref<LocaleDiff[]>([]);
const filter = ref<"all" | "diff">("all");
const selected = ref<Record<string, string[]>>({});
const selectedScopes = ref<Record<string, boolean>>({});
const alert = ref<{ level: string; message: string } | null>(null);
const conflict = ref(false);
const pullTaskId = ref("");
const pullLog = channelOf(pullTaskId);
const loading = ref(false);
const loaded = ref(false);

const visible = computed(() => {
  if (filter.value === "all") return locales.value;
  return locales.value.filter((loc) =>
    loc.fields.some((f) => f.status !== "equal") || loc.screenshots.length,
  );
});

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
  if (!window.confirm(t("metadata.diff_shots_confirm", { count: scopes.length }))) return;
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
  if (tab === "diff" && pullTaskId.value) setActiveTask(pullTaskId.value);
});

onActivated(() => {
  if (listingTab.value === "diff" && pullTaskId.value) setActiveTask(pullTaskId.value);
});

onMounted(() => { void load(); });
</script>

<template>
  <div class="page-stack">
    <el-alert v-if="alert" :type="(alert.level === 'warning' ? 'warning' : 'error')" show-icon :title="alert.message" />
    <el-alert v-if="conflict" type="warning" show-icon :title="t('metadata.wb_conflict')">
      <el-button size="small" @click="load">{{ t("metadata.diff_reload") }}</el-button>
    </el-alert>
    <div class="card">
      <p>{{ t("metadata.diff_hint") }}</p>
      <p v-if="version">{{ t("metadata.diff_version", { version: version.versionString || "", state: version.appStoreState || "" }) }}</p>
      <div class="field-row">
        <el-button
          :loading="loading && loaded"
          :disabled="loading && !loaded"
          @click="load"
        >{{ t("metadata.diff_load") }}</el-button>
        <el-button @click="filter = 'all'">{{ t("metadata.diff_filter_all") }}</el-button>
        <el-button @click="filter = 'diff'">{{ t("metadata.diff_filter_diff") }}</el-button>
        <el-button type="primary" @click="pullText">{{ t("metadata.diff_pull") }}</el-button>
        <el-button @click="pullShots">{{ t("metadata.diff_shots_pull") }}</el-button>
      </div>
    </div>
    <PageLoading v-if="loading && !loaded" size="block" />
    <p v-else-if="!locales.length" class="empty-state">{{ t("metadata.diff_empty") }}</p>
    <section v-for="loc in visible" :key="loc.locale" class="card">
      <h3>{{ loc.locale }}</h3>
      <table>
        <thead>
          <tr>
            <th></th>
            <th>{{ t("metadata.diff_col_field") }}</th>
            <th>{{ t("metadata.diff_status_changed") }}</th>
            <th>{{ t("metadata.diff_local") }}</th>
            <th>{{ t("metadata.diff_asc") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="field in loc.fields" :key="field.field" v-show="filter === 'all' || field.status !== 'equal'">
            <td>
              <input
                type="checkbox"
                :checked="(selected[loc.locale] || []).includes(field.field)"
                @change="toggleField(loc.locale, field.field, ($event.target as HTMLInputElement).checked)"
              />
            </td>
            <td>{{ t(`metadata.field_${field.field}`) }}</td>
            <td>{{ t(`metadata.diff_status_${field.status}`) }}</td>
            <td class="mono">{{ field.local }}</td>
            <td class="mono">{{ field.asc }}</td>
          </tr>
        </tbody>
      </table>
      <h4>{{ t("metadata.diff_shots_heading") }}</h4>
      <p class="muted">{{ t("metadata.diff_shots_note") }}</p>
      <div v-for="shot in loc.screenshots" :key="shot.display_type" class="shot-block">
        <label class="check">
          <input v-model="selectedScopes[scopeKey(loc.locale, shot.display_type)]" type="checkbox" />
          {{ shot.display_type }}
        </label>
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
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th, td { border-bottom: 1px solid var(--border); padding: 6px; vertical-align: top; }
.muted { color: var(--text-muted); font-size: 12px; }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.cols img { width: 72px; height: 128px; object-fit: cover; margin: 4px; border-radius: 6px; cursor: zoom-in; border: 1px solid var(--border); }
.check { display: flex; gap: 8px; align-items: center; margin: 8px 0; }
.shot-block { margin-top: 10px; }
</style>
