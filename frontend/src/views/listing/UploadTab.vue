<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { ApiError, apiErrorMessage, httpForm, httpJson } from "@/api/http";
import ExampleHelp from "@/components/ExampleHelp.vue";
import TaskRunBar from "@/components/TaskRunBar.vue";
import { useBrowse } from "@/composables/useBrowse";
import { hydrateListingForm } from "@/composables/useFormMemory";
import { rememberFormPath } from "@/composables/useFormPaths";
import { useListingScope } from "@/composables/useListingScope";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";
import { useListingTab, useTaskPagePhase } from "@/composables/useTaskPagePhase";

const { t } = useI18n();
const route = useRoute();
const browse = useBrowse();
const { snapshot } = useProfile();
const scope = useListingScope();
const rail = useRightRail();
const { setActiveTask } = useTaskLog();
const { listingTab } = useListingTab();
const { isForm, isRun, taskId, enterRun, backToForm } = useTaskPagePhase("listing-upload");
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const listing = hydrateListingForm(snapshot.value?.current_profile || "", {
  csv: snapshot.value?.paths.csv || "data/appstore_info.csv",
  screenshots: snapshot.value?.paths.screenshots || "data/screenshots",
});
const csvPath = listing.csv_path;
const shotsDir = listing.screenshots_dir;
const includeMetadata = listing.include_metadata;
const includeScreenshots = listing.include_screenshots;
const dryRun = listing.dry_run;
const verbose = listing.verbose;
watch([csvPath, shotsDir], ([csv, shots]) => {
  rememberFormPath("listing.csv_path", csv);
  rememberFormPath("listing.screenshots_dir", shots);
}, { immediate: true });
const checkMsg = ref("");
const checkDetail = ref<{ version?: string; state?: string } | null>(null);
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
    const data = await httpJson<{
      ok?: boolean;
      message?: string;
      detail?: { version?: string; state?: string };
    }>("/api/metadata/check", { method: "POST" });
    checkMsg.value = data.message || "";
    checkDetail.value = data.detail || null;
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
  if (scope.loaded.value && scope.dirty.value) {
    alert.value = t("metadata.wb_dirty_block");
    return;
  }
  if (
    scope.loaded.value
    && (includeMetadata.value || includeScreenshots.value)
    && !scope.hasMetadataSelection()
    && !scope.hasScreenshotSelection()
  ) {
    alert.value = t("metadata.wb_empty_selection");
    return;
  }
  try {
    const body = new URLSearchParams();
    body.set("csv_path", csvPath.value);
    body.set("screenshots_dir", shotsDir.value);
    body.set("include_metadata", includeMetadata.value ? "true" : "");
    body.set("include_screenshots", includeScreenshots.value ? "true" : "");
    body.set("dry_run", dryRun.value ? "true" : "");
    body.set("verbose", verbose.value ? "true" : "");
    body.set("locales_json", scope.localesJson());
    body.set("fields_by_locale_json", scope.fieldsByLocaleJson());
    body.set("screenshot_scopes_json", scope.screenshotScopesJson());
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
    <t-alert v-if="empty" theme="warning" :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </t-alert>
    <t-alert v-if="alert" theme="error" :title="alert" />
    <div v-if="isForm" class="card">
      <div class="field">
        <ExampleHelp kind="csv" :label="t('metadata.csv_path')" />
        <div class="field-row">
          <t-input v-model="csvPath" />
          <t-button @click="pickCsv">{{ t("filebrowser.browse") }}</t-button>
        </div>
      </div>
      <div class="field">
        <ExampleHelp kind="shots" :label="t('metadata.shots_dir')" />
        <div class="field-row">
          <t-input v-model="shotsDir" />
          <t-button @click="pickShots">{{ t("filebrowser.browse") }}</t-button>
        </div>
      </div>
      <div class="field">
        <span class="lbl">{{ t("metadata.scope") }}</span>
        <div class="field-row scope-row">
          <t-checkbox v-model="includeMetadata">{{ t("metadata.scope_metadata") }}</t-checkbox>
          <t-checkbox v-model="includeScreenshots">{{ t("metadata.scope_screenshots") }}</t-checkbox>
        </div>
      </div>
      <t-checkbox v-model="dryRun">{{ t("common.dry_run") }}</t-checkbox>
      <t-checkbox v-model="verbose">{{ t("build.verbose") }}</t-checkbox>
      <div class="field-row">
        <t-button :disabled="empty" :loading="checkingEnv" @click="checkEnv">{{ t("common.check_env") }}</t-button>
        <t-button theme="primary" :disabled="empty" @click="run">{{ t("common.submit") }}</t-button>
      </div>
      <p v-if="checkMsg">{{ checkMsg }}</p>
      <p v-if="checkDetail?.version" class="muted">
        {{ checkDetail.version }}<span v-if="checkDetail.state"> · {{ checkDetail.state }}</span>
      </p>
    </div>
    <TaskRunBar v-if="isRun && taskId" :task-id="taskId" @back="backToForm" />
  </div>
</template>

<style scoped>
.card { display: flex; flex-direction: column; gap: 10px; }
.lbl { display: block; font-size: 12px; color: var(--text-muted); }
.scope-row { gap: 16px; }
.scope-row :deep(.t-checkbox__label) { margin-left: 6px; }
.muted { color: var(--text-muted); font-size: 12px; }
</style>
