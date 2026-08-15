<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { httpForm, httpJson } from "@/api/http";

type EnvEntry = {
  fingerprint?: string;
  address?: string;
  available?: boolean;
  bound: boolean;
  app_id: string;
  app_name: string;
  note: string;
  profile_name: string;
};

type BindingRow = {
  category: string;
  key: string;
  app_id: string;
  note: string;
  bound_at?: string;
  profile_name?: string;
};

type GuardStatus = {
  enabled: boolean;
  bindings: Record<string, Record<string, Omit<BindingRow, "category" | "key">>>;
  current_environment?: { machine: EnvEntry; ip: EnvEntry };
  error?: string;
};

const { t } = useI18n();
const loading = ref(true);
const guard = ref<GuardStatus | null>(null);
const profiles = ref<string[]>([]);
const details = ref<Record<string, { already_bound?: boolean }>>({});
const addOpen = ref(false);
const addError = ref("");
const addForm = reactive({ fingerprint: "", profile: "", ip: "", note: "" });
const savingNote = ref("");

const rows = computed<BindingRow[]>(() => {
  const out: BindingRow[] = [];
  const bindings = guard.value?.bindings || {};
  for (const category of ["machine", "ip", "credential"]) {
    for (const [key, info] of Object.entries(bindings[category] || {})) {
      out.push({ category, key, ...info });
    }
  }
  return out;
});

const availableProfiles = computed(() =>
  profiles.value.filter((name) => !details.value[name]?.already_bound),
);

function appLabel(entry?: EnvEntry) {
  if (!entry?.bound) return t("guard.no_bound_app");
  const name = entry.profile_name || entry.app_name || "";
  const id = entry.app_id || "";
  if (name && id) return `${name} (${id})`;
  return name || id || t("guard.no_bound_app");
}

async function loadGuard() {
  loading.value = true;
  try {
    guard.value = await httpJson<GuardStatus>("/api/guard/status");
  } catch {
    guard.value = null;
  } finally {
    loading.value = false;
  }
}

async function loadProfiles() {
  const data = await httpJson<{
    profiles: string[];
    profile_details: Record<string, { already_bound?: boolean }>;
  }>("/api/profiles");
  profiles.value = data.profiles || [];
  details.value = data.profile_details || {};
}

async function saveNote(row: BindingRow) {
  savingNote.value = row.app_id;
  try {
    await httpForm("/api/guard/note", new URLSearchParams({ app_id: row.app_id, note: row.note || "" }));
    await loadGuard();
  } finally {
    savingNote.value = "";
  }
}

function openAdd() {
  addError.value = "";
  addForm.fingerprint = "";
  addForm.ip = "";
  addForm.note = "";
  addOpen.value = true;
  void loadProfiles().then(() => {
    addForm.profile = availableProfiles.value[0] || "";
  });
}

async function submitAdd() {
  addError.value = "";
  if (!addForm.fingerprint.trim()) {
    addError.value = t("guard.fingerprint_required");
    return;
  }
  if (!addForm.profile) {
    addError.value = t("guard.app_required");
    return;
  }
  try {
    await httpForm("/api/guard/manual-bind", new URLSearchParams({ ...addForm }));
    addOpen.value = false;
    await loadGuard();
    await loadProfiles();
  } catch (err) {
    addError.value = err instanceof Error ? err.message : t("guard.add_failed");
  }
}

onMounted(() => {
  void loadGuard();
  void loadProfiles();
});
</script>

<template>
  <div class="page-stack">
    <div class="card">
      <div class="toolbar">
        <h2>{{ t("guard.title") }}</h2>
        <el-button @click="openAdd">{{ t("guard.manual_add") }}</el-button>
      </div>
      <p class="hint">{{ t("guard.help1") }} {{ t("guard.help2") }} <span class="mono">asc guard</span></p>
      <p v-if="loading" class="empty-state">{{ t("common.loading") }}</p>
      <p v-else-if="!guard" class="empty-state">{{ t("guard.load_failed") }}</p>
      <template v-else>
        <p :class="guard.enabled ? 'ok' : 'muted'">
          {{ guard.enabled ? t("guard.enabled") : t("guard.disabled") }}
        </p>
        <div v-if="guard.current_environment" class="env">
          <h3>{{ t("guard.current_env") }}</h3>
          <div class="env-grid">
            <div>
              <span>{{ t("guard.machine") }}</span>
              <code class="mono">{{ guard.current_environment.machine.fingerprint }}</code>
              <small>{{
                guard.current_environment.machine.bound ? t("guard.status_bound") : t("guard.status_unbound")
              }}</small>
              <small>{{ t("guard.bound_app") }}: {{ appLabel(guard.current_environment.machine) }}</small>
            </div>
            <div>
              <span>{{ t("guard.ip") }}</span>
              <code class="mono">{{ guard.current_environment.ip.address }}</code>
              <small v-if="guard.current_environment.ip.available === false">{{ t("guard.ip_unavailable") }}</small>
              <small v-else>{{
                guard.current_environment.ip.bound ? t("guard.status_bound") : t("guard.status_unbound")
              }}</small>
              <small>{{ t("guard.bound_app") }}: {{ appLabel(guard.current_environment.ip) }}</small>
            </div>
          </div>
        </div>
        <el-table v-if="rows.length" :data="rows">
          <el-table-column prop="category" :label="t('guard.bindings')" width="110" />
          <el-table-column prop="key" :label="t('guard.machine')">
            <template #default="{ row }"><span class="mono">{{ row.key }}</span></template>
          </el-table-column>
          <el-table-column prop="profile_name" :label="t('guard.bound_app')" />
          <el-table-column :label="t('guard.note')">
            <template #default="{ row }">
              <div class="field-row">
                <input v-model="row.note" class="field-input" />
                <el-button size="small" :loading="savingNote === row.app_id" @click="saveNote(row)">
                  {{ t("guard.save_note") }}
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <p v-else class="empty-state">{{ t("guard.empty") }}</p>
      </template>
    </div>
    <el-dialog v-model="addOpen" :title="t('guard.manual_add_title')" width="480px">
      <p class="hint">{{ t("guard.manual_add_desc") }}</p>
      <p class="hint">{{ t("guard.credentials_from_profile") }}</p>
      <div class="page-stack">
        <label class="field">
          <span>{{ t("guard.machine") }}</span>
          <input v-model="addForm.fingerprint" class="field-input" :placeholder="t('guard.fingerprint_placeholder')" />
        </label>
        <label class="field">
          <span>{{ t("guard.local_app") }}</span>
          <select v-model="addForm.profile" class="field-input">
            <option value="">{{ t("guard.select_app") }}</option>
            <option v-for="name in availableProfiles" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <p v-if="!profiles.length" class="hint">{{ t("guard.no_profiles") }}</p>
        <p v-else-if="!availableProfiles.length" class="hint">{{ t("guard.all_apps_bound") }}</p>
        <label class="field">
          <span>{{ t("guard.ip_optional") }}</span>
          <input v-model="addForm.ip" class="field-input" />
        </label>
        <label class="field">
          <span>{{ t("guard.note_optional") }}</span>
          <input v-model="addForm.note" class="field-input" />
        </label>
        <p v-if="addError" class="err">{{ addError }}</p>
      </div>
      <template #footer>
        <el-button @click="addOpen = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" @click="submitAdd">{{ t("guard.manual_add_submit") }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
h2, h3 { margin: 0; font-size: 14px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-muted); }
.hint { color: var(--text-muted); font-size: 13px; }
.ok { color: var(--ok); }
.muted { color: var(--text-muted); }
.err { color: var(--err); font-size: 13px; }
.env { margin: 16px 0; }
.env-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.env-grid span { display: block; font-size: 11px; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.08em; }
.env-grid small { display: block; color: var(--text-muted); }
@media (max-width: 1100px) { .env-grid { grid-template-columns: 1fr; } }
</style>
