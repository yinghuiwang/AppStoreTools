<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { MessagePlugin } from "tdesign-vue-next";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import ExampleHelp from "@/components/ExampleHelp.vue";
import LocalePicker from "@/components/LocalePicker.vue";
import { useBrowse } from "@/composables/useBrowse";
import { useListingWorkflow, type ListingSnapshot } from "@/composables/useListingWorkflow";
import { useLocaleCatalog } from "@/composables/useLocaleCatalog";
import { clearAgentPageContext, setAgentPageContext } from "@/composables/useAgentContext";
import { useRightRail } from "@/composables/useRightRail";

const emit = defineEmits<{ next: [] }>();
const { t } = useI18n();
const browse = useBrowse();
const workflow = useListingWorkflow();
const rail = useRightRail();
const catalog = useLocaleCatalog({ presence: false });

type Source = "csv" | "asc" | "blank" | "agent";
const source = ref<Source>("blank");
const pulling = ref(false);
const opening = ref(false);
const error = ref("");
const pickerOpen = ref(false);
const blankLocales = ref<string[]>(["en-US"]);

const hasFile = computed(() => workflow.exists.value && workflow.hasContent.value);
const csvPath = computed({
  get: () => workflow.csvPath.value,
  set: (value: string | number) => workflow.setCsvPath(String(value ?? "")),
});
const shotsDir = computed({
  get: () => workflow.screenshotsDir.value,
  set: (value: string | number) => workflow.setScreenshotsDir(String(value ?? "")),
});

watch(
  hasFile,
  (ready) => {
    if (ready && source.value === "blank") source.value = "csv";
  },
  { immediate: true },
);

onMounted(() => {
  void catalog.load();
});

const localeOptions = computed(() =>
  catalog.rows.value.map((row) => ({
    label: catalog.labelFor(row.code),
    value: row.code,
  })),
);

async function browseCsv() {
  const path = await browse.pick({ mode: "file", ext: ".csv", initialPath: workflow.csvPath.value });
  if (!path) return;
  opening.value = true;
  workflow.setCsvPath(path);
  await workflow.load(path);
  opening.value = false;
  if (!workflow.alert.value) MessagePlugin.success(t("listing.file_opened"));
}

async function browseShots() {
  const path = await browse.pick({ mode: "dir", initialPath: workflow.screenshotsDir.value });
  if (path) workflow.setScreenshotsDir(path);
}

async function pullAsc() {
  pulling.value = true;
  error.value = "";
  try {
    const data = await httpJson<{ snapshot: ListingSnapshot }>("/api/listing/pull/text", {
      method: "POST",
      body: JSON.stringify({
        csv_path: workflow.csvPath.value,
        screenshots_dir: workflow.screenshotsDir.value,
        expected_mtime: workflow.mtime.value,
        write: false,
      }),
    });
    workflow.applySnapshot(data.snapshot, { dirty: true, storeDraft: true });
    MessagePlugin.success(t("listing.draft_applied"));
  } catch (err) {
    error.value = err instanceof ApiError ? apiErrorMessage(err) : String(err);
  } finally {
    pulling.value = false;
  }
}

function blank() {
  const codes = blankLocales.value.length ? blankLocales.value : ["en-US"];
  workflow.applySnapshot(
    { locales: codes.map((locale) => workflow.blankLocale(locale)) },
    { dirty: true, storeDraft: false },
  );
  MessagePlugin.success(t("listing.draft_applied"));
}

function openAgent() {
  clearAgentPageContext();
  setAgentPageContext({ route: "/listing", phase: "create" });
  rail.openAgent({ seedPrompt: t("listing.agent_seed_create") });
}
</script>

<template>
  <div class="create-stack">
    <p v-if="hasFile" class="skip-row">
      {{ t("listing.current_file") }} <code>{{ workflow.csvPath.value }}</code>
      ·
      <button type="button" class="link" @click="emit('next')">{{ t("listing.skip_to_preview") }}</button>
    </p>
    <p v-if="error" class="err">{{ error }}</p>
    <t-tabs class="create-tabs" v-model="source">
      <t-tab-panel :label="t('listing.tab.csv')" value="csv" :destroy-on-hide="false">
        <div class="tab-body">
          <p class="muted">{{ t("listing.csv_path_help") }}</p>
          <div class="field">
            <ExampleHelp kind="csv" :label="t('metadata.csv_path')" />
            <div class="field-row">
              <t-input v-model="csvPath" />
              <t-button :loading="opening" @click="browseCsv">{{ t("filebrowser.browse") }}</t-button>
            </div>
          </div>
          <div class="field">
            <ExampleHelp kind="shots" :label="t('metadata.shots_dir')" />
            <div class="field-row">
              <t-input v-model="shotsDir" />
              <t-button @click="browseShots">{{ t("filebrowser.browse") }}</t-button>
            </div>
          </div>
        </div>
      </t-tab-panel>
      <t-tab-panel :label="t('listing.tab.asc')" value="asc" :destroy-on-hide="false">
        <div class="tab-body">
          <p class="muted">{{ t("listing.asc_help") }}</p>
          <t-button theme="primary" :loading="pulling" :disabled="workflow.emptyProfile.value" @click="pullAsc">{{ t("listing.asc_import") }}</t-button>
        </div>
      </t-tab-panel>
      <t-tab-panel :label="t('listing.tab.blank')" value="blank" :destroy-on-hide="false">
        <div class="tab-body">
          <p class="muted">{{ t("listing.source.blank_hint") }}</p>
          <div class="field-row">
            <t-select
              class="locale-add"
              v-model="blankLocales"
              multiple
              filterable
              :placeholder="t('listing.blank_locales')"
              :options="localeOptions"
              :popup-props="{ attach: 'body' }"
            />
            <t-button size="small" variant="outline" @click="pickerOpen = true">{{ t("metadata.locales_btn") }}</t-button>
          </div>
          <t-button theme="primary" @click="blank">{{ t("listing.source.blank") }}</t-button>
        </div>
      </t-tab-panel>
      <t-tab-panel :label="t('listing.tab.agent')" value="agent" :destroy-on-hide="false">
        <div class="tab-body">
          <p class="muted">{{ t("listing.source.agent_hint") }}</p>
          <t-button theme="primary" @click="openAgent">{{ t("listing.source.agent") }}</t-button>
        </div>
      </t-tab-panel>
    </t-tabs>
    <LocalePicker v-model:open="pickerOpen" />
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
.create-tabs :deep(.t-tabs__header) { flex: 0 0 auto; }
.create-tabs :deep(.t-tabs__content) { overflow: visible; background: transparent; }
.create-tabs :deep(.t-tab-panel) { overflow: visible; background: transparent; }
.tab-body { display: flex; flex-direction: column; gap: 12px; padding: 16px 0 4px; }
.muted { color: var(--text-muted); font-size: 12px; }
.err { color: var(--err); margin: 0; }
.field-row { display: flex; gap: 8px; align-items: center; }
.field { display: flex; flex-direction: column; gap: 6px; }
.locale-add { min-width: 240px; flex: 1; }
</style>
