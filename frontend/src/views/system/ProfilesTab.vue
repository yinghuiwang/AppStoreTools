<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import { httpJson } from "@/api/http";
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
  <div class="page-stack">
    <div class="card">
      <div class="toolbar">
        <el-button type="primary" :disabled="!canCreate" :title="canCreate ? t('profiles.add_title') : t('profiles.cannot_create')" @click="openCreate">{{ t("profiles.add") }}</el-button>
        <el-button @click="importLocal">{{ t("profiles.import_confirm") }}</el-button>
      </div>
      <PageLoading v-if="loading" size="block" />
      <el-table v-else :data="profiles.map((name) => ({ name, ...(details[name] || {}) }))">
        <el-table-column prop="name" :label="t('profiles.name')" />
        <el-table-column prop="app_id" label="App ID" />
        <el-table-column prop="issuer_id" label="Issuer" />
        <el-table-column>
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row.name)">{{ t("common.edit") }}</el-button>
            <el-button size="small" @click="setDefault(row.name)">{{ t("common.set_default") }}</el-button>
            <el-button size="small" @click="remove(row.name)">{{ t("common.delete") }}</el-button>
            <span v-if="row.name === defaultName" class="mono">{{ t("common.default") }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <el-dialog v-model="dialog" :title="editing ? t('common.edit') : t('profiles.create')" width="520px">
      <div class="page-stack">
        <label class="field"><span>{{ t("profiles.name") }}</span><input v-model="form.name" class="field-input" /></label>
        <label class="field"><span>Issuer ID</span><input v-model="form.issuer_id" class="field-input" /></label>
        <label class="field"><span>Key ID</span><input v-model="form.key_id" class="field-input" /></label>
        <label class="field"><span>App ID</span><input v-model="form.app_id" class="field-input" /></label>
        <label class="field">
          <span>CSV</span>
          <div class="field-row">
            <input v-model="form.csv" class="field-input" />
            <el-button @click="pickCsv">{{ t("filebrowser.browse") }}</el-button>
          </div>
        </label>
        <label class="field">
          <span>Screenshots</span>
          <div class="field-row">
            <input v-model="form.screenshots" class="field-input" />
            <el-button @click="pickShots">{{ t("filebrowser.browse") }}</el-button>
          </div>
        </label>
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
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 14px; }
</style>
