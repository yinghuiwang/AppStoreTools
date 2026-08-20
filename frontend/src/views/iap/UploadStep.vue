<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { MessagePlugin } from "tdesign-vue-next";
import { httpForm, httpJson } from "@/api/http";
import TaskRunBar from "@/components/TaskRunBar.vue";
import { useBrowse } from "@/composables/useBrowse";
import { useIapWorkflow } from "@/composables/useIapWorkflow";
import { useImageViewer } from "@/composables/useImageViewer";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskPagePhase } from "@/composables/useTaskPagePhase";

type Target = {
  kind: string;
  id: string;
  productId: string;
  name: string;
  groupName: string;
  defaultPath: string;
  pathStatus: string;
};

const { t } = useI18n();
const browse = useBrowse();
const viewer = useImageViewer();
const workflow = useIapWorkflow();
const rail = useRightRail();
const { isRun, taskId, enterRun, backToForm } = useTaskPagePhase("iap");

const items = computed(() => workflow.planItems.value);
const loading = computed(() => workflow.planLoading.value);
const planError = computed(() => workflow.planError.value);
const shotsOpen = ref(false);
const targets = ref<Target[]>([]);
const paths = ref<Record<string, string>>({});
const scanning = ref(false);
const reviewDry = ref(false);
const reviewVerbose = ref(false);
const stillMissing = ref(false);
const pathErrors = ref<Record<string, string>>({});

const counts = computed(() => ({
  create: items.value.filter((i) => i.action === "create").length,
  update: items.value.filter((i) => i.action === "update").length,
  skip: items.value.filter((i) => i.action === "skip").length,
}));

const tableRows = computed(() =>
  items.value.map((row) => ({
    ...row,
    actionLabel: t(`iap.action_${row.action}`),
  })),
);

const columns = computed(() => [
  { colKey: "productId", title: "productId" },
  { colKey: "type", title: t("iap.col_type") },
  { colKey: "actionLabel", title: t("iap.action") },
]);

async function refreshStore() {
  await workflow.ensureCompare({ force: true });
}

async function openExistingJson() {
  const path = await browse.pick({ mode: "file", ext: ".json", initialPath: workflow.iapFile.value });
  if (!path) return;
  workflow.setIapFile(path);
  await workflow.load(path);
}

async function start() {
  const missing: string[] = [];
  if (workflow.emptyProfile.value) missing.push(t("nav.select_app"));
  if (!(workflow.iapFile.value || "").trim()) {
    const msg = t("iap.need_file");
    workflow.fieldErrors.value.file = msg;
    missing.push(msg);
  }
  if (missing.length) {
    MessagePlugin.warning(missing.join("；"));
    return;
  }
  if (workflow.dirty.value || workflow.storeDraft.value) {
    const saved = await workflow.save();
    if (!saved) return;
  }
  const body = new URLSearchParams({
    iap_file: workflow.iapFile.value,
    dry_run: workflow.dryRun.value ? "true" : "",
    update_existing: workflow.updateExisting.value ? "true" : "",
    verbose: workflow.verbose.value ? "true" : "",
  });
  const { task_id } = await httpForm<{ task_id: string }>("/api/iap/run", body);
  enterRun(task_id);
  rail.openLogs(task_id);
}

async function scan() {
  scanning.value = true;
  try {
    const data = await httpJson<{ targets: Target[]; count: number }>("/api/iap/review-screenshots/scan", {
      method: "POST",
      body: JSON.stringify({ iapFile: workflow.iapFile.value }),
    });
    targets.value = data.targets || [];
    stillMissing.value = targets.value.length > 0;
    const next: Record<string, string> = {};
    for (const item of targets.value) next[item.id] = item.defaultPath || "";
    paths.value = next;
    if (targets.value.length) shotsOpen.value = true;
  } finally {
    scanning.value = false;
  }
}

function previewPath(path: string) {
  const root = path.replace(/[/\\][^/\\]+$/, "") || ".";
  viewer.show([{
    src: `/api/listing/thumb?path=${encodeURIComponent(path)}&root=${encodeURIComponent(root)}`,
    title: path,
  }]);
}

async function pickPath(id: string) {
  const path = await browse.pick({ mode: "file", ext: ".png,.jpg,.jpeg", initialPath: paths.value[id] });
  if (path) {
    paths.value[id] = path;
    if (pathErrors.value[id]) {
      const next = { ...pathErrors.value };
      delete next[id];
      pathErrors.value = next;
    }
  }
}

async function uploadShots() {
  const missing: string[] = [];
  pathErrors.value = {};
  if (workflow.emptyProfile.value) missing.push(t("nav.select_app"));
  if (!targets.value.length) missing.push(t("iap.no_missing"));
  const payload = targets.value
    .filter((item) => (paths.value[item.id] || "").trim())
    .map((item) => ({
      kind: item.kind,
      id: item.id,
      productId: item.productId,
      path: paths.value[item.id],
    }));
  if (targets.value.length && !payload.length) {
    const msg = t("iap.pick_path");
    const next: Record<string, string> = {};
    for (const item of targets.value) {
      if (!(paths.value[item.id] || "").trim()) next[item.id] = msg;
    }
    pathErrors.value = next;
    missing.push(msg);
  }
  if (missing.length) {
    MessagePlugin.warning(missing.join("；"));
    return;
  }
  const { task_id } = await httpJson<{ task_id: string }>("/api/iap/review-screenshots/upload", {
    method: "POST",
    body: JSON.stringify({ items: payload, dryRun: reviewDry.value, verbose: reviewVerbose.value }),
  });
  enterRun(task_id);
  rail.openLogs(task_id);
}

function onBack() {
  backToForm();
}

watch(paths, (next) => {
  const ids = Object.keys(pathErrors.value);
  if (!ids.length) return;
  const remaining: Record<string, string> = { ...pathErrors.value };
  let changed = false;
  for (const id of ids) {
    if ((next[id] || "").trim()) {
      delete remaining[id];
      changed = true;
    }
  }
  if (changed) pathErrors.value = remaining;
}, { deep: true });

function toggleShots() {
  shotsOpen.value = !shotsOpen.value;
}

defineExpose({ start });
</script>

<template>
  <div class="upload-stack">
    <p v-if="!workflow.hasContent.value" class="empty-row card">
      {{ t("iap.empty_open") }}
      <t-button size="small" @click="openExistingJson">{{ t("iap.source.json") }}</t-button>
    </p>
    <div class="card">
      <p class="muted">
        {{ workflow.iapFile.value }}
        <template v-if="workflow.compared.value"> · {{ items.length }} {{ t("iap.entries") }}</template>
      </p>
      <t-space class="check-opts" size="small" break-line>
        <t-checkbox v-model="workflow.dryRun.value">{{ t("iap.dry_run") }}</t-checkbox>
        <t-checkbox v-model="workflow.updateExisting.value">{{ t("iap.update_existing") }}</t-checkbox>
        <t-checkbox v-model="workflow.verbose.value">{{ t("build.verbose") }}</t-checkbox>
      </t-space>
      <t-button
        size="small"
        variant="outline"
        :disabled="workflow.emptyProfile.value"
        :loading="loading"
        @click="refreshStore"
      >
        {{ workflow.compared.value ? t("iap.compare.refresh") : t("iap.compare.button") }}
      </t-button>
      <p v-if="workflow.compared.value" class="muted">
        {{ t("iap.plan_counts", { create: counts.create, update: counts.update, skip: counts.skip }) }}
      </p>
      <p v-if="!workflow.planOk.value && !loading" class="muted">{{ planError || t("iap.plan_unchecked") }}</p>
      <p v-else-if="!workflow.compared.value && !loading" class="muted">{{ t("iap.filter.need_compare") }}</p>
      <t-table
        v-if="workflow.compared.value && items.length"
        row-key="productId"
        size="small"
        :data="tableRows"
        :columns="columns"
      />
      <p v-else-if="workflow.compared.value && !loading" class="muted">{{ t("iap.plan_empty") }}</p>
    </div>
    <div class="card">
      <button type="button" class="fold" @click="toggleShots">
        {{ t("iap.review_title") }}
      </button>
      <div v-if="shotsOpen">
        <div class="field-row">
          <t-button :disabled="workflow.emptyProfile.value" :loading="scanning" @click="scan">{{ t("iap.scan_missing") }}</t-button>
        </div>
        <p v-if="targets.length">{{ t("iap.found_missing", { n: targets.length }) }}</p>
        <p v-else class="muted">{{ t("iap.no_missing") }}</p>
        <div v-for="item in targets" :key="item.id" class="nested shot-row">
          <div>
            <span class="loc-code">{{ item.productId }}</span>
            <div>{{ item.name || item.productId }}</div>
            <div class="muted">{{ item.kind === "subscription" ? t("iap.kind_sub") : "IAP" }}</div>
          </div>
          <div class="field-row">
            <t-input
              v-model="paths[item.id]"
              :status="pathErrors[item.id] ? 'error' : undefined"
              :tips="pathErrors[item.id] || undefined"
            />
            <t-button size="small" @click="pickPath(item.id)">{{ t("filebrowser.browse") }}</t-button>
            <img
              v-if="paths[item.id]"
              class="thumb"
              :src="`/api/listing/thumb?path=${encodeURIComponent(paths[item.id])}&root=${encodeURIComponent(paths[item.id].replace(/[/\\\\][^/\\\\]+$/, '') || '.')}`"
              alt=""
              @click="previewPath(paths[item.id])"
            />
          </div>
        </div>
        <t-space class="check-opts" size="small" break-line>
          <t-checkbox v-model="reviewDry">{{ t("iap.preview") }}</t-checkbox>
          <t-checkbox v-model="reviewVerbose">{{ t("build.verbose") }}</t-checkbox>
        </t-space>
        <t-button theme="primary" @click="uploadShots">{{ t("iap.upload_shots") }}</t-button>
      </div>
    </div>
    <TaskRunBar v-if="isRun && taskId" :task-id="taskId" @back="onBack" />
    <t-alert v-if="stillMissing && !isRun" theme="warning" :title="t('iap.still_missing_shots')" />
  </div>
</template>

<style scoped>
.upload-stack { display: flex; flex-direction: column; gap: 12px; }
.card { display: flex; flex-direction: column; gap: 10px; }
.empty-row { display: flex; flex-direction: row; align-items: center; gap: 8px; margin: 0; font-size: 13px; }
.muted { color: var(--text-muted); font-size: 12px; }
.field-row { display: flex; gap: 8px; align-items: flex-start; }
.check-opts {
  width: fit-content;
  max-width: 100%;
}
.check-opts :deep(.t-checkbox) {
  display: inline-flex;
  align-items: center;
  width: auto;
  flex: 0 0 auto;
}
.check-opts :deep(.t-checkbox__label) {
  padding-left: 0;
  margin-left: 8px;
}
.nested {
  margin: 0 0 8px 8px;
  padding: 10px 12px;
  background: var(--raised);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.shot-row { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.loc-code { display: block; font-size: 11px; font-weight: 500; color: var(--text-muted); }
.thumb { width: 48px; height: 48px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border); }
.fold {
  background: none;
  border: 0;
  color: inherit;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
  text-align: left;
}
</style>
