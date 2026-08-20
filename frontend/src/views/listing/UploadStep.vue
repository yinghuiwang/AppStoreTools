<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { ApiError, apiErrorMessage, httpForm, httpJson } from "@/api/http";
import TaskRunBar from "@/components/TaskRunBar.vue";
import { LISTING_FIELDS, useListingScope } from "@/composables/useListingScope";
import { useListingWorkflow } from "@/composables/useListingWorkflow";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";
import { useTaskPagePhase } from "@/composables/useTaskPagePhase";

const { t } = useI18n();
const route = useRoute();
const workflow = useListingWorkflow();
const scope = useListingScope();
const rail = useRightRail();
const { setActiveTask } = useTaskLog();
const { isForm, isRun, taskId, enterRun, backToForm } = useTaskPagePhase("listing-upload");
const alert = ref("");
const checkingEnv = ref(false);
const checkMsg = ref("");
const checkDetail = ref<{ version?: string; state?: string } | null>(null);

const items = computed(() => workflow.planLocales.value);
const loading = computed(() => workflow.planLoading.value);
const planError = computed(() => workflow.planError.value);
const version = computed(() => workflow.planVersion.value);

const tableRows = computed(() =>
  items.value.map((row) => ({
    ...row,
    statusLabel: t(`listing.status.${row.status || "unchecked"}`),
    shotLabel: row.missingScreenshots ? t("listing.status.missing-shot") : "",
  })),
);

const columns = computed(() => [
  { colKey: "locale", title: t("listing.col_locale") },
  { colKey: "statusLabel", title: t("listing.col_status") },
  { colKey: "shotLabel", title: t("metadata.shots_section") },
]);

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

async function refreshStore() {
  await workflow.ensureCompare({ force: true });
}

async function start() {
  alert.value = "";
  if (workflow.dirty.value || workflow.storeDraft.value) {
    const saved = await workflow.save();
    if (!saved) return;
  }
  if (
    (workflow.includeMetadata.value || workflow.includeScreenshots.value)
    && !scope.hasMetadataSelection()
    && !scope.hasScreenshotSelection()
  ) {
    alert.value = t("metadata.wb_empty_selection");
    return;
  }
  try {
    const body = new URLSearchParams();
    body.set("csv_path", workflow.csvPath.value);
    body.set("screenshots_dir", workflow.screenshotsDir.value);
    body.set("include_metadata", workflow.includeMetadata.value ? "true" : "");
    body.set("include_screenshots", workflow.includeScreenshots.value ? "true" : "");
    body.set("dry_run", workflow.dryRun.value ? "true" : "");
    body.set("verbose", workflow.verbose.value ? "true" : "");
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

function onBack() {
  backToForm();
}

onMounted(() => {
  const action = String(route.query.action || "");
  if (action === "check") {
    void checkEnv();
  } else if (action === "all") {
    workflow.includeMetadata.value = true;
    workflow.includeScreenshots.value = true;
  } else if (action === "metadata") {
    workflow.includeMetadata.value = true;
    workflow.includeScreenshots.value = false;
  } else if (action === "screenshots") {
    workflow.includeMetadata.value = false;
    workflow.includeScreenshots.value = true;
  }
  scope.hydrateFromLocal(workflow.snapshot.value.locales);
});

watch(
  () => workflow.snapshot.value.locales,
  (rows) => scope.hydrateFromLocal(rows),
  { deep: true },
);

watch(isRun, (running) => {
  if (running && taskId.value) setActiveTask(taskId.value);
});

defineExpose({ start });
</script>

<template>
  <div class="upload-stack">
    <t-alert v-if="alert" theme="error" :title="alert" />
    <div v-if="isForm" class="card">
      <p class="muted">
        {{ workflow.csvPath.value }}
        <template v-if="workflow.screenshotsDir.value"> · {{ workflow.screenshotsDir.value }}</template>
        <template v-if="workflow.compared.value"> · {{ items.length }} {{ t("listing.entries") }}</template>
      </p>
      <p v-if="version">{{ t("metadata.diff_version", { version: version.versionString || "", state: version.appStoreState || "" }) }}</p>
      <div class="field">
        <span class="lbl">{{ t("metadata.scope") }}</span>
        <div class="field-row scope-row">
          <t-checkbox v-model="workflow.includeMetadata.value">{{ t("metadata.scope_metadata") }}</t-checkbox>
          <t-checkbox v-model="workflow.includeScreenshots.value">{{ t("metadata.scope_screenshots") }}</t-checkbox>
        </div>
      </div>
      <t-space class="check-opts" size="small" break-line>
        <t-checkbox v-model="workflow.dryRun.value">{{ t("common.dry_run") }}</t-checkbox>
        <t-checkbox v-model="workflow.verbose.value">{{ t("build.verbose") }}</t-checkbox>
      </t-space>
      <div class="field-row">
        <t-button :disabled="workflow.emptyProfile.value" :loading="checkingEnv" @click="checkEnv">{{ t("common.check_env") }}</t-button>
        <t-button
          size="small"
          variant="outline"
          :disabled="workflow.emptyProfile.value"
          :loading="loading"
          @click="refreshStore"
        >
          {{ workflow.compared.value ? t("listing.compare.refresh") : t("listing.compare.button") }}
        </t-button>
      </div>
      <p v-if="checkMsg">{{ checkMsg }}</p>
      <p v-if="checkDetail?.version" class="muted">
        {{ checkDetail.version }}<span v-if="checkDetail.state"> · {{ checkDetail.state }}</span>
      </p>
      <p v-if="!workflow.planOk.value && !loading" class="muted">{{ planError || t("listing.plan_unchecked") }}</p>
      <p v-else-if="!workflow.compared.value && !loading" class="muted">{{ t("listing.filter.need_compare") }}</p>
      <t-table
        v-if="workflow.compared.value && items.length"
        row-key="locale"
        size="small"
        :data="tableRows"
        :columns="columns"
      />
      <p v-else-if="workflow.compared.value && !loading" class="muted">{{ t("listing.plan_empty") }}</p>
    </div>
    <div v-if="isForm && scope.loaded.value" class="card">
      <div class="col-select">
        <span class="lbl">{{ t("metadata.col_upload") }}</span>
        <t-checkbox
          v-for="field in LISTING_FIELDS"
          :key="`col-${field}`"
          :checked="scope.allFieldsSelected(field)"
          @change="(on: boolean) => scope.selectAllField(field, on)"
        >
          {{ t(`metadata.field_${field}`) }}
        </t-checkbox>
      </div>
      <div v-for="row in workflow.snapshot.value.locales" :key="row.locale" class="nested">
        <t-checkbox
          :checked="scope.isLocaleSelected(row.locale)"
          @change="(on: boolean) => scope.setLocaleSelected(row.locale, on)"
        >
          <span class="loc-code">{{ row.locale }}</span>
        </t-checkbox>
        <div class="field-row wrap">
          <t-checkbox
            v-for="field in LISTING_FIELDS"
            :key="`${row.locale}-${field}`"
            :checked="scope.isFieldSelected(row.locale, field)"
            @change="(on: boolean) => scope.setFieldSelected(row.locale, field, on)"
          >
            {{ t(`metadata.field_${field}`) }}
          </t-checkbox>
        </div>
      </div>
    </div>
    <TaskRunBar v-if="isRun && taskId" :task-id="taskId" @back="onBack" />
  </div>
</template>

<style scoped>
.upload-stack { display: flex; flex-direction: column; gap: 12px; }
.card { display: flex; flex-direction: column; gap: 10px; }
.muted { color: var(--text-muted); font-size: 12px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field-row { display: flex; gap: 8px; align-items: center; }
.field-row.wrap { flex-wrap: wrap; }
.lbl { display: block; font-size: 12px; color: var(--text-muted); }
.scope-row { gap: 16px; }
.scope-row :deep(.t-checkbox__label) { margin-left: 6px; }
.check-opts { width: fit-content; max-width: 100%; }
.check-opts :deep(.t-checkbox) { display: inline-flex; align-items: center; width: auto; flex: 0 0 auto; }
.check-opts :deep(.t-checkbox__label) { padding-left: 0; margin-left: 8px; }
.col-select { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; }
.nested {
  margin: 0 0 8px 8px;
  padding: 10px 12px;
  background: var(--raised);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.loc-code { font-size: 11px; font-weight: 500; color: var(--text-muted); }
</style>
