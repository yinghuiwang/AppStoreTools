<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { MessagePlugin } from "tdesign-vue-next";
import { useAgent } from "@/composables/useAgent";
import { useIapWorkflow } from "@/composables/useIapWorkflow";
import CreateStep from "./iap/CreateStep.vue";
import EditStep from "./iap/EditStep.vue";
import UploadStep from "./iap/UploadStep.vue";

defineOptions({ name: "IapView" });

const STEPS = ["create", "edit", "upload"] as const;
type StepId = (typeof STEPS)[number];

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const workflow = useIapWorkflow();
const { appliedTick } = useAgent();
const uploadRef = ref<{ start: () => Promise<void> } | null>(null);

const step = computed<StepId>({
  get() {
    const raw = String(route.query.step || "");
    if (STEPS.includes(raw as StepId)) return raw as StepId;
    return "create";
  },
  set(value) {
    const next = STEPS.includes(value) ? value : "create";
    void router.replace({ query: { ...route.query, step: next } });
  },
});

const current = computed({
  get(): number {
    const idx = STEPS.indexOf(step.value);
    return idx >= 0 ? idx : 0;
  },
  set(idx: string | number) {
    const n = Number(idx);
    go(STEPS[Number.isInteger(n) ? n : 0] || "create");
  },
});

function go(next: StepId) {
  step.value = next;
}

function itemStatus(index: number): "default" | "process" | "finish" {
  if (index < current.value) return "finish";
  if (index === current.value) return "process";
  return "default";
}

async function ensureLoaded() {
  if (!workflow.loaded.value && !workflow.emptyProfile.value) {
    await workflow.load();
  }
}

onMounted(async () => {
  await ensureLoaded();
});

watch(appliedTick, () => {
  if (workflow.emptyProfile.value) return;
  void workflow.reloadFromDisk();
});

watch(
  () => [workflow.dryRun.value, workflow.updateExisting.value, workflow.verbose.value, workflow.autoTranslate.value, workflow.iapFile.value],
  () => workflow.persistMemory(),
);

async function next() {
  if (step.value === "create") {
    go("edit");
    return;
  }
  if (step.value === "edit") {
    go("upload");
    return;
  }
  await startUpload();
}

function prev() {
  if (step.value === "upload") go("edit");
  else if (step.value === "edit") go("create");
}

function skip() {
  if (step.value === "create") go("edit");
  else if (step.value === "edit") go("upload");
}

async function startUpload() {
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
  await uploadRef.value?.start();
}
</script>

<template>
  <div class="page-stack iap-wizard">
    <div class="iap-head">
      <h1>{{ t("iap.title") }}</h1>
      <t-alert
        v-if="workflow.storeDraft.value"
        theme="warning"
        :title="t('iap.store_draft_banner')"
      >
        <div class="draft-actions">
          <t-button size="small" theme="primary" :loading="workflow.saving.value" @click="workflow.save()">
            {{ t("iap.save_to_json") }}
          </t-button>
          <t-button size="small" variant="outline" @click="workflow.discard()">
            {{ t("iap.discard_draft") }}
          </t-button>
        </div>
      </t-alert>
      <p v-else-if="workflow.dirty.value" class="dirty-bar">
        {{ t("iap.unsaved") }}
        <t-button size="small" theme="primary" :loading="workflow.saving.value" @click="workflow.save()">{{ t("common.save") }}</t-button>
        <t-button size="small" variant="outline" @click="workflow.discard()">{{ t("iap.discard") }}</t-button>
      </p>
    </div>
    <t-alert v-if="workflow.emptyProfile.value" theme="warning" :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </t-alert>
    <t-alert v-if="workflow.alert.value" theme="error" :title="workflow.alert.value" />
    <t-alert v-if="workflow.conflict.value" theme="warning" :title="t('iap.mtime_conflict')">
      <t-button size="small" @click="workflow.reload()">{{ t("iap.reload") }}</t-button>
    </t-alert>
    <t-steps v-model:current="current" :readonly="false" theme="default" class="iap-steps">
      <t-step-item :title="t('iap.step.create')" :status="itemStatus(0)" />
      <t-step-item :title="t('iap.step.edit')" :status="itemStatus(1)" />
      <t-step-item :title="t('iap.step.upload')" :status="itemStatus(2)" />
    </t-steps>
    <div class="iap-body">
      <CreateStep v-if="step === 'create'" @next="go('edit')" />
      <EditStep v-else-if="step === 'edit'" />
      <UploadStep v-else ref="uploadRef" />
    </div>
    <div class="iap-footer">
      <t-button v-if="step !== 'create'" variant="outline" @click="prev">{{ t("iap.prev") }}</t-button>
      <t-button v-if="step !== 'upload'" variant="outline" @click="skip">{{ t("iap.skip") }}</t-button>
      <t-button v-if="step !== 'upload'" theme="primary" :disabled="workflow.emptyProfile.value" @click="next">{{ t("iap.next") }}</t-button>
      <t-button v-else theme="primary" @click="startUpload">
        {{ workflow.dryRun.value ? t("iap.preview_run") : t("iap.start_upload") }}
      </t-button>
    </div>
  </div>
</template>

<style scoped>
h1 { margin: 0 0 8px; }
.iap-wizard {
  --iap-footer-h: 56px;
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.iap-head { display: flex; flex-direction: column; gap: 8px; flex: 0 0 auto; }
.dirty-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 13px;
  color: var(--warn);
}
.draft-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.iap-steps { margin: 4px 0 12px; flex: 0 0 auto; }
.iap-body {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding-bottom: var(--iap-footer-h);
}
.iap-wizard > .iap-footer {
  position: sticky;
  bottom: 0;
  z-index: 5;
  flex: 0 0 auto;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: calc(-1 * var(--iap-footer-h) - 16px);
  padding: 10px 0;
  min-height: var(--iap-footer-h);
  box-sizing: border-box;
  background: var(--bg);
  border-top: 1px solid var(--border);
}
</style>
