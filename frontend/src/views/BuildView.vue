<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { ApiError, apiErrorMessage, httpForm, httpJson } from "@/api/http";
import BuildStageProgress from "@/components/BuildStageProgress.vue";
import PageLoading from "@/components/PageLoading.vue";
import { useBrowse } from "@/composables/useBrowse";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskPagePhase } from "@/composables/useTaskPagePhase";

type Options = {
  ok?: boolean;
  error?: string;
  project?: string;
  schemes?: string[];
  selected_scheme?: string;
  certificates?: { name: string; sha1: string }[];
  selected_certificate?: string;
  profiles?: { name: string; path: string }[];
  selected_profile?: string;
  bundle_id?: string;
};

const { t } = useI18n();
const route = useRoute();
const browse = useBrowse();
const { snapshot } = useProfile();
const rail = useRightRail();
const { isForm, isRun, enterRun, backToForm } = useTaskPagePhase();
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const alert = ref("");
const taskId = ref("");
const mode = ref<"full" | "build" | "deploy">("full");
const runMode = ref<"full" | "build" | "deploy">("full");
const signing = ref("auto");
const project = ref("");
const scheme = ref("");
const destination = ref("testflight");
const ipaPath = ref("");
const certificate = ref("");
const profileName = ref("");
const verbose = ref(false);
const dryRun = ref(false);
const reuseArchive = ref(false);
const options = ref<Options>({ schemes: [], certificates: [], profiles: [] });
const optionsLoading = ref(false);
const optionsReady = ref(false);

async function loadOptions() {
  optionsLoading.value = true;
  try {
    const qs = new URLSearchParams({
      project: project.value,
      scheme: scheme.value,
      signing: signing.value,
      certificate: certificate.value,
    });
    options.value = await httpJson<Options>(`/api/build/options?${qs}`);
    if (!project.value && options.value.project) project.value = options.value.project;
    if (!scheme.value && options.value.selected_scheme) scheme.value = options.value.selected_scheme;
    if (!certificate.value && options.value.selected_certificate) certificate.value = options.value.selected_certificate;
    if (!profileName.value && options.value.selected_profile) profileName.value = options.value.selected_profile;
    optionsReady.value = true;
  } finally {
    optionsLoading.value = false;
  }
}

async function pickProject() {
  const path = await browse.pick({ mode: "dir", initialPath: project.value });
  if (path) {
    project.value = path;
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
    runMode.value = mode.value;
    taskId.value = task_id;
    enterRun();
    rail.openLogs(task_id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  }
}

watch([scheme, signing, certificate], () => { void loadOptions(); });
onMounted(() => {
  if (route.query.action === "build-upload") mode.value = "full";
  void loadOptions();
});
</script>

<template>
  <div class="page-stack">
    <h1>{{ t("build.title") }}</h1>
    <el-alert v-if="empty" type="warning" show-icon :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </el-alert>
    <el-alert v-if="alert" type="error" show-icon :title="alert" />
    <div v-if="isForm" class="card">
      <PageLoading v-if="optionsLoading && !optionsReady" />
      <template v-else>
      <div v-if="optionsLoading" class="field-row">
        <PageLoading size="inline" />
      </div>
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
          <el-button @click="pickProject">{{ t("filebrowser.browse") }}</el-button>
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
      <label class="field"><span>{{ t("build.signing") }}</span>
        <select v-model="signing" class="field-input">
          <option value="auto">{{ t("build.signing_auto") }}</option>
          <option value="manual">{{ t("build.signing_manual") }}</option>
        </select>
      </label>
      <template v-if="signing === 'manual'">
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
          <el-button @click="pickIpa">{{ t("filebrowser.browse") }}</el-button>
        </div>
      </label>
      <label class="check"><input v-model="verbose" type="checkbox" /> {{ t("build.verbose") }}</label>
      <label class="check"><input v-model="dryRun" type="checkbox" /> {{ t("build.dry_run") }}</label>
      <label class="check"><input v-model="reuseArchive" type="checkbox" /> {{ t("build.reuse_reuse") }}</label>
      <el-button type="primary" :disabled="empty || optionsLoading" @click="run">{{ t("common.submit") }}</el-button>
      </template>
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
.card { display: flex; flex-direction: column; gap: 12px; }
</style>
