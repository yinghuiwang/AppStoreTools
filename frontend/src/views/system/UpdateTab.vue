<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { httpForm, httpJson } from "@/api/http";
import PageLoading from "@/components/PageLoading.vue";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";

type CheckResult = {
  ok: boolean;
  level: string;
  message: string;
  detail?: {
    current?: string;
    current_commit?: string;
    latest?: string;
    latest_commit?: string;
    is_latest?: boolean;
    is_editable?: boolean;
  };
};

type PostRestart = {
  boot_id: string;
  pending: boolean;
  task_id: string | null;
  status: string | null;
};

const { t } = useI18n();
const { snapshot, refresh } = useProfile();
const rail = useRightRail();
const checking = ref(false);
const checkResult = ref<CheckResult | null>(null);
const versions = ref<string[]>([]);
const branches = ref<string[]>([]);
const versionError = ref("");
const branchError = ref("");
const versionsLoading = ref(false);
const branchesLoading = ref(false);
const selectedVersion = ref("");
const selectedBranch = ref("");
const advanced = ref<"specific" | "branch">("specific");
const pending = ref<PostRestart | null>(null);
const verbose = ref(false);
let lastBootId = snapshot.value?.boot_id || "";

const currentVersion = computed(
  () => checkResult.value?.detail?.current || snapshot.value?.version || "",
);
const currentCommit = computed(
  () => checkResult.value?.detail?.current_commit || snapshot.value?.commit || "",
);

async function check() {
  checking.value = true;
  try {
    checkResult.value = await httpJson<CheckResult>("/api/update/check");
  } finally {
    checking.value = false;
  }
}

async function loadVersions() {
  versionError.value = "";
  if (!versions.value.length) versionsLoading.value = true;
  try {
    const data = await httpJson<{ ok: boolean; versions: string[]; message?: string }>("/api/update/versions");
    versions.value = data.versions || [];
    if (!data.ok) versionError.value = data.message || t("update.version_list_failed");
    if (versions.value.length && !selectedVersion.value) selectedVersion.value = versions.value[0];
  } finally {
    versionsLoading.value = false;
  }
}

async function loadBranches() {
  branchError.value = "";
  if (!branches.value.length) branchesLoading.value = true;
  try {
    const data = await httpJson<{ ok: boolean; branches: string[]; message?: string }>("/api/update/branches");
    branches.value = data.branches || [];
    if (!data.ok) branchError.value = data.message || t("update.branch_list_failed");
    if (branches.value.length && !selectedBranch.value) selectedBranch.value = branches.value[0];
  } finally {
    branchesLoading.value = false;
  }
}

async function run(version = "", branch = "") {
  const body = new URLSearchParams({
    version,
    branch,
    verbose: verbose.value ? "true" : "",
  });
  const { task_id } = await httpForm<{ task_id: string }>("/api/update/run", body);
  rail.openLogs(task_id);
}

async function handshake() {
  const data = await httpJson<PostRestart>("/api/update/post-restart");
  if (lastBootId && data.boot_id && data.boot_id !== lastBootId) {
    await refresh();
    lastBootId = snapshot.value?.boot_id || data.boot_id;
  }
  if (data.pending) {
    pending.value = data;
    if (data.task_id) rail.openLogs(data.task_id);
  }
}

async function ack() {
  await httpJson("/api/update/post-restart/ack", { method: "POST" });
  pending.value = null;
}

onMounted(() => {
  lastBootId = snapshot.value?.boot_id || "";
  void handshake();
  void check();
  void loadVersions();
});
</script>

<template>
  <div class="page-stack">
    <el-alert
      v-if="pending"
      type="info"
      show-icon
      :title="t('update.restarting')"
      :description="t('update.restarting_hint')"
    >
      <el-button size="small" @click="ack">{{ t("common.cancel") }}</el-button>
    </el-alert>
    <el-alert v-if="snapshot?.is_editable" type="warning" show-icon :title="t('update.editable_title')" :description="t('update.editable_body')" />
    <div class="card">
      <div class="toolbar">
        <el-button
          :loading="checking && !!checkResult"
          :disabled="checking && !checkResult"
          @click="check"
        >{{ checking && !checkResult ? t("update.checking") : t("update.title") }}</el-button>
      </div>
      <PageLoading v-if="checking && !checkResult" size="inline" :text="t('update.checking')" />
      <div v-else class="version-block">
        <div class="version-row">
          <span class="version-label">{{ t("update.current_short") }}</span>
          <span class="version-num mono">{{ currentVersion }}</span>
        </div>
        <p v-if="currentCommit" class="version-commit mono">commit {{ currentCommit }}</p>
        <span v-if="checkResult?.detail?.is_latest" class="badge-latest">{{ t("update.badge_latest") }}</span>
        <p v-else-if="checkResult && !checkResult.ok" class="muted">{{ checkResult.message }}</p>
      </div>
    </div>
    <div v-if="checkResult?.detail && !checkResult.detail.is_latest" class="card">
      <p class="found-label">{{ t("update.found") }}</p>
      <p class="version-num mono">{{ checkResult.detail.latest }}</p>
      <p v-if="snapshot?.is_editable">{{ t("update.editable_latest_blocked") }}</p>
      <el-button v-else type="primary" @click="run()">{{ t("update.install_now") }}</el-button>
    </div>
    <div class="card">
      <h2>{{ t("update.advanced") }}</h2>
      <div class="seg">
        <button type="button" :class="{ on: advanced === 'specific' }" @click="advanced = 'specific'; loadVersions()">{{ t("update.pin_version") }}</button>
        <button type="button" :class="{ on: advanced === 'branch' }" @click="advanced = 'branch'; loadBranches()">{{ t("update.pin_branch") }}</button>
      </div>
      <div v-show="advanced === 'specific'" class="form-stack">
        <PageLoading v-if="versionsLoading && !versions.length" size="inline" />
        <label class="field">
          <span>{{ t("update.version_label") }}</span>
          <select v-if="versions.length" v-model="selectedVersion" class="field-input">
            <option v-for="ver in versions" :key="ver" :value="ver">{{ ver }}</option>
          </select>
          <input v-else v-model="selectedVersion" class="field-input" :placeholder="t('update.version_ph')" />
        </label>
        <p v-if="versionError" class="muted">{{ versionError }}</p>
        <el-button type="primary" :disabled="versionsLoading" @click="run(selectedVersion, '')">{{ t("update.install_version") }}</el-button>
      </div>
      <div v-show="advanced === 'branch'" class="form-stack">
        <PageLoading v-if="branchesLoading && !branches.length" size="inline" />
        <label class="field">
          <span>{{ t("update.branch_label") }}</span>
          <select v-if="branches.length" v-model="selectedBranch" class="field-input">
            <option v-for="br in branches" :key="br" :value="br">{{ br }}</option>
          </select>
          <input v-else v-model="selectedBranch" class="field-input" :placeholder="t('update.branch_ph')" />
        </label>
        <p v-if="branchError" class="muted">{{ branchError }}</p>
        <el-button type="primary" :disabled="branchesLoading" @click="run('', selectedBranch)">{{ t("update.install_branch") }}</el-button>
      </div>
      <label class="check"><input v-model="verbose" type="checkbox" /> {{ t("build.verbose") }}</label>
      <p class="muted">{{ t("update.note") }}</p>
    </div>
  </div>
</template>

<style scoped>
.card { display: flex; flex-direction: column; flex: 0 0 auto; }
.toolbar { display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; }
.muted { color: var(--text-muted); font-size: 13px; }
h2 { font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-muted); }
.seg { display: flex; gap: 6px; margin: 12px 0; }
.seg button { flex: 1; background: var(--raised); color: var(--text-muted); border: 1px solid var(--border); border-radius: 8px; padding: 8px; }
.seg button.on { color: #0a0a0c; background: linear-gradient(135deg, var(--accent-dim), var(--accent)); border-color: transparent; }
.check { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
.form-stack { display: flex; flex-direction: column; gap: 12px; }
.version-block { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
.version-row { display: flex; flex-direction: column; gap: 4px; }
.version-label {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: 600;
}
.version-num {
  font-size: 22px;
  font-weight: 650;
  line-height: 1.2;
  letter-spacing: -0.02em;
  color: var(--text);
}
.version-commit { margin: 0; font-size: 12px; color: var(--text-faint); }
.found-label { margin: 0 0 4px; font-size: 12px; color: var(--text-muted); }
.badge-latest {
  display: inline-flex;
  align-self: flex-start;
  margin-top: 2px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 650;
  color: var(--ok);
  background: color-mix(in srgb, var(--ok) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--ok) 35%, transparent);
}
</style>
