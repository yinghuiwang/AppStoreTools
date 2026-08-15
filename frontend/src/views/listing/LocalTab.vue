<script setup lang="ts">
import { computed, inject, onMounted, ref, watch, type Ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import { useBrowse } from "@/composables/useBrowse";
import { useImageViewer } from "@/composables/useImageViewer";
import { useProfile } from "@/composables/useProfile";
import LocalePicker from "./LocalePicker.vue";

type Shot = { file_name: string; order: number; thumb_url: string; local_path: string; remote_id: string };
type LocaleRow = { locale: string; fields: Record<string, string>; screenshots: Record<string, Shot[]> };

const FIELDS = ["name", "subtitle", "description", "keywords", "supportUrl", "marketingUrl", "privacyPolicyUrl"];

const { t } = useI18n();
const browse = useBrowse();
const viewer = useImageViewer();
const { snapshot } = useProfile();
const reloadTick = inject<Ref<number>>("listingReload", ref(0));
const csvPath = ref(snapshot.value?.paths.csv || "data/appstore_info.csv");
const shotsDir = ref(snapshot.value?.paths.screenshots || "data/screenshots");
const locales = ref<LocaleRow[]>([]);
const mtime = ref<number | null>(null);
const conflict = ref(false);
const pickerOpen = ref(false);
const active = ref("");
const alert = ref("");
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const current = computed(() => locales.value.find((row) => row.locale === active.value) || locales.value[0]);

async function load() {
  alert.value = "";
  conflict.value = false;
  const qs = new URLSearchParams({ csv_path: csvPath.value, screenshots_dir: shotsDir.value });
  try {
    const data = await httpJson<{ ok: boolean; mtime: number | null; snapshot: { locales: LocaleRow[] } }>(
      `/api/listing/local?${qs}`,
    );
    locales.value = data.snapshot?.locales || [];
    mtime.value = data.mtime;
    if (!active.value || !locales.value.some((row) => row.locale === active.value)) {
      active.value = locales.value[0]?.locale || "";
    }
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
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

onMounted(() => { if (!empty.value) void load(); });
watch(reloadTick, () => { if (!empty.value) void load(); });
</script>

<template>
  <div class="page-stack">
    <el-alert v-if="empty" type="warning" show-icon :title="t('index.no_app')">
      <router-link to="/system/profiles">{{ t("nav.system") }}</router-link>
    </el-alert>
    <el-alert v-if="alert" type="error" show-icon :title="alert" />
    <el-alert v-if="conflict" type="warning" show-icon :title="t('metadata.wb_conflict')">
      <el-button size="small" @click="load">{{ t("metadata.load_preview") }}</el-button>
    </el-alert>
    <div class="card">
      <p>{{ t("metadata.wb_hint") }}</p>
      <label class="field">
        <span>{{ t("metadata.csv_path") }}</span>
        <div class="field-row">
          <input v-model="csvPath" class="field-input" />
          <el-button @click="browse.pick({ mode: 'file', ext: '.csv', initialPath: csvPath }).then((p) => { if (p) csvPath = p; })">{{ t("filebrowser.browse") }}</el-button>
        </div>
      </label>
      <label class="field">
        <span>{{ t("metadata.shots_dir") }}</span>
        <div class="field-row">
          <input v-model="shotsDir" class="field-input" />
          <el-button @click="browse.pick({ mode: 'dir', initialPath: shotsDir }).then((p) => { if (p) shotsDir = p; })">{{ t("filebrowser.browse") }}</el-button>
        </div>
      </label>
      <div class="field-row">
        <el-button :disabled="empty" @click="load">{{ t("metadata.load_preview") }}</el-button>
        <el-button type="primary" :disabled="empty" @click="save">{{ t("metadata.save_csv") }}</el-button>
        <el-button @click="pickerOpen = true">{{ t("metadata.locales_btn") }}</el-button>
        <a href="/api/examples/csv">{{ t("common.download_sample_csv") }}</a>
        <a href="/api/examples/screenshots">{{ t("common.download_sample_shots") }}</a>
      </div>
    </div>
    <p v-if="!locales.length" class="empty-state">{{ t("metadata.wb_empty") }}</p>
    <div v-else class="workbench">
      <aside>
        <button
          v-for="row in locales"
          :key="row.locale"
          type="button"
          :class="{ on: row.locale === current?.locale }"
          @click="active = row.locale"
        >{{ row.locale }}</button>
      </aside>
      <div v-if="current" class="card editors">
        <label v-for="field in FIELDS" :key="field" class="field">
          <span>{{ t(`metadata.field_${field}`) }}</span>
          <textarea v-if="field === 'description'" v-model="current.fields[field]" rows="6" class="field-input" />
          <input v-else v-model="current.fields[field]" class="field-input" />
        </label>
        <h3>{{ t("metadata.shots_section") }}</h3>
        <p v-if="!Object.keys(current.screenshots || {}).length" class="muted">{{ t("metadata.shots_empty") }}</p>
        <div v-for="(group, dtype) in current.screenshots" :key="dtype" class="shots">
          <div class="shot-head">
            <strong>{{ dtype }}</strong>
            <label class="add">
              {{ t("metadata.shots_add") }}
              <input type="file" accept="image/png,image/jpeg" @change="(e) => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) addShot(current.locale, String(dtype), f); }" />
            </label>
          </div>
          <div class="thumbs">
            <figure v-for="(item, idx) in group" :key="item.local_path || item.file_name">
              <img :src="item.thumb_url" :alt="item.file_name" @click="openShots(group, idx)" />
              <figcaption>{{ item.file_name }}</figcaption>
              <div class="field-row">
                <el-button size="small" @click="moveShot(current.locale, String(dtype), idx, -1)">↑</el-button>
                <el-button size="small" @click="moveShot(current.locale, String(dtype), idx, 1)">↓</el-button>
                <label class="add">
                  {{ t("metadata.shots_replace") }}
                  <input type="file" accept="image/png,image/jpeg" @change="(e) => { const f = (e.target as HTMLInputElement).files?.[0]; if (f) replaceShot(item.local_path, f); }" />
                </label>
                <el-button size="small" @click="deleteShot(item.local_path)">{{ t("metadata.shots_delete") }}</el-button>
              </div>
            </figure>
          </div>
        </div>
      </div>
    </div>
    <LocalePicker v-model:open="pickerOpen" />
  </div>
</template>

<style scoped>
.workbench { display: grid; grid-template-columns: 180px 1fr; gap: 16px; }
aside { display: flex; flex-direction: column; gap: 4px; }
aside button { text-align: left; background: var(--surface); color: var(--text-muted); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
aside button.on { color: var(--accent); border-color: var(--accent-dim); }
.editors { display: flex; flex-direction: column; gap: 10px; }
.muted { color: var(--text-muted); }
.thumbs { display: flex; flex-wrap: wrap; gap: 12px; }
figure { margin: 0; width: 140px; }
figure img { width: 140px; height: 240px; object-fit: cover; border-radius: 8px; border: 1px solid var(--border); cursor: zoom-in; }
figcaption { font-size: 11px; color: var(--text-muted); word-break: break-all; }
.add { font-size: 12px; color: var(--accent); }
.add input { display: block; margin-top: 4px; }
.shot-head { display: flex; justify-content: space-between; align-items: center; margin: 8px 0; }
@media (max-width: 1100px) { .workbench { grid-template-columns: 1fr; } }
</style>
