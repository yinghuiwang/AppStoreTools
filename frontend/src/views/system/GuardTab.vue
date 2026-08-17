<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { httpForm, httpJson } from "@/api/http";
import PageLoading from "@/components/PageLoading.vue";

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

type BindingInfo = {
  app_id: string;
  app_name?: string;
  note?: string;
  bound_at?: string;
  profile_name?: string;
};

type AppBinding = {
  profile_name: string;
  app_name: string;
  app_id: string;
  machine: string;
  ip: string;
  credential: string;
  bound_at: string;
  note: string;
};

type GuardStatus = {
  enabled: boolean;
  bindings: Record<string, Record<string, BindingInfo>>;
  current_environment?: { machine: EnvEntry; ip: EnvEntry };
  current_profile?: string;
  app_notes?: Record<string, string>;
  error?: string;
};

const { t } = useI18n();
const loading = ref(true);
const guard = ref<GuardStatus | null>(null);
const profiles = ref<string[]>([]);
const details = ref<Record<string, { already_bound?: boolean }>>({});
const addOpen = ref(false);
const addSaving = ref(false);
const addError = ref("");
const addForm = reactive({ fingerprint: "", profile: "", ip: "", note: "" });
const savingNote = ref("");
const appRows = ref<AppBinding[]>([]);

const availableProfiles = computed(() =>
  profiles.value.filter((name) => !details.value[name]?.already_bound),
);

function appendValue(row: AppBinding, field: "machine" | "ip" | "credential", value: string) {
  if (!value) return;
  const parts = row[field] ? row[field].split(", ") : [];
  if (parts.includes(value)) return;
  row[field] = parts.length ? `${row[field]}, ${value}` : value;
}

function rebuildAppRows(status: GuardStatus) {
  const bindings = status.bindings || {};
  const appNotes = status.app_notes || {};
  const apps: Record<string, AppBinding> = {};

  function ensure(info: BindingInfo): AppBinding {
    const appId = String(info.app_id || "");
    const key = info.profile_name || info.app_name || appId || "_";
    if (!apps[key]) {
      apps[key] = {
        profile_name: info.profile_name || "",
        app_name: info.app_name || "",
        app_id: appId,
        machine: "",
        ip: "",
        credential: "",
        bound_at: info.bound_at || "",
        note: appNotes[appId] || info.note || "",
      };
    }
    if (info.bound_at) apps[key].bound_at = info.bound_at;
    if (appId && !apps[key].app_id) apps[key].app_id = appId;
    return apps[key];
  }

  for (const [fp, info] of Object.entries(bindings.machine || {})) {
    appendValue(ensure(info), "machine", fp);
  }
  for (const [ip, info] of Object.entries(bindings.ip || {})) {
    appendValue(ensure(info), "ip", ip);
  }
  for (const [keyId, info] of Object.entries(bindings.credential || {})) {
    appendValue(ensure(info), "credential", keyId);
  }

  const current = status.current_profile || "";
  appRows.value = Object.values(apps).sort((a, b) => {
    if (a.profile_name === current) return -1;
    if (b.profile_name === current) return 1;
    return 0;
  });
}

function appLabel(entry?: EnvEntry) {
  if (!entry?.bound) return t("guard.no_bound_app");
  const name = entry.profile_name || entry.app_name || "";
  const id = entry.app_id || "";
  if (name && id) return `${name} (${id})`;
  return name || id || t("guard.no_bound_app");
}

function formatBoundAt(value?: string) {
  if (!value) return "";
  return value.slice(0, 19).replace("T", " ");
}

function isCurrentApp(row: AppBinding) {
  const current = guard.value?.current_profile || "";
  return Boolean(current && row.profile_name === current);
}

async function loadGuard() {
  loading.value = true;
  try {
    guard.value = await httpJson<GuardStatus>("/api/guard/status");
    if (guard.value) rebuildAppRows(guard.value);
    else appRows.value = [];
  } catch {
    guard.value = null;
    appRows.value = [];
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

async function saveNote(row: AppBinding) {
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
  addSaving.value = true;
  try {
    await httpForm("/api/guard/manual-bind", new URLSearchParams({ ...addForm }));
    addOpen.value = false;
    await loadGuard();
    await loadProfiles();
  } catch (err) {
    addError.value = err instanceof Error ? err.message : t("guard.add_failed");
  } finally {
    addSaving.value = false;
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
      <PageLoading v-if="loading" size="block" />
      <p v-else-if="!guard" class="err">{{ t("guard.load_failed") }}</p>
      <template v-else>
        <div class="status-row">
          <span class="status-dot" :class="guard.enabled ? 'on' : 'off'" />
          <p :class="guard.enabled ? 'ok' : 'muted'">
            {{ guard.enabled ? t("guard.enabled") : t("guard.disabled") }}
          </p>
        </div>

        <section v-if="guard.current_environment" class="section">
          <h3>{{ t("guard.current_env") }}</h3>
          <div class="panel">
            <div class="env-block">
              <div class="env-line">
                <span class="k">{{ t("guard.machine") }}</span>
                <code class="mono">{{ guard.current_environment.machine.fingerprint }}</code>
              </div>
              <p :class="guard.current_environment.machine.bound ? 'ok' : 'muted'">
                {{
                  guard.current_environment.machine.bound
                    ? t("guard.status_bound")
                    : t("guard.status_unbound")
                }}
              </p>
              <p class="meta">
                <span class="k">{{ t("guard.bound_app") }}:</span>
                <span class="mono">{{ appLabel(guard.current_environment.machine) }}</span>
              </p>
              <p
                v-if="guard.current_environment.machine.bound && guard.current_environment.machine.note"
                class="meta"
              >
                <span class="k">{{ t("guard.note") }}:</span>
                <span>{{ guard.current_environment.machine.note }}</span>
              </p>
            </div>
            <div class="env-block split">
              <div class="env-line">
                <span class="k">{{ t("guard.ip_address") }}</span>
                <code class="mono">{{ guard.current_environment.ip.address }}</code>
              </div>
              <p v-if="guard.current_environment.ip.available === false" class="warn">
                {{ t("guard.ip_unavailable") }}
              </p>
              <template v-else>
                <p :class="guard.current_environment.ip.bound ? 'ok' : 'muted'">
                  {{
                    guard.current_environment.ip.bound
                      ? t("guard.status_bound")
                      : t("guard.status_unbound")
                  }}
                </p>
                <p class="meta">
                  <span class="k">{{ t("guard.bound_app") }}:</span>
                  <span class="mono">{{ appLabel(guard.current_environment.ip) }}</span>
                </p>
                <p
                  v-if="guard.current_environment.ip.bound && guard.current_environment.ip.note"
                  class="meta"
                >
                  <span class="k">{{ t("guard.note") }}:</span>
                  <span>{{ guard.current_environment.ip.note }}</span>
                </p>
              </template>
            </div>
          </div>
        </section>

        <section v-if="appRows.length" class="section">
          <h3>{{ t("guard.bindings") }}</h3>
          <div class="bind-list">
            <article v-for="row in appRows" :key="row.app_id || row.profile_name" class="panel bind-card">
              <header class="bind-head">
                <span class="star" :class="{ on: isCurrentApp(row) }">{{ isCurrentApp(row) ? "★" : "" }}</span>
                <span class="mono name">{{ row.profile_name || row.app_id }}</span>
                <span v-if="row.app_name && row.app_name !== row.profile_name" class="muted">{{ row.app_name }}</span>
                <span v-if="isCurrentApp(row)" class="badge">{{ t("guard.current") }}</span>
              </header>
              <dl class="detail-grid">
                <div v-if="row.app_id">
                  <dt>{{ t("guard.app_id") }}</dt>
                  <dd class="mono">{{ row.app_id }}</dd>
                </div>
                <div v-if="row.machine">
                  <dt>{{ t("guard.machine") }}</dt>
                  <dd class="mono">{{ row.machine }}</dd>
                </div>
                <div v-if="row.ip">
                  <dt>{{ t("guard.ip") }}</dt>
                  <dd class="mono">{{ row.ip }}</dd>
                </div>
                <div v-if="row.credential">
                  <dt>{{ t("guard.credential") }}</dt>
                  <dd class="mono">{{ row.credential }}</dd>
                </div>
                <div v-if="row.bound_at">
                  <dt>{{ t("guard.bound_at") }}</dt>
                  <dd class="mono muted">{{ formatBoundAt(row.bound_at) }}</dd>
                </div>
              </dl>
              <div v-if="row.app_id" class="note-row">
                <span class="k">{{ t("guard.note") }}</span>
                <div class="field-row">
                  <input v-model="row.note" class="field-input" :placeholder="t('guard.note')" />
                  <el-button size="small" :loading="savingNote === row.app_id" @click="saveNote(row)">
                    {{ savingNote === row.app_id ? t("guard.saving") : t("guard.save_note") }}
                  </el-button>
                </div>
              </div>
            </article>
          </div>
        </section>
        <p v-else class="empty-state">{{ t("guard.empty") }}</p>

        <div class="help">
          <p>{{ t("guard.help1") }}</p>
          <p>
            {{ t("guard.help2") }}
            <code class="mono">asc guard enable/disable/unbind</code>
          </p>
        </div>
      </template>
    </div>
    <el-dialog v-model="addOpen" :title="t('guard.manual_add_title')" width="480px">
      <p class="hint">{{ t("guard.manual_add_desc") }}</p>
      <div class="page-stack">
        <label class="field">
          <span>{{ t("guard.machine") }}</span>
          <input
            v-model="addForm.fingerprint"
            class="field-input mono"
            :placeholder="t('guard.fingerprint_placeholder')"
          />
        </label>
        <label class="field">
          <span>{{ t("guard.local_app") }}</span>
          <select v-model="addForm.profile" class="field-input">
            <option value="">{{ t("guard.select_app") }}</option>
            <option v-for="name in availableProfiles" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <p v-if="!profiles.length" class="hint warn">{{ t("guard.no_profiles") }}</p>
        <p v-else-if="!availableProfiles.length" class="hint warn">{{ t("guard.all_apps_bound") }}</p>
        <p v-else-if="addForm.profile" class="hint">{{ t("guard.credentials_from_profile") }}</p>
        <label class="field">
          <span>{{ t("guard.ip_optional") }}</span>
          <input v-model="addForm.ip" class="field-input mono" placeholder="1.2.3.4" />
        </label>
        <label class="field">
          <span>{{ t("guard.note_optional") }}</span>
          <input v-model="addForm.note" class="field-input" />
        </label>
        <p v-if="addError" class="err">{{ addError }}</p>
      </div>
      <template #footer>
        <el-button @click="addOpen = false">{{ t("common.cancel") }}</el-button>
        <el-button type="primary" :loading="addSaving" :disabled="!availableProfiles.length" @click="submitAdd">
          {{ addSaving ? t("guard.saving") : t("guard.manual_add_submit") }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
h2, h3 {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: 600;
}
.hint { color: var(--text-muted); font-size: 13px; }
.ok { color: var(--ok); }
.muted { color: var(--text-muted); }
.warn { color: var(--warn); }
.err { color: var(--err); font-size: 13px; }
.status-row { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; }
.status-row p { margin: 0; font-size: 13px; font-weight: 600; }
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-faint);
  flex-shrink: 0;
}
.status-dot.on {
  background: var(--ok);
  box-shadow: 0 0 8px color-mix(in srgb, var(--ok) 55%, transparent);
}
.section { margin: 0 0 20px; }
.section h3 { margin-bottom: 10px; }
.panel {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
}
.env-block { display: flex; flex-direction: column; gap: 6px; }
.env-block.split { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); }
.env-line { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.env-block p { margin: 0; font-size: 13px; }
.k {
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-faint);
}
.meta { color: var(--text-muted); font-size: 12px; }
.meta .mono { color: var(--text); margin-left: 6px; }
.bind-list { display: flex; flex-direction: column; gap: 12px; }
.bind-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.star { width: 12px; color: var(--warn); }
.name { font-size: 13px; font-weight: 600; color: var(--text); }
.badge {
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--info);
  border: 1px solid color-mix(in srgb, var(--info) 45%, transparent);
  background: color-mix(in srgb, var(--info) 12%, transparent);
  border-radius: 999px;
  padding: 1px 7px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 24px;
  margin: 0;
}
.detail-grid dt {
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-faint);
  margin-bottom: 2px;
}
.detail-grid dd { margin: 0; font-size: 12px; word-break: break-all; }
.note-row {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.help {
  margin-top: 4px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.help p { margin: 0 0 6px; color: var(--text-faint); font-size: 12px; }
.help code {
  color: var(--accent);
  background: var(--raised);
  padding: 1px 6px;
  border-radius: 4px;
}
@media (max-width: 1100px) {
  .detail-grid { grid-template-columns: 1fr; }
}
</style>
