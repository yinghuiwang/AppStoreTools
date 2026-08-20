<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { MessagePlugin } from "tdesign-vue-next";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import { LISTING_FIELDS } from "@/composables/useListingScope";
import {
  useListingWorkflow,
  type ListingLocale,
  type ListingPlanLocale,
  type ListingSnapshot,
} from "@/composables/useListingWorkflow";
import { useRightRail } from "@/composables/useRightRail";

const NAME_MIN = 2;
const NAME_MAX = 30;
const SUBTITLE_MAX = 30;
const KEYWORDS_MAX = 100;
const DESCRIPTION_MAX = 4000;

const props = defineProps<{
  visible: boolean;
  title: string;
  draft: ListingLocale;
  plan?: ListingPlanLocale;
}>();

const emit = defineEmits<{
  "update:visible": [boolean];
  confirm: [];
  cancel: [];
  pulled: [];
}>();

const { t } = useI18n();
const workflow = useListingWorkflow();
const rail = useRightRail();
let committed = false;

const fields = computed(() => props.draft.fields);

function len(name: string): number {
  return (fields.value[name] || "").length;
}

function statusFor(name: string): "warning" | undefined {
  const n = len(name);
  if (name === "name" && n > 0 && (n < NAME_MIN || n > NAME_MAX)) return "warning";
  if (name === "subtitle" && n > SUBTITLE_MAX) return "warning";
  if (name === "keywords" && n > KEYWORDS_MAX) return "warning";
  if (name === "description" && n > DESCRIPTION_MAX) return "warning";
  return undefined;
}

function maxFor(name: string): number {
  if (name === "name") return NAME_MAX;
  if (name === "subtitle") return SUBTITLE_MAX;
  if (name === "keywords") return KEYWORDS_MAX;
  if (name === "description") return DESCRIPTION_MAX;
  return 0;
}

function setField(name: string, value: string | number) {
  fields.value[name] = String(value ?? "");
}

const diffFields = computed(() => (props.plan?.fields || []).filter((field) => field.status === "changed" || field.status === "local_only" || field.status === "asc_only"));

async function pullOne() {
  const locale = props.draft.locale;
  if (!locale) return;
  try {
    const data = await httpJson<{ snapshot: ListingSnapshot }>("/api/listing/pull/text", {
      method: "POST",
      body: JSON.stringify({
        csv_path: workflow.csvPath.value,
        screenshots_dir: workflow.screenshotsDir.value,
        expected_mtime: workflow.mtime.value,
        write: false,
        selections: [{ locale, fields: [...LISTING_FIELDS] }],
      }),
    });
    workflow.applySnapshot(data.snapshot, { dirty: true, storeDraft: true });
    committed = true;
    emit("pulled");
    emit("update:visible", false);
  } catch (err) {
    MessagePlugin.error(err instanceof ApiError ? apiErrorMessage(err) : String(err));
  }
}

function openAgent() {
  rail.openAgent({
    seedPrompt: t("listing.agent_seed_edit", { locale: props.draft.locale || "en-US" }),
  });
}

function confirm() {
  committed = true;
  emit("confirm");
  emit("update:visible", false);
}

function cancel() {
  if (committed) {
    committed = false;
    return;
  }
  emit("cancel");
  emit("update:visible", false);
}

function onVisible(value: boolean) {
  emit("update:visible", value);
  if (!value) cancel();
}
</script>

<template>
  <t-dialog
    :visible="visible"
    :header="title"
    width="820px"
    placement="center"
    attach="body"
    :close-on-overlay-click="true"
    @update:visible="onVisible"
  >
    <div class="editor-body dialog-form">
      <div v-if="plan?.status === 'changed' && diffFields.length" class="diff-box">
        <p>{{ t("listing.changed_hint") }}</p>
        <ul>
          <li v-for="field in diffFields" :key="field.field">
            {{ t(`metadata.field_${field.field}`) }}: {{ field.local }} → {{ field.asc }}
          </li>
        </ul>
        <t-button size="small" @click="pullOne">{{ t("listing.overwrite_store") }}</t-button>
      </div>

      <section class="mod">
        <header class="mod-head">
          <h3 class="mod-title">{{ draft.locale }}</h3>
          <t-button size="small" variant="outline" @click="openAgent">{{ t("listing.agent_tweak") }}</t-button>
        </header>
        <label v-for="name in LISTING_FIELDS" :key="name" class="field">
          <span class="lbl">
            {{ t(`metadata.field_${name}`) }}
            <em v-if="maxFor(name)" class="muted">{{ t("listing.char_count", { n: len(name), max: maxFor(name) }) }}</em>
          </span>
          <t-textarea
            v-if="name === 'description'"
            :value="fields[name] || ''"
            :autosize="{ minRows: 6, maxRows: 12 }"
            :status="statusFor(name)"
            @change="(v) => setField(name, v)"
          />
          <t-input
            v-else
            :value="fields[name] || ''"
            :status="statusFor(name)"
            @change="(v) => setField(name, v)"
          />
        </label>
      </section>
    </div>
    <template #footer>
      <t-button variant="outline" @click="cancel">{{ t("common.cancel") }}</t-button>
      <t-button theme="primary" @click="confirm">{{ t("listing.dialog_ok") }}</t-button>
    </template>
  </t-dialog>
</template>

<style scoped>
.editor-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: min(70vh, 720px);
  overflow: auto;
  padding-right: 4px;
}
.mod {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--raised);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
}
.mod-title { margin: 0; font-size: 13px; font-weight: 600; }
.mod-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  justify-content: space-between;
}
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.muted { color: var(--text-muted); font-size: 12px; font-style: normal; }
.diff-box {
  background: var(--raised);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
}
</style>
