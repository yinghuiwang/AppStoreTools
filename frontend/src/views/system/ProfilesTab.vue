<script setup lang="ts">
import { computed, onActivated, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { MessagePlugin } from "tdesign-vue-next";
import { httpJson } from "@/api/http";
import ExampleHelp from "@/components/ExampleHelp.vue";
import PageLoading from "@/components/PageLoading.vue";
import { useAddProfile } from "@/composables/useAddProfile";
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

type ImportCandidate = {
  suggested_name?: string;
  env_file_path?: string;
  app_id?: string;
  project_root?: string;
  key_id?: string;
  key_file?: string;
  key_file_exists?: boolean;
};

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const browse = useBrowse();
const { refresh } = useProfile();
const { pending } = useAddProfile();
const profiles = ref<string[]>([]);
const details = ref<Record<string, Detail>>({});
const defaultName = ref("");
const canCreate = ref(true);
const dialog = ref(false);
const importOpen = ref(false);
const addOpening = ref(false);
const importBusy = ref(false);
const importError = ref("");
const importCandidates = ref<ImportCandidate[]>([]);
const importName = ref("");
const importSetDefault = ref(true);
const loading = ref(true);
const loaded = ref(false);
const editing = ref("");
const keyFile = ref<File | null>(null);
const showIssuer = ref(false);
const showKeyId = ref(false);
const formError = ref("");
const dialogOpen = computed({
  get: () => dialog.value || importOpen.value,
  set: (visible: boolean) => {
    if (!visible) closeDialog();
  },
});
const dialogTitle = computed(() => {
  if (editing.value) return t("profiles.edit_title");
  if (importOpen.value) return t("profiles.import_title");
  return t("profiles.add_title");
});
const form = reactive({
  name: "",
  issuer_id: "",
  key_id: "",
  app_id: "",
  csv: "",
  screenshots: "",
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

function closeDialog() {
  dialog.value = false;
  importOpen.value = false;
  importBusy.value = false;
  formError.value = "";
  importError.value = "";
}

function resetCreateForm() {
  editing.value = "";
  Object.assign(form, {
    name: "", issuer_id: "", key_id: "", app_id: "",
    csv: "", screenshots: "",
  });
  keyFile.value = null;
  showIssuer.value = false;
  showKeyId.value = false;
  formError.value = "";
}

function openCreate() {
  resetCreateForm();
  dialog.value = true;
}

async function openAdd() {
  if (!canCreate.value || addOpening.value) return;
  importError.value = "";
  addOpening.value = true;
  try {
    const found = await httpJson<{ candidates: ImportCandidate[] }>("/api/profiles/discover-local");
    const candidates = found.candidates || [];
    if (candidates.length) {
      importCandidates.value = candidates;
      importName.value = candidates[0].suggested_name || "";
      importSetDefault.value = true;
      importOpen.value = true;
      return;
    }
  } catch {
    // Fall through to the manual create dialog.
  } finally {
    addOpening.value = false;
  }
  openCreate();
}

function queryWantsNew(): boolean {
  const raw = route.query.new;
  const value = String(Array.isArray(raw) ? raw[0] : raw || "");
  return value === "1" || value === "true";
}

function stripNewQuery() {
  if (!queryWantsNew() || route.path !== "/profiles") return;
  const { new: _new, ...rest } = route.query;
  void router.replace({ path: "/profiles", query: rest });
}

const consumingOpen = ref(false);

async function consumeOpenRequest() {
  const fromQuery = queryWantsNew();
  const fromPending = pending.value;
  if (!fromQuery && !fromPending) return;
  if (consumingOpen.value) return;
  consumingOpen.value = true;
  pending.value = false;
  try {
    stripNewQuery();
    if (dialog.value || importOpen.value || addOpening.value) return;
    if (!loaded.value) await load();
    await openAdd();
  } finally {
    consumingOpen.value = false;
  }
}

function openEdit(name: string) {
  const d = details.value[name] || ({} as Detail);
  editing.value = name;
  Object.assign(form, {
    name, issuer_id: "", key_id: "", app_id: d.app_id,
    csv: d.csv || "", screenshots: d.screenshots || "",
  });
  keyFile.value = null;
  showIssuer.value = false;
  showKeyId.value = false;
  formError.value = "";
  importOpen.value = false;
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
  formError.value = "";
  const body = new FormData();
  body.set("name", form.name);
  body.set("issuer_id", form.issuer_id);
  body.set("key_id", form.key_id);
  body.set("app_id", form.app_id);
  if (editing.value) {
    body.set("csv", form.csv);
    body.set("screenshots", form.screenshots);
    rememberFormPath("profile.csv", form.csv);
    rememberFormPath("profile.screenshots", form.screenshots);
  }
  if (keyFile.value) body.set("key_file", keyFile.value);
  try {
    if (editing.value) {
      await httpJson(`/api/profiles/${encodeURIComponent(editing.value)}`, { method: "PUT", body });
    } else {
      if (!keyFile.value) {
        formError.value = "key_file";
        MessagePlugin.error("key_file");
        return;
      }
      await httpJson("/api/profiles", { method: "POST", body });
    }
  } catch {
    formError.value = t("profiles.save_failed");
    return;
  }
  closeDialog();
  await load();
  await refresh();
}

async function remove(name: string) {
  await httpJson(`/api/profiles/${encodeURIComponent(name)}`, { method: "DELETE" });
  await load();
  await refresh();
}

async function setDefault(name: string) {
  await httpJson(`/api/profiles/${encodeURIComponent(name)}/set-default`, { method: "POST" });
  await load();
}

function skipImport() {
  resetCreateForm();
  dialog.value = true;
  importOpen.value = false;
}

async function importCandidate(candidate: ImportCandidate) {
  if (!candidate.key_file_exists || importBusy.value) return;
  importError.value = "";
  importBusy.value = true;
  try {
    const name = (importName.value || candidate.suggested_name || "").trim();
    await httpJson("/api/profiles/import", {
      method: "POST",
      body: JSON.stringify({
        name: name || undefined,
        set_default: importSetDefault.value,
      }),
    });
    closeDialog();
    await load();
    await refresh();
  } catch {
    importError.value = t("profiles.import_failed");
  } finally {
    importBusy.value = false;
  }
}

watch(pending, (value) => {
  if (value) void consumeOpenRequest();
});
watch(() => route.query.new, () => {
  void consumeOpenRequest();
});

const didMount = ref(false);
onMounted(() => {
  void load().then(() => {
    didMount.value = true;
    return consumeOpenRequest();
  });
});
onActivated(() => {
  if (!didMount.value) return;
  void consumeOpenRequest();
});
</script>

<template>
  <div class="page-stack profiles-page">
    <div class="card">
      <div class="toolbar">
        <t-button
          theme="primary"
          :disabled="!canCreate"
          :loading="addOpening"
          :title="canCreate ? t('profiles.add_title') : t('profiles.cannot_create')"
          @click="openAdd"
        >{{ t("profiles.add") }}</t-button>
      </div>
      <PageLoading v-if="loading && !loaded" size="page" />
      <t-empty v-else-if="!rows.length" :description="t('profiles.empty')">
        <template #description>
          <p>{{ t("profiles.empty") }}</p>
          <span class="empty-hint">{{ t("profiles.empty_hint") }}</span>
        </template>
      </t-empty>
      <div v-else class="profile-list">
        <article v-for="row in rows" :key="row.name" class="profile-card">
          <header class="profile-head">
            <span class="name mono">{{ row.name }}</span>
            <span v-if="row.isDefault" class="badge">{{ t("common.default") }}</span>
          </header>
          <div class="actions">
            <t-button size="small" @click="openEdit(row.name)">{{ t("common.edit") }}</t-button>
            <t-button v-if="!row.isDefault" size="small" @click="setDefault(row.name)">{{ t("common.set_default") }}</t-button>
            <t-popconfirm :content="t('profiles.confirm_delete', { name: row.name })" @confirm="remove(row.name)">
              <t-button size="small">{{ t("common.delete") }}</t-button>
            </t-popconfirm>
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
  <t-dialog
    v-model:visible="dialogOpen"
    :header="dialogTitle"
    :footer="false"
    width="480px"
    placement="center"
    attach="body"
    :close-on-overlay-click="true"
    class="profile-dialog"
  >
    <div class="profile-panel">
      <div v-if="importOpen && !editing" class="profile-import">
        <p class="import-hint">{{ t("profiles.import_hint") }}</p>
        <article v-for="item in importCandidates" :key="item.env_file_path || item.suggested_name" class="import-card">
          <header class="import-head">
            <span class="name mono">{{ item.suggested_name }}</span>
            <span class="badge">{{ t("profiles.import_local") }}</span>
          </header>
          <dl class="import-meta">
            <div class="meta-item">
              <dt>App ID</dt>
              <dd class="mono">{{ item.app_id || "—" }}</dd>
            </div>
            <div class="meta-item">
              <dt>{{ t("profiles.import_project") }}</dt>
              <dd class="mono">{{ item.project_root || "—" }}</dd>
            </div>
            <div class="meta-item">
              <dt>Key ID</dt>
              <dd class="mono">{{ item.key_id || "—" }}</dd>
            </div>
            <div class="meta-item">
              <dt>{{ t("profiles.key_file") }}</dt>
              <dd class="mono" :class="{ missing: !item.key_file_exists }">{{ item.key_file || "—" }}</dd>
            </div>
          </dl>
          <t-alert v-if="!item.key_file_exists" theme="error" :title="t('profiles.import_missing_key')" />
          <label class="field">
            <span>{{ t("profiles.name") }}</span>
            <t-input v-model="importName" :placeholder="item.suggested_name" />
          </label>
          <div class="import-card-footer">
            <t-checkbox v-model="importSetDefault">
              {{ t("profiles.import_set_default") }}
            </t-checkbox>
            <t-button
              theme="primary"
              :disabled="!item.key_file_exists || importBusy"
              :loading="importBusy"
              @click="importCandidate(item)"
            >{{ importBusy ? t("profiles.importing") : t("profiles.import_confirm") }}</t-button>
          </div>
        </article>
        <t-alert v-if="importError" theme="error" :title="importError" />
        <div class="profile-import-footer">
          <t-button variant="outline" @click="skipImport">{{ t("profiles.import_skip") }}</t-button>
          <t-button variant="outline" @click="closeDialog">{{ t("common.cancel") }}</t-button>
        </div>
      </div>

      <form v-else class="profile-form" @submit.prevent="save">
        <label class="field">
          <span>{{ t("profiles.name") }}</span>
          <t-input v-model="form.name" placeholder="myapp" />
        </label>
        <label class="field">
          <span>Issuer ID</span>
          <t-input v-model="form.issuer_id" :type="showIssuer ? 'text' : 'password'">
            <template #suffix>
              <button type="button" class="reveal" @click="showIssuer = !showIssuer">
                {{ showIssuer ? t("profiles.hide") : t("profiles.show") }}
              </button>
            </template>
          </t-input>
        </label>
        <label class="field">
          <span>Key ID</span>
          <t-input v-model="form.key_id" :type="showKeyId ? 'text' : 'password'">
            <template #suffix>
              <button type="button" class="reveal" @click="showKeyId = !showKeyId">
                {{ showKeyId ? t("profiles.hide") : t("profiles.show") }}
              </button>
            </template>
          </t-input>
        </label>
        <label class="field">
          <span>{{ t("profiles.p8") }}</span>
          <input type="file" accept=".p8" @change="keyFile = ($event.target as HTMLInputElement).files?.[0] || null" />
          <p v-if="editing" class="keep-key">{{ t("profiles.keep_key") }}</p>
        </label>
        <label class="field">
          <span>{{ t("profiles.app_id") }}</span>
          <t-input v-model="form.app_id" placeholder="1234567890" />
        </label>
        <div v-if="editing" class="field">
          <ExampleHelp kind="csv" :label="t('profiles.csv_optional')" />
          <div class="field-row">
            <t-input v-model="form.csv" />
            <t-button @click="pickCsv">{{ t("filebrowser.browse") }}</t-button>
          </div>
        </div>
        <div v-if="editing" class="field">
          <ExampleHelp kind="shots" :label="t('profiles.shots_optional')" />
          <div class="field-row">
            <t-input v-model="form.screenshots" />
            <t-button @click="pickShots">{{ t("filebrowser.browse") }}</t-button>
          </div>
        </div>
        <t-alert v-if="formError" theme="error" :title="formError" />
        <div class="profile-form-actions">
          <t-button theme="primary" type="submit">{{ editing ? t("common.save") : t("profiles.create") }}</t-button>
          <t-button variant="outline" type="button" @click="closeDialog">{{ t("common.cancel") }}</t-button>
        </div>
      </form>
    </div>
  </t-dialog>
</template>

<style scoped>
.profile-dialog :deep(.t-dialog__header) {
  border-bottom: 0;
  padding: 20px 24px 8px;
}
.profile-dialog :deep(.t-dialog__body) {
  padding: 8px 24px 24px;
}
.profile-panel,
.profile-import,
.profile-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.profile-form .field > span {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 500;
}
.reveal {
  margin: 0;
  padding: 0;
  border: 0;
  background: none;
  color: var(--text-faint);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 500;
  cursor: pointer;
}
.reveal:hover {
  color: var(--text-muted);
}
.keep-key {
  margin: 0;
  font-size: 11px;
  color: var(--text-faint);
}
.profile-form-actions,
.profile-import-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.profile-form-actions :deep(.t-button + .t-button),
.profile-import-footer :deep(.t-button + .t-button) {
  margin-left: 0;
}
.import-hint { margin: 0; color: var(--text-muted); font-size: 13px; }
.import-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
}
.import-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.import-meta {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
  margin: 0;
}
.import-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.import-card-footer :deep(.t-checkbox) {
  flex: 1 1 auto;
  min-width: 0;
}
.import-card-footer :deep(.t-button) {
  flex: 0 0 auto;
  margin-left: auto;
}
.missing { color: var(--err); }
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
.actions :deep(.t-button + .t-button) {
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
