<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { useAgent } from "@/composables/useAgent";
import { useListingWorkflow } from "@/composables/useListingWorkflow";
import CreateStep from "./listing/CreateStep.vue";
import PreviewStep from "./listing/PreviewStep.vue";
import UploadStep from "./listing/UploadStep.vue";

defineOptions({ name: "ListingView" });

const STEPS = ["create", "preview", "upload"] as const;
type StepId = (typeof STEPS)[number];

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const workflow = useListingWorkflow();
const { appliedTick } = useAgent();
const uploadRef = ref<{ start: () => Promise<void> } | null>(null);

function mapLegacyQuery(): StepId | "" {
  const action = String(route.query.action || "");
  if (["check", "all", "metadata", "screenshots"].includes(action)) return "upload";
  const tab = String(route.query.tab || "");
  if (tab === "local") return "preview";
  if (tab === "diff" || tab === "upload") return "upload";
  return "";
}

const step = computed<StepId>({
  get() {
    const raw = String(route.query.step || "");
    if (STEPS.includes(raw as StepId)) return raw as StepId;
    const mapped = mapLegacyQuery();
    if (mapped) return mapped;
    return "create";
  },
  set(value) {
    const next = STEPS.includes(value) ? value : "create";
    const { tab: _tab, ...rest } = route.query;
    void router.replace({ query: { ...rest, step: next } });
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
  const raw = String(route.query.step || "");
  const mapped = mapLegacyQuery();
  if (mapped && !STEPS.includes(raw as StepId)) {
    step.value = mapped;
  }
});

watch(appliedTick, () => {
  if (workflow.emptyProfile.value) return;
  void workflow.reload();
});

watch(
  () => [
    workflow.dryRun.value,
    workflow.verbose.value,
    workflow.includeMetadata.value,
    workflow.includeScreenshots.value,
    workflow.autoTranslate.value,
    workflow.csvPath.value,
    workflow.screenshotsDir.value,
  ],
  () => workflow.persistMemory(),
);

async function next() {
  if (step.value === "create") {
    go("preview");
    return;
  }
  if (step.value === "preview") {
    go("upload");
    return;
  }
  await startUpload();
}

function prev() {
  if (step.value === "upload") go("preview");
  else if (step.value === "preview") go("create");
}

function skip() {
  if (step.value === "create") go("preview");
  else if (step.value === "preview") go("upload");
}

async function startUpload() {
  if (workflow.dirty.value || workflow.storeDraft.value) {
    const saved = await workflow.save();
    if (!saved) return;
  }
  await uploadRef.value?.start();
}
</script>

<template>
  <div class="page-stack listing-wizard">
    <div class="listing-head">
      <h1>{{ t("listing.title") }}</h1>
      <t-alert
        v-if="workflow.storeDraft.value"
        theme="warning"
        :title="t('listing.store_draft_banner')"
      >
        <div class="draft-actions">
          <t-button size="small" theme="primary" :loading="workflow.saving.value" @click="workflow.save()">
            {{ t("listing.save_to_csv") }}
          </t-button>
          <t-button size="small" variant="outline" @click="workflow.discard()">
            {{ t("listing.discard_draft") }}
          </t-button>
        </div>
      </t-alert>
      <p v-else-if="workflow.dirty.value" class="dirty-bar">
        {{ t("listing.unsaved") }}
        <t-button size="small" theme="primary" :loading="workflow.saving.value" @click="workflow.save()">{{ t("common.save") }}</t-button>
        <t-button size="small" variant="outline" @click="workflow.discard()">{{ t("listing.discard") }}</t-button>
      </p>
    </div>
    <t-alert v-if="workflow.emptyProfile.value" theme="warning" :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </t-alert>
    <t-alert v-if="workflow.alert.value" theme="error" :title="workflow.alert.value" />
    <t-alert v-if="workflow.conflict.value" theme="warning" :title="t('listing.mtime_conflict')">
      <t-button size="small" @click="workflow.reload()">{{ t("listing.reload") }}</t-button>
    </t-alert>
    <t-steps v-model:current="current" :readonly="false" theme="default" class="listing-steps">
      <t-step-item :title="t('listing.step.create')" :status="itemStatus(0)" />
      <t-step-item :title="t('listing.step.preview')" :status="itemStatus(1)" />
      <t-step-item :title="t('listing.step.upload')" :status="itemStatus(2)" />
    </t-steps>
    <div class="listing-body">
      <CreateStep v-if="step === 'create'" @next="go('preview')" />
      <PreviewStep v-else-if="step === 'preview'" />
      <UploadStep v-else ref="uploadRef" />
    </div>
    <div class="listing-footer">
      <t-button v-if="step !== 'create'" variant="outline" @click="prev">{{ t("listing.prev") }}</t-button>
      <t-button v-if="step !== 'upload'" variant="outline" @click="skip">{{ t("listing.skip") }}</t-button>
      <t-button v-if="step !== 'upload'" theme="primary" :disabled="workflow.emptyProfile.value" @click="next">{{ t("listing.next") }}</t-button>
      <t-button v-else theme="primary" :disabled="workflow.emptyProfile.value" @click="startUpload">
        {{ workflow.dryRun.value ? t("listing.preview_run") : t("listing.start_upload") }}
      </t-button>
    </div>
  </div>
</template>

<style scoped>
h1 { margin: 0 0 8px; }
.listing-wizard {
  --listing-footer-h: 56px;
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.listing-head { display: flex; flex-direction: column; gap: 8px; flex: 0 0 auto; }
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
.listing-steps { margin: 4px 0 12px; flex: 0 0 auto; }
.listing-body {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding-bottom: var(--listing-footer-h);
}
.listing-wizard > .listing-footer {
  position: sticky;
  bottom: 0;
  z-index: 5;
  flex: 0 0 auto;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: calc(-1 * var(--listing-footer-h) - 16px);
  padding: 10px 0;
  min-height: var(--listing-footer-h);
  box-sizing: border-box;
  background: var(--bg);
  border-top: 1px solid var(--border);
}
</style>
