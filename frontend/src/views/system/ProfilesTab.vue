<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import { httpJson } from "@/api/http";
import ExampleHelp from "@/components/ExampleHelp.vue";
import PageLoading from "@/components/PageLoading.vue";
import { useBrowse } from "@/composables/useBrowse";
import { rememberFormPath } from "@/composables/useFormPaths";
import { useProfile } from "@/composables/useProfile";

type Detail = {
  issuer_id: string;
  key_id: string;
  key_file_name: string;
  app_id: string;
  csv: string;
  screenshots: string;
  already_bound?: boolean;
};

const { t } = useI18n();
const browse = useBrowse();
const { refresh } = useProfile();
const profiles = ref<string[]>([]);
const details = ref<Record<string, Detail>>({});
const defaultName = ref("");
const canCreate = ref(true);
const dialog = ref(false);
const loading = ref(true);
const loaded = ref(false);
const editing = ref("");
const keyFile = ref<File | null>(null);
const form = reactive({
  name: "",
  issuer_id: "",
  key_id: "",
  app_id: "",
  csv: "data/appstore_info.csv",
  screenshots: "data/screenshots",
});

const rows = computed(() =>
  profiles.value.map((name) => {
    const d = details.value[name];
    return {
      name,
      app_id: d?.app_id || "—",
      issuer_id: d?.issuer_id || "—",
      isDefault: name === defaultName.value,
    };
  }),
);

async function load() {
  if (!loaded.value) loading.value = true;
  try {
    const data = await httpJson<{
      profiles: string[];
      default: string;
      profile_details: Record<string, Detail>;
      can_create: boolean;
    }>("/api/profiles");
    profiles.value = data.profiles || [];
    details.value = data.profile_details || {};
    defaultName.value = data.default || "";
    canCreate.value = data.can_create !== false;
    loaded.value = true;
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editing.value = "";
  Object.assign(form, {
    name: "", issuer_id: "", key_id: "", app_id: "",
    csv: "data/appstore_info.csv", screenshots: "data/screenshots",
  });
  keyFile.value = null;
  dialog.value = true;
}

function openEdit(name: string) {
  const d = details.value[name] || ({} as Detail);
  editing.value = name;
  Object.assign(form, {
    name, issuer_id: d.issuer_id, key_id: d.key_id, app_id: d.app_id,
    csv: d.csv || "data/appstore_info.csv", screenshots: d.screenshots || "data/screenshots",
  });
  keyFile.value = null;
  dialog.value = true;
}

async function pickCsv() {
  const path = await browse.pick({ mode: "file", ext: ".csv", initialPath: form.csv });
  if (path) form.csv = path;
}

async function pickShots() {
  const path = await browse.pick({ mode: "dir", initialPath: form.screenshots });
  if (path) form.screenshots = path;
}

async function save() {
  const body = new FormData();
  body.set("name", form.name);
  body.set("issuer_id", form.issuer_id);
  body.set("key_id", form.key_id);
  body.set("app_id", form.app_id);
  body.set("csv", form.csv);
  body.set("screenshots", form.screenshots);
  rememberFormPath("profile.csv", form.csv);
  rememberFormPath("profile.screenshots", form.screenshots);
  if (keyFile.value) body.set("key_file", keyFile.value);
  if (editing.value) {
    await httpJson(`/api/profiles/${encodeURIComponent(editing.value)}`, { method: "PUT", body });
  } else {
    if (!keyFile.value) {
      ElMessage.error("key_file");
      return;
    }
    await httpJson("/api/profiles", { method: "POST", body });
  }
  dialog.value = false;
  await load();
  await refresh();
}

async function remove(name: string) {
  if (!window.confirm(t("profiles.confirm_delete", { name }))) return;
  await httpJson(`/api/profiles/${encodeURIComponent(name)}`, { method: "DELETE" });
  await load();
  await refresh();
}

async function setDefault(name: string) {
  await httpJson(`/api/profiles/${encodeURIComponent(name)}/set-default`, { method: "POST" });
  await load();
}

async function importLocal() {
  const found = await httpJson<{ candidates: { suggested_name?: string }[] }>("/api/profiles/discover-local");
  const name = found.candidates?.[0]?.suggested_name || "";
  await httpJson("/api/profiles/import", {
    method: "POST",
    body: JSON.stringify({ name, set_default: true }),
  });
  await load();
  await refresh();
}

onMounted(() => { void load(); });
</script>

<template>
  <div class="page-stack profiles-page">
    <div class="card">
      <div class="toolbar">
        <el-button type="primary" :disabled="!canCreate" :title="canCreate ? t('profiles.add_title') : t('profiles.cannot_create')" @click="openCreate">{{ t("profiles.add") }}</el-button>
        <el-button @click="importLocal">{{ t("profiles.import_confirm") }}</el-button>
      </div>
      <PageLoading v-if="loading && !loaded" size="block" />
      <p v-else-if="!rows.length" class="empty-state">
        {{ t("profiles.empty") }}
        <span class="empty-hint">{{ t("profiles.empty_hint") }}</span>
      </p>
      <div v-else class="profile-list">
        <article v-for="row in rows" :key="row.name" class="profile-card">
          <header class="profile-head">
            <span class="name mono">{{ row.name }}</span>
            <span v-if="row.isDefault" class="badge">{{ t("common.default") }}</span>
          </header>
          <div class="actions">
            <el-button size="small" @click="openEdit(row.name)">{{ t("common.edit") }}</el-button>
            <el-button v-if="!row.isDefault" size="small" @click="setDefault(row.name)">{{ t("common.set_default") }}</el-button>
            <el-button size="small" @click="remove(row.name)">{{ t("common.delete") }}</el-button>
          </div>
          <dl class="profile-meta">
            <div class="meta-item">
              <dt>App ID</dt>
              <dd class="mono">{{ row.app_id }}</dd>
            </div>
            <div class="meta-item">
              <dt>Issuer</dt>
              <dd class="mono">{{ row.issuer_id }}</dd>
            </div>
          </dl>
        </article>
      </div>
    </div>
  </div>
  <el-dialog v-model="dialog" :title="editing ? t('common.edit') : t('profiles.create')" width="520px">
    <div class="page-stack">
      <label class="field"><span>{{ t("profiles.name") }}</span><input v-model="form.name" class="field-input" /></label>
      <label class="field"><span>Issuer ID</span><input v-model="form.issuer_id" class="field-input" /></label>
      <label class="field"><span>Key ID</span><input v-model="form.key_id" class="field-input" /></label>
      <label class="field"><span>App ID</span><input v-model="form.app_id" class="field-input" /></label>
      <div class="field">
        <ExampleHelp kind="csv" :label="t('profiles.csv_optional')" />
        <div class="field-row">
          <input v-model="form.csv" class="field-input" />
          <el-button @click="pickCsv">{{ t("filebrowser.browse") }}</el-button>
        </div>
      </div>
      <div class="field">
        <ExampleHelp kind="shots" :label="t('profiles.shots_optional')" />
        <div class="field-row">
          <input v-model="form.screenshots" class="field-input" />
          <el-button @click="pickShots">{{ t("filebrowser.browse") }}</el-button>
        </div>
      </div>
      <label class="field">
        <span>.p8</span>
        <input type="file" accept=".p8" @change="keyFile = ($event.target as HTMLInputElement).files?.[0] || null" />
      </label>
    </div>
    <template #footer>
      <el-button @click="dialog = false">{{ t("common.cancel") }}</el-button>
      <el-button type="primary" @click="save">{{ t("common.save") }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.profiles-page {
  align-self: stretch;
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  max-width: none;
  box-sizing: border-box;
}
.profiles-page > .card {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  align-self: stretch;
  width: 100%;
  min-width: 0;
  max-width: none;
  box-sizing: border-box;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}
.empty-hint {
  display: block;
  margin-top: 4px;
  color: var(--text-faint);
  font-size: 12px;
}
.profile-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  min-width: 0;
  flex: 1 1 auto;
}
.profile-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    "head actions"
    "meta actions";
  column-gap: 20px;
  row-gap: 10px;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
}
.profile-head {
  grid-area: head;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}
.name {
  font-size: 14px;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.badge {
  flex-shrink: 0;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--info);
  border: 1px solid color-mix(in srgb, var(--info) 45%, transparent);
  background: color-mix(in srgb, var(--info) 12%, transparent);
  border-radius: 999px;
  padding: 1px 7px;
}
.actions {
  grid-area: actions;
  display: inline-flex;
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
  align-self: start;
  gap: 8px;
}
.actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.profile-meta {
  grid-area: meta;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
  gap: 10px 28px;
  margin: 0;
  min-width: 0;
}
.meta-item dt {
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-faint);
  margin-bottom: 4px;
}
.meta-item dd {
  margin: 0;
  font-size: 13px;
  line-height: 1.45;
  overflow-wrap: anywhere;
  word-break: break-word;
}
@media (max-width: 720px) {
  .profile-card {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "head"
      "meta"
      "actions";
  }
  .profile-meta {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
