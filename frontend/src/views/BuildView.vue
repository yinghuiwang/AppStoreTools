<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { ApiError, apiErrorMessage, httpForm, httpJson } from "@/api/http";
import BuildStageProgress from "@/components/BuildStageProgress.vue";
import PageLoading from "@/components/PageLoading.vue";
import { useBrowse } from "@/composables/useBrowse";
import { rememberFormPath } from "@/composables/useFormPaths";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskPagePhase } from "@/composables/useTaskPagePhase";

type CertRow = { name: string; sha1: string };
type ProfileRow = {
  name: string;
  path: string;
  team_id?: string;
  bundle_id?: string;
  expiration?: string;
};
type ArchiveMatch = {
  path: string;
  marketing_version: string;
  build_number: string;
  created?: string;
};
type VersionInfo = { marketing_version: string; build_number: string };

type Options = {
  ok?: boolean;
  error?: string;
  project?: string;
  kind?: string;
  schemes?: string[];
  selected_scheme?: string;
  certificates?: CertRow[];
  selected_certificate?: string;
  profiles?: ProfileRow[];
  selected_profile?: string;
  bundle_id?: string;
  bundle_id_selected?: string;
  version_info?: VersionInfo | null;
  archive_match?: ArchiveMatch | null;
};

type ScanStatus = "idle" | "running" | "success" | "error";

const { t } = useI18n();
const route = useRoute();
const browse = useBrowse();
const { snapshot } = useProfile();
const rail = useRightRail();
defineOptions({ name: "BuildView" });

const { isForm, isRun, taskId, meta, enterRun, backToForm } = useTaskPagePhase("build");
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const alert = ref("");
const mode = ref<"full" | "build" | "deploy">("full");
const runMode = computed<"full" | "build" | "deploy">(() => {
  const stored = meta.value.runMode;
  if (stored === "full" || stored === "build" || stored === "deploy") return stored;
  return mode.value;
});
const signing = ref("auto");
const project = ref("");
const scheme = ref("");
const destination = ref("testflight");
const ipaPath = ref("");
watch([project, ipaPath], ([proj, ipa]) => {
  rememberFormPath("build.project", proj);
  rememberFormPath("build.ipa_path", ipa);
}, { immediate: true });
const certificate = ref("");
const profileName = ref("");
const verbose = ref(false);
const dryRun = ref(false);
const reuseArchive = ref(false);
const options = ref<Options>({ schemes: [], certificates: [], profiles: [] });
const optionsLoading = ref(false);
const scannedOnce = ref(false);
const scanStatus = ref<ScanStatus>("idle");
const scanMessage = ref("");
const showScanSidebar = computed(() => mode.value !== "deploy");

function scanStepsMessage(): string {
  const steps = [t("build.step_detect")];
  if (signing.value === "manual") steps.push(t("build.step_signing"));
  steps.push(t("build.step_archive"));
  return steps.join(" -> ");
}

async function loadOptions() {
  if (mode.value === "deploy") {
    optionsLoading.value = false;
    scanStatus.value = "idle";
    scanMessage.value = t("build.scan_waiting");
    return;
  }
  optionsLoading.value = true;
  scanStatus.value = "running";
  scanMessage.value = scanStepsMessage();
  try {
    const qs = new URLSearchParams({
      project: project.value,
      scheme: scheme.value,
      signing: signing.value,
      certificate: certificate.value,
    });
    const data = await httpJson<Options>(`/api/build/options?${qs}`);
    options.value = data;
    if (!project.value && data.project) project.value = data.project;
    if (!scheme.value && data.selected_scheme) scheme.value = data.selected_scheme;
    if (!certificate.value && data.selected_certificate) certificate.value = data.selected_certificate;
    if (!profileName.value && data.selected_profile) profileName.value = data.selected_profile;
    if (data.ok) {
      scanStatus.value = "success";
      scanMessage.value = t("build.scan_done");
    } else {
      scanStatus.value = "error";
      scanMessage.value = data.error || t("build.scan_failed");
    }
  } catch (err) {
    scanStatus.value = "error";
    const msg = err instanceof Error ? err.message : String(err);
    scanMessage.value = t("build.options_fail_prefix") + msg;
  } finally {
    optionsLoading.value = false;
    scannedOnce.value = true;
  }
}

async function pickProject() {
  const path = await browse.pick({ mode: "dir", initialPath: project.value });
  if (path) {
    project.value = path;
    scheme.value = "";
    await loadOptions();
  }
}

async function pickIpa() {
  const path = await browse.pick({ mode: "file", ext: ".ipa", initialPath: ipaPath.value });
  if (path) ipaPath.value = path;
}

async function run() {
  alert.value = "";
  try {
    const body = new URLSearchParams();
    body.set("mode", mode.value);
    body.set("project", project.value);
    body.set("scheme", scheme.value);
    body.set("destination", destination.value || "testflight");
    body.set("ipa_path", ipaPath.value);
    body.set("verbose", verbose.value ? "true" : "");
    body.set("signing", signing.value);
    body.set("certificate", certificate.value);
    body.set("provisioning_profile", profileName.value);
    body.set("dry_run", dryRun.value ? "true" : "");
    body.set("reuse_archive", reuseArchive.value ? "true" : "");
    const { task_id } = await httpForm<{ task_id: string }>("/api/build/run", body);
    enterRun(task_id, { runMode: mode.value });
    rail.openLogs(task_id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  }
}

function profileMeta(item: ProfileRow): string {
  const file = item.path.split("/").pop() || item.path;
  const bits = [file];
  if (item.team_id) bits.push(item.team_id);
  if (item.expiration) bits.push(item.expiration);
  return bits.join(" · ");
}

watch(mode, (next) => {
  if (next === "deploy") {
    scanStatus.value = "idle";
    scanMessage.value = t("build.scan_waiting");
  } else {
    void loadOptions();
  }
});
watch([scheme, signing, certificate], () => {
  if (mode.value === "deploy") return;
  void loadOptions();
});
onMounted(() => {
  if (route.query.action === "build-upload") mode.value = "full";
  if (scannedOnce.value) return;
  scanMessage.value = t("build.scan_waiting");
  void loadOptions();
});
</script>

<template>
  <div class="page-stack">
    <h1>{{ t("build.title") }}</h1>
    <t-alert v-if="empty" theme="warning" :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </t-alert>
    <t-alert v-if="alert" theme="error" :title="alert" />

    <div v-if="isForm" class="build-layout" :class="{ 'has-scan': showScanSidebar }">
      <div class="card build-form">
        <label class="field"><span>{{ t("build.mode") }}</span>
          <select v-model="mode" class="field-input">
            <option value="full">{{ t("build.mode_full") }}</option>
            <option value="build">{{ t("build.mode_build") }}</option>
            <option value="deploy">{{ t("build.mode_upload") }}</option>
          </select>
        </label>
        <label v-if="mode !== 'deploy'" class="field"><span>{{ t("build.project_field") }}</span>
          <div class="field-row">
            <input v-model="project" class="field-input" :placeholder="t('build.auto_detect')" />
            <t-button @click="pickProject">{{ t("filebrowser.browse") }}</t-button>
          </div>
        </label>
        <label v-if="mode !== 'deploy'" class="field"><span>{{ t("build.scheme") }}</span>
          <select v-model="scheme" class="field-input">
            <option value="">{{ t("build.auto_detect") }}</option>
            <option v-for="name in options.schemes || []" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <label class="field"><span>{{ t("build.platform") }}</span>
          <select v-model="destination" class="field-input">
            <option value="testflight">TestFlight</option>
            <option value="appstore">App Store</option>
          </select>
        </label>
        <label v-if="mode !== 'deploy'" class="field"><span>{{ t("build.signing") }}</span>
          <select v-model="signing" class="field-input">
            <option value="auto">{{ t("build.signing_auto") }}</option>
            <option value="manual">{{ t("build.signing_manual") }}</option>
          </select>
        </label>
        <template v-if="mode !== 'deploy' && signing === 'manual'">
          <p class="muted">{{ t("build.signing_manual_hint") }}</p>
          <label class="field"><span>{{ t("build.certificate") }}</span>
            <select v-model="certificate" class="field-input">
              <option value="">{{ t("build.auto_detect") }}</option>
              <option v-for="cert in options.certificates || []" :key="cert.sha1" :value="cert.name">{{ cert.name }}</option>
            </select>
          </label>
          <label class="field"><span>{{ t("build.profile") }}</span>
            <select v-model="profileName" class="field-input">
              <option value="">{{ t("build.auto_detect") }}</option>
              <option v-for="item in options.profiles || []" :key="item.path" :value="item.name">{{ item.name }}</option>
            </select>
          </label>
        </template>
        <label v-if="mode === 'deploy'" class="field"><span>{{ t("build.ipa_path") }}</span>
          <div class="field-row">
            <input v-model="ipaPath" class="field-input" />
            <t-button @click="pickIpa">{{ t("filebrowser.browse") }}</t-button>
          </div>
        </label>
        <label class="check"><input v-model="verbose" type="checkbox" /> {{ t("build.verbose") }}</label>
        <label class="check"><input v-model="dryRun" type="checkbox" /> {{ t("build.dry_run") }}</label>
        <label v-if="mode !== 'deploy'" class="check"><input v-model="reuseArchive" type="checkbox" /> {{ t("build.reuse_reuse") }}</label>
        <t-button theme="primary" :disabled="empty || optionsLoading" @click="run">{{ t("common.submit") }}</t-button>
      </div>

      <aside v-if="showScanSidebar" class="card build-scan" aria-live="polite">
        <div class="scan-head">
          <h2>{{ t("build.scan_title") }}</h2>
          <div class="scan-actions">
            <span class="scan-status" :data-status="scanStatus">
              <template v-if="scanStatus === 'running'">{{ t("build.scanning") }}</template>
              <template v-else-if="scanStatus === 'success'">{{ t("build.scan_success") }}</template>
              <template v-else-if="scanStatus === 'error'">{{ t("build.scan_error") }}</template>
            </span>
            <t-button
              size="small"
              :loading="optionsLoading && scannedOnce"
              :disabled="optionsLoading && !scannedOnce"
              @click="loadOptions"
            >{{ t("build.refresh") }}</t-button>
          </div>
        </div>

        <div class="scan-banner" :data-status="scanStatus">
          <PageLoading v-if="optionsLoading && !scannedOnce" size="inline" :text="scanMessage" />
          <span v-else>{{ scanMessage || t("build.scan_waiting") }}</span>
        </div>

        <div v-if="options.ok" class="scan-body">
          <div class="scan-row">
            <div class="scan-label">{{ t("build.project") }}</div>
            <div class="scan-value">{{ options.project || "-" }} ({{ options.kind || "-" }})</div>
          </div>
          <div class="scan-row">
            <div class="scan-label">{{ t("build.scheme_candidates") }}</div>
            <div class="scan-value">
              {{ (options.schemes || []).length ? (options.schemes || []).join(" / ") : t("build.not_detected") }}
            </div>
          </div>
          <div class="scan-row">
            <div class="scan-label">{{ t("build.selected") }}</div>
            <div class="scan-value">{{ options.selected_scheme || t("build.not_selected") }}</div>
          </div>
          <div class="scan-row">
            <div class="scan-label">Bundle ID</div>
            <div class="scan-value">
              {{ options.bundle_id_selected || options.bundle_id || t("build.not_detected") }}
            </div>
          </div>

          <template v-if="signing === 'manual'">
            <div class="scan-row">
              <div class="scan-label">{{ t("build.cert_candidates") }}</div>
              <div v-if="(options.certificates || []).length" class="scan-list">
                <div v-for="item in options.certificates" :key="item.sha1" class="scan-value" :title="item.name">
                  {{ item.name }}
                </div>
              </div>
              <div v-else class="scan-value">{{ t("build.not_detected") }}</div>
            </div>
            <div class="scan-row">
              <div class="scan-label">{{ t("build.current_cert") }}</div>
              <div class="scan-value">{{ options.selected_certificate || t("build.not_selected") }}</div>
            </div>
            <div class="scan-row">
              <div class="scan-label">{{ t("build.profile_candidates") }}</div>
              <div v-if="(options.profiles || []).length" class="scan-list">
                <div v-for="item in options.profiles" :key="item.path" class="profile-card" :title="item.path">
                  <div class="scan-value">{{ item.name || item.path.split("/").pop() }}</div>
                  <div class="scan-meta">{{ profileMeta(item) }}</div>
                </div>
              </div>
              <div v-else class="scan-value">{{ t("build.not_detected") }}</div>
            </div>
            <div class="scan-row">
              <div class="scan-label">{{ t("build.current_profile") }}</div>
              <div class="scan-value">{{ options.selected_profile || t("build.not_selected") }}</div>
            </div>
          </template>

          <div class="scan-row">
            <div class="scan-label">{{ t("build.archive_reuse") }}</div>
            <div v-if="options.archive_match" class="scan-list">
              <div class="scan-value">{{ t("build.hit_prefix") }}{{ options.archive_match.path }}</div>
              <div class="scan-meta">
                {{ t("build.version_prefix") }}{{ options.archive_match.marketing_version }}
                ({{ options.archive_match.build_number }})
              </div>
              <div v-if="options.archive_match.created" class="scan-meta">
                {{ t("build.created_prefix") }}{{ options.archive_match.created }}
              </div>
            </div>
            <div v-else class="scan-value">
              <template v-if="options.version_info">
                {{ t("build.no_reuse") }}{{ options.version_info.marketing_version }}
                ({{ options.version_info.build_number }})
              </template>
              <template v-else>{{ t("build.no_version_info") }}</template>
            </div>
          </div>
        </div>

        <p v-else-if="!optionsLoading" class="scan-hint">{{ t("build.scan_hint") }}</p>
      </aside>
    </div>

    <BuildStageProgress
      v-if="isRun && taskId"
      :task-id="taskId"
      :mode="runMode"
      @back="backToForm"
    />
  </div>
</template>

<style scoped>
h1 { margin: 0; }
.muted { color: var(--text-muted); font-size: 12px; }
.check { display: flex; gap: 8px; align-items: center; margin: 8px 0; }
.card { display: flex; flex-direction: column; gap: 12px; flex: 1 1 auto; }

.build-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  align-items: stretch;
  width: 100%;
  flex: 1 1 auto;
}
.build-layout.has-scan {
  grid-template-columns: minmax(0, 1fr) minmax(280px, 390px);
}
@media (max-width: 1100px) {
  .build-layout.has-scan { grid-template-columns: 1fr; }
  .build-scan { order: 2; }
}

.scan-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.scan-head h2 {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: 600;
}
.scan-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.scan-status {
  font-size: 11px;
  color: var(--text-faint);
}
.scan-status[data-status="running"] { color: var(--accent-dim); }
.scan-status[data-status="success"] { color: var(--ok); }
.scan-status[data-status="error"] { color: var(--err); }

.scan-banner {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--text-muted);
  background: color-mix(in srgb, var(--surface-2, var(--surface)) 80%, transparent);
}
.scan-banner[data-status="running"] {
  border-color: color-mix(in srgb, var(--accent-dim) 35%, var(--border));
  background: color-mix(in srgb, var(--accent-dim) 10%, transparent);
  color: var(--accent-dim);
}
.scan-banner[data-status="success"] {
  border-color: color-mix(in srgb, var(--ok) 35%, var(--border));
  background: color-mix(in srgb, var(--ok) 10%, transparent);
  color: var(--ok);
}
.scan-banner[data-status="error"] {
  border-color: color-mix(in srgb, var(--err) 35%, var(--border));
  background: color-mix(in srgb, var(--err) 10%, transparent);
  color: var(--err);
}

.scan-body { display: flex; flex-direction: column; flex: 1 1 auto; gap: 14px; }
.scan-row { display: flex; flex-direction: column; gap: 4px; }
.scan-label {
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-faint);
}
.scan-value {
  font-size: 13px;
  color: var(--text);
  word-break: break-word;
}
.scan-meta {
  font-size: 11px;
  color: var(--text-muted);
  word-break: break-word;
}
.scan-list { display: flex; flex-direction: column; gap: 6px; }
.profile-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
  background: color-mix(in srgb, var(--surface-2, var(--surface)) 70%, transparent);
}
.scan-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-muted);
}
</style>
