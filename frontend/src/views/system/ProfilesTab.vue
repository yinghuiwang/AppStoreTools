<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import { httpJson } from "@/api/http";
import ExampleHelp from "@/components/ExampleHelp.vue";
import PageLoading from "@/components/PageLoading.vue";
import { useBrowse } from "@/composables/useBrowse";
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
  loading.value = true;
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
      <PageLoading v-if="loading" size="block" />
      <p v-else-if="!rows.length" class="empty-state">
        {{ t("profiles.empty") }}
        <span class="empty-hint">{{ t("profiles.empty_hint") }}</span>
      </p>
      <div v-else class="table-wrap">
        <table class="profiles-table">
          <thead>
            <tr>
              <th class="col-name">{{ t("profiles.name") }}</th>
              <th class="col-app">App ID</th>
              <th class="col-issuer">Issuer</th>
              <th class="col-actions">{{ t("index.col_actions") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.name">
              <td class="col-name">
                <div class="name-cell">
                  <span class="name mono" :title="row.name">{{ row.name }}</span>
                  <span v-if="row.isDefault" class="badge">{{ t("common.default") }}</span>
                </div>
              </td>
              <td class="col-app mono" :title="row.app_id">{{ row.app_id }}</td>
              <td class="col-issuer mono" :title="row.issuer_id">{{ row.issuer_id }}</td>
              <td class="col-actions">
                <div class="actions">
                  <el-button size="small" @click="openEdit(row.name)">{{ t("common.edit") }}</el-button>
                  <el-button v-if="!row.isDefault" size="small" @click="setDefault(row.name)">{{ t("common.set_default") }}</el-button>
                  <el-button size="small" @click="remove(row.name)">{{ t("common.delete") }}</el-button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
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
.table-wrap {
  width: 100%;
  min-width: 0;
  flex: 1 1 auto;
  overflow-x: auto;
}
.profiles-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  padding: 10px 12px;
  text-align: left;
  vertical-align: middle;
  border-bottom: 1px solid var(--border);
}
th {
  color: var(--text-faint);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  white-space: nowrap;
  background: var(--raised);
}
.col-name { width: 22%; }
.col-app { width: 18%; }
.col-issuer { width: auto; }
.col-actions {
  width: 1%;
  white-space: nowrap;
}
.col-app,
.col-issuer {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  display: inline-flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}
.actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
