<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { ApiError, apiErrorMessage, httpForm, httpJson } from "@/api/http";
import ExampleHelp from "@/components/ExampleHelp.vue";
import TaskRunBar from "@/components/TaskRunBar.vue";
import { useBrowse } from "@/composables/useBrowse";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";
import { useListingTab, useTaskPagePhase } from "@/composables/useTaskPagePhase";

const { t } = useI18n();
const route = useRoute();
const browse = useBrowse();
const { snapshot } = useProfile();
const rail = useRightRail();
const { setActiveTask } = useTaskLog();
const { listingTab } = useListingTab();
const { isForm, isRun, taskId, enterRun, backToForm } = useTaskPagePhase("listing-upload");
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const csvPath = ref(snapshot.value?.paths.csv || "data/appstore_info.csv");
const shotsDir = ref(snapshot.value?.paths.screenshots || "data/screenshots");
const includeMetadata = ref(true);
const includeScreenshots = ref(true);
const dryRun = ref(false);
const verbose = ref(false);
const checkMsg = ref("");
const alert = ref("");
const checkingEnv = ref(false);

async function pickCsv() {
  const path = await browse.pick({ mode: "file", ext: ".csv", initialPath: csvPath.value });
  if (path) csvPath.value = path;
}

async function pickShots() {
  const path = await browse.pick({ mode: "dir", initialPath: shotsDir.value });
  if (path) shotsDir.value = path;
}

async function checkEnv() {
  alert.value = "";
  checkingEnv.value = true;
  try {
    const data = await httpJson<{ ok?: boolean; message?: string }>("/api/metadata/check", { method: "POST" });
    checkMsg.value = data.message || "";
    if (data.ok === false && data.message) alert.value = data.message;
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  } finally {
    checkingEnv.value = false;
  }
}

async function run() {
  alert.value = "";
  try {
    const body = new URLSearchParams();
    body.set("csv_path", csvPath.value);
    body.set("screenshots_dir", shotsDir.value);
    body.set("include_metadata", includeMetadata.value ? "true" : "");
    body.set("include_screenshots", includeScreenshots.value ? "true" : "");
    body.set("dry_run", dryRun.value ? "true" : "");
    body.set("verbose", verbose.value ? "true" : "");
    const { task_id } = await httpForm<{ task_id: string }>("/api/metadata/run", body);
    enterRun(task_id);
    rail.openLogs(task_id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  }
}

watch(listingTab, (tab) => {
  if (tab === "upload" && isRun.value && taskId.value) setActiveTask(taskId.value);
});

onMounted(() => {
  const action = String(route.query.action || "");
  if (action === "check") {
    void checkEnv();
  } else if (action === "all") {
    includeMetadata.value = true;
    includeScreenshots.value = true;
  } else if (action === "metadata") {
    includeMetadata.value = true;
    includeScreenshots.value = false;
  } else if (action === "screenshots") {
    includeMetadata.value = false;
    includeScreenshots.value = true;
  }
});
</script>

<template>
  <div class="page-stack">
    <el-alert v-if="empty" type="warning" show-icon :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </el-alert>
    <el-alert v-if="alert" type="error" show-icon :title="alert" />
    <div v-if="isForm" class="card">
      <div class="field">
        <ExampleHelp kind="csv" :label="t('metadata.csv_path')" />
        <div class="field-row">
          <input v-model="csvPath" class="field-input" />
          <el-button @click="pickCsv">{{ t("filebrowser.browse") }}</el-button>
        </div>
      </div>
      <div class="field">
        <ExampleHelp kind="shots" :label="t('metadata.shots_dir')" />
        <div class="field-row">
          <input v-model="shotsDir" class="field-input" />
          <el-button @click="pickShots">{{ t("filebrowser.browse") }}</el-button>
        </div>
      </div>
      <div>
        <span class="lbl">{{ t("metadata.scope") }}</span>
        <label class="check"><input v-model="includeMetadata" type="checkbox" /> {{ t("metadata.scope_metadata") }}</label>
        <label class="check"><input v-model="includeScreenshots" type="checkbox" /> {{ t("metadata.scope_screenshots") }}</label>
      </div>
      <label class="check"><input v-model="dryRun" type="checkbox" /> {{ t("common.dry_run") }}</label>
      <label class="check"><input v-model="verbose" type="checkbox" /> {{ t("build.verbose") }}</label>
      <div class="field-row">
        <el-button :disabled="empty" :loading="checkingEnv" @click="checkEnv">{{ t("common.check_env") }}</el-button>
        <el-button type="primary" :disabled="empty" @click="run">{{ t("common.submit") }}</el-button>
      </div>
      <p v-if="checkMsg">{{ checkMsg }}</p>
    </div>
    <TaskRunBar v-if="isRun && taskId" :task-id="taskId" @back="backToForm" />
  </div>
</template>

<style scoped>
.card { display: flex; flex-direction: column; gap: 10px; }
.check { display: flex; gap: 8px; align-items: center; }
.lbl { display: block; font-size: 12px; color: var(--text-muted); }
</style>
