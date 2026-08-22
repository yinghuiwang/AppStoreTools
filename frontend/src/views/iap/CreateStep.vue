<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { MessagePlugin } from "tdesign-vue-next";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import ExampleHelp from "@/components/ExampleHelp.vue";
import { useBrowse } from "@/composables/useBrowse";
import { useIapWorkflow, type IapGroup, type IapItem, type IapSnapshot } from "@/composables/useIapWorkflow";
import { useRightRail } from "@/composables/useRightRail";

const emit = defineEmits<{ next: [] }>();
const { t } = useI18n();
const browse = useBrowse();
const workflow = useIapWorkflow();
const rail = useRightRail();

type Source = "table" | "asc" | "json" | "blank" | "agent";
const source = ref<Source>("table");
const tableText = ref("");
const inferring = ref(false);
const inferError = ref("");
const inferResult = ref<{
  snapshot: IapSnapshot;
  needsConfirmation: Array<{ productId: string; name: string; reason: string; kind: string }>;
  groupLevelHelp: string;
  groupLevelBatches: Array<{
    referenceName: string;
    displayName: string;
    subscriptions: Array<{ productId: string; name: string; groupLevel: number | null }>;
  }>;
} | null>(null);
const kindOverrides = ref<Record<string, string>>({});
const groupLevels = ref<Record<string, number>>({});
const pulling = ref(false);
const pullGroups = ref("");
const opening = ref(false);

const hasFile = computed(() => workflow.exists.value && workflow.hasContent.value);
const jsonPath = computed({
  get: () => workflow.iapFile.value,
  set: (value: string | number) => workflow.setIapFile(String(value ?? "")),
});

watch(
  hasFile,
  (ready) => {
    if (ready && source.value === "table") source.value = "json";
  },
  { immediate: true },
);

async function runInfer() {
  inferError.value = "";
  inferring.value = true;
  try {
    const data = await httpJson<{
      snapshot: IapSnapshot;
      needsConfirmation: typeof inferResult.value extends infer T ? T extends { needsConfirmation: infer N } ? N : never : never;
      groupLevelHelp: string;
      groupLevelBatches: NonNullable<typeof inferResult.value>["groupLevelBatches"];
      products?: Array<{ productId: string; kind: string }>;
    }>("/api/iap/infer", {
      method: "POST",
      body: JSON.stringify({ text: tableText.value }),
    });
    inferResult.value = {
      snapshot: data.snapshot,
      needsConfirmation: data.needsConfirmation || [],
      groupLevelHelp: data.groupLevelHelp,
      groupLevelBatches: data.groupLevelBatches || [],
    };
    const levels: Record<string, number> = {};
    for (const batch of data.groupLevelBatches || []) {
      batch.subscriptions.forEach((sub, idx) => {
        levels[sub.productId] = idx + 1;
      });
    }
    groupLevels.value = levels;
    const kinds: Record<string, string> = {};
    for (const row of data.needsConfirmation || []) kinds[row.productId] = "CONSUMABLE";
    kindOverrides.value = kinds;
  } catch (err) {
    inferError.value = err instanceof ApiError ? apiErrorMessage(err) : String(err);
  } finally {
    inferring.value = false;
  }
}

function ensureGroup(snap: IapSnapshot, name: string): IapGroup {
  snap.subscriptionGroups = snap.subscriptionGroups || [];
  let group = snap.subscriptionGroups.find((row) => row.referenceName === name);
  if (!group) {
    group = {
      referenceName: name,
      localizations: { "en-US": { name }, "zh-Hans": { name } },
      subscriptions: [],
    };
    snap.subscriptionGroups.push(group);
  }
  group.subscriptions = group.subscriptions || [];
  return group;
}

function itemToSubscription(item: IapItem) {
  return {
    productId: item.productId,
    name: item.name || item.productId,
    subscriptionPeriod: "ONE_MONTH",
    familySharable: false,
    availableInAllTerritories: item.availableInAllTerritories !== false,
    price: item.price,
    localizations: item.localizations || {},
    review: item.review || { screenshot: "", note: "" },
  };
}

function applyInfer() {
  if (!inferResult.value) return;
  const snap = JSON.parse(JSON.stringify(inferResult.value.snapshot)) as IapSnapshot;
  const remaining: IapItem[] = [];
  for (const item of snap.items) {
    const override = kindOverrides.value[item.productId];
    if (override === "SUBSCRIPTION") {
      ensureGroup(snap, "Membership").subscriptions!.push(itemToSubscription(item));
      continue;
    }
    if (override === "NON_CONSUMABLE" || override === "CONSUMABLE") {
      item.inAppPurchaseType = override;
    }
    remaining.push(item);
  }
  snap.items = remaining;
  for (const group of snap.subscriptionGroups) {
    for (const sub of group.subscriptions || []) {
      const level = groupLevels.value[sub.productId];
      if (level) sub.groupLevel = level;
    }
  }
  workflow.applySnapshot(snap, { dirty: true, storeDraft: false });
  MessagePlugin.success(t("iap.draft_applied"));
}

async function pullAsc() {
  pulling.value = true;
  inferError.value = "";
  try {
    const groups = pullGroups.value.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean);
    const data = await httpJson<{ snapshot: IapSnapshot }>("/api/iap/pull", {
      method: "POST",
      body: JSON.stringify({
        iapFile: workflow.iapFile.value,
        expected_mtime: workflow.mtime.value,
        groupNames: groups,
        write: false,
      }),
    });
    workflow.applySnapshot(data.snapshot, { dirty: true, storeDraft: true });
    MessagePlugin.success(t("iap.draft_applied"));
  } catch (err) {
    inferError.value = err instanceof ApiError ? apiErrorMessage(err) : String(err);
  } finally {
    pulling.value = false;
  }
}

async function browseJson() {
  const path = await browse.pick({ mode: "file", ext: ".json", initialPath: workflow.iapFile.value });
  if (!path) return;
  opening.value = true;
  workflow.setIapFile(path);
  await workflow.load(path);
  opening.value = false;
  if (!workflow.alert.value) MessagePlugin.success(t("iap.file_opened"));
}

function blank() {
  workflow.applySnapshot(workflow.emptySnapshot(), { dirty: true, storeDraft: false });
  MessagePlugin.success(t("iap.draft_applied"));
}

function openAgent() {
  rail.openAgent({ seedPrompt: t("iap.agent_seed_create") });
}
</script>

<template>
  <div class="create-stack">
    <p v-if="hasFile" class="skip-row">
      {{ t("iap.current_file") }} <code>{{ workflow.iapFile.value }}</code>
      ·
      <button type="button" class="link" @click="emit('next')">{{ t("iap.skip_to_edit") }}</button>
    </p>
    <p v-if="inferError" class="err">{{ inferError }}</p>
    <t-tabs class="create-tabs" v-model="source">
      <t-tab-panel :label="t('iap.tab.json')" value="json" :destroy-on-hide="false">
        <div class="tab-body">
          <p class="muted">{{ t("iap.json_path_help") }}</p>
          <div class="field">
            <ExampleHelp kind="iap" :label="t('iap.file')" />
            <div class="field-row">
              <t-input
                v-model="jsonPath"
                :status="workflow.fieldErrors.value.file ? 'error' : undefined"
                :tips="workflow.fieldErrors.value.file || undefined"
              />
              <t-button :loading="opening" @click="browseJson">{{ t("filebrowser.browse") }}</t-button>
            </div>
          </div>
        </div>
      </t-tab-panel>
      <t-tab-panel :label="t('iap.tab.table')" value="table" :destroy-on-hide="false">
        <div class="tab-body">
          <p class="muted">{{ t("iap.table_help") }}</p>
          <t-textarea v-model="tableText" :autosize="{ minRows: 6, maxRows: 14 }" />
          <div class="field-row">
            <t-button :loading="inferring" :disabled="!tableText.trim()" @click="runInfer">{{ t("iap.infer") }}</t-button>
          </div>
          <div v-if="inferResult" class="confirm">
            <section v-if="inferResult.needsConfirmation.length" class="mod">
              <h3 class="mod-title">{{ t("iap.confirm_kinds") }}</h3>
              <div v-for="row in inferResult.needsConfirmation" :key="row.productId" class="nested kind-row">
                <div>
                  <span class="loc-code">{{ row.productId }}</span>
                  <div>{{ row.name || row.productId }}</div>
                  <div class="muted">{{ row.reason }}</div>
                </div>
                <t-select v-model="kindOverrides[row.productId]" :options="[
                  { label: t('iap.kind_consumable'), value: 'CONSUMABLE' },
                  { label: t('iap.kind_non_consumable'), value: 'NON_CONSUMABLE' },
                  { label: t('iap.kind_sub'), value: 'SUBSCRIPTION' },
                ]" />
              </div>
            </section>
            <t-alert theme="info" :title="t('iap.group_level_title')">
              <pre class="help-pre">{{ inferResult.groupLevelHelp }}</pre>
            </t-alert>
            <section v-for="batch in inferResult.groupLevelBatches" :key="batch.referenceName" class="mod">
              <h3 class="mod-title">{{ batch.displayName || batch.referenceName }}</h3>
              <div v-for="sub in batch.subscriptions" :key="sub.productId" class="nested kind-row">
                <div>
                  <span class="loc-code">{{ sub.productId }}</span>
                  <div>{{ sub.name }}</div>
                </div>
                <t-input-number v-model="groupLevels[sub.productId]" :min="1" theme="column" />
              </div>
            </section>
            <t-button theme="primary" @click="applyInfer">{{ t("iap.apply_draft") }}</t-button>
          </div>
        </div>
      </t-tab-panel>
      <t-tab-panel :label="t('iap.tab.asc')" value="asc" :destroy-on-hide="false">
        <div class="tab-body">
          <p class="muted">{{ t("iap.asc_help") }}</p>
          <div class="field">
            <span>{{ t("iap.asc_groups") }}</span>
            <t-input v-model="pullGroups" :placeholder="t('iap.asc_groups_ph')" />
          </div>
          <t-button theme="primary" :loading="pulling" :disabled="workflow.emptyProfile.value" @click="pullAsc">{{ t("iap.asc_import") }}</t-button>
        </div>
      </t-tab-panel>
      <t-tab-panel :label="t('iap.tab.blank')" value="blank" :destroy-on-hide="false">
        <div class="tab-body">
          <p class="muted">{{ t("iap.source.blank_hint") }}</p>
          <t-button theme="primary" @click="blank">{{ t("iap.source.blank") }}</t-button>
        </div>
      </t-tab-panel>
      <t-tab-panel :label="t('iap.tab.agent')" value="agent" :destroy-on-hide="false">
        <div class="tab-body">
          <p class="muted">{{ t("iap.source.agent_hint") }}</p>
          <t-button theme="primary" @click="openAgent">{{ t("iap.source.agent") }}</t-button>
        </div>
      </t-tab-panel>
    </t-tabs>
  </div>
</template>

<style scoped>
.create-stack { display: flex; flex-direction: column; gap: 12px; }
.skip-row { margin: 0; font-size: 13px; }
.link { background: none; border: 0; color: var(--accent); cursor: pointer; padding: 0; }
.create-tabs {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  overflow: visible;
  background: transparent;
}
.create-tabs :deep(.t-tabs__header) {
  flex: 0 0 auto;
}
.create-tabs :deep(.t-tabs__content) {
  overflow: visible;
  background: transparent;
}
.create-tabs :deep(.t-tab-panel) {
  overflow: visible;
  background: transparent;
}
.tab-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 0 4px;
}
.muted { color: var(--text-muted); font-size: 12px; }
.err { color: var(--err); margin: 0; }
.kind-row { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.field-row { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.help-pre { white-space: pre-wrap; font-size: 12px; margin: 8px 0 0; }
.confirm { display: flex; flex-direction: column; gap: 16px; }
.mod {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
}
.mod-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}
.nested {
  margin-left: 8px;
  padding: 10px 12px;
  background: var(--raised);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.loc-code {
  display: block;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
}
.field { display: flex; flex-direction: column; gap: 6px; }
</style>
