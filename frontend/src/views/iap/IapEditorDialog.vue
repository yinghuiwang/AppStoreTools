<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { MessagePlugin } from "tdesign-vue-next";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import LocalePicker from "@/components/LocalePicker.vue";
import { useBrowse } from "@/composables/useBrowse";
import {
  useIapWorkflow,
  type IapGroup,
  type IapItem,
  type IapSnapshot,
  type IapSubscription,
  type LocMap,
  type PlanItem,
} from "@/composables/useIapWorkflow";
import { useLocaleCatalog } from "@/composables/useLocaleCatalog";
import { useRightRail } from "@/composables/useRightRail";
import IapReviewThumb from "./IapReviewThumb.vue";

const props = defineProps<{
  visible: boolean;
  kind: "item" | "group" | "sub";
  title: string;
  draft: IapItem | IapGroup | IapSubscription;
  plan?: PlanItem;
}>();

const emit = defineEmits<{
  "update:visible": [boolean];
  confirm: [];
  cancel: [];
  pulled: [];
}>();

const { t } = useI18n();
const browse = useBrowse();
const workflow = useIapWorkflow();
const rail = useRightRail();

const PERIODS = [
  "ONE_WEEK",
  "ONE_MONTH",
  "TWO_MONTHS",
  "THREE_MONTHS",
  "SIX_MONTHS",
  "ONE_YEAR",
];

const addingLocale = ref("");
const pickerOpen = ref(false);
const translating = ref<Record<string, boolean>>({});
const autoTranslated = ref<Record<string, boolean>>({});
const locLoading = ref(false);
const catalog = useLocaleCatalog({ presence: false });
let committed = false;

const item = computed(() => (props.kind === "item" ? (props.draft as IapItem) : null));
const group = computed(() => (props.kind === "group" ? (props.draft as IapGroup) : null));
const sub = computed(() => (props.kind === "sub" ? (props.draft as IapSubscription) : null));

function locsOf(): LocMap {
  if (group.value) return group.value.localizations || (group.value.localizations = {});
  if (item.value) return item.value.localizations || (item.value.localizations = {});
  if (sub.value) return sub.value.localizations || (sub.value.localizations = {});
  return {};
}

const locRows = computed(() => Object.entries(locsOf()).map(([locale, row]) => ({ locale, ...row })));

function productId(): string {
  if (item.value) return item.value.productId;
  if (sub.value) return sub.value.productId;
  return "";
}

function shotPath(): string {
  if (item.value) return item.value.review?.screenshot || "";
  if (sub.value) return sub.value.review?.screenshot || "";
  return "";
}

function shotName(): string {
  const path = shotPath().trim();
  if (!path) return "";
  return path.split(/[/\\]/).pop() || path;
}

function sourceLocale(): { locale: string; name: string; description: string } | null {
  const locs = locsOf();
  const preferred = locs["en-US"];
  if (preferred && (preferred.name || preferred.description)) {
    return { locale: "en-US", name: preferred.name || "", description: preferred.description || "" };
  }
  for (const [locale, row] of Object.entries(locs)) {
    if (row.name || row.description) return { locale, name: row.name || "", description: row.description || "" };
  }
  return null;
}

onMounted(() => {
  void catalog.load();
});

function availableLocales(): string[] {
  const used = new Set(Object.keys(locsOf()));
  return catalog.rows.value.map((row) => row.code).filter((code) => !used.has(code));
}

const localeOptions = computed(() => {
  const used = new Set(Object.keys(locsOf()));
  return catalog.rows.value.map((row) => ({
    label: catalog.labelFor(row.code),
    value: row.code,
    disabled: used.has(row.code),
  }));
});

async function translateFields(fields: Array<{ locale: string; name: string; description?: string }>, mode: "translate" | "rewrite") {
  const src = sourceLocale();
  return httpJson<{ translations?: Array<{ locale: string; name: string; description?: string }>; error?: string }>(
    "/api/iap/translate",
    {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({
        source_locale: src?.locale || "en-US",
        mode,
        fields,
      }),
    },
  );
}

async function addLocale() {
  const locale = addingLocale.value;
  if (!locale) return;
  const locs = locsOf();
  if (locs[locale]) return;
  const includeDesc = props.kind !== "group";
  locs[locale] = includeDesc ? { name: "", description: "" } : { name: "" };
  addingLocale.value = "";
  if (!workflow.autoTranslate.value) return;
  const src = sourceLocale();
  if (!src?.name) return;
  translating.value = { ...translating.value, [locale]: true };
  try {
    const field: { locale: string; name: string; description?: string } = { locale, name: src.name };
    if (includeDesc) field.description = src.description;
    const data = await translateFields([field], "translate");
    const row = data.translations?.[0];
    if (row) {
      locs[locale] = includeDesc
        ? { name: row.name, description: row.description || "" }
        : { name: row.name };
      autoTranslated.value = { ...autoTranslated.value, [locale]: true };
    }
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) {
      MessagePlugin.warning(t("iap.translate_no_key"));
    } else {
      MessagePlugin.error(err instanceof ApiError ? apiErrorMessage(err) : String(err));
    }
  } finally {
    const next = { ...translating.value };
    delete next[locale];
    translating.value = next;
  }
}

async function fillMissing() {
  const missing = availableLocales();
  const src = sourceLocale();
  if (!src?.name || !missing.length) return;
  const includeDesc = props.kind !== "group";
  locLoading.value = true;
  try {
    const fields = missing.map((locale) => {
      const field: { locale: string; name: string; description?: string } = { locale, name: src.name };
      if (includeDesc) field.description = src.description;
      return field;
    });
    const data = await translateFields(fields, "translate");
    const locs = locsOf();
    for (const row of data.translations || []) {
      locs[row.locale] = includeDesc
        ? { name: row.name, description: row.description || "" }
        : { name: row.name };
      autoTranslated.value = { ...autoTranslated.value, [row.locale]: true };
    }
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) MessagePlugin.warning(t("iap.translate_no_key"));
    else MessagePlugin.error(err instanceof ApiError ? apiErrorMessage(err) : String(err));
  } finally {
    locLoading.value = false;
  }
}

async function rewrite(field: "name" | "description") {
  const src = sourceLocale();
  if (!src) return;
  const includeDesc = props.kind !== "group";
  if (field === "description" && !includeDesc) return;
  locLoading.value = true;
  try {
    const fields = locRows.value.map((row) => {
      const payload: { locale: string; name: string; description?: string } = { locale: row.locale, name: src.name };
      if (includeDesc) payload.description = src.description;
      return payload;
    });
    const data = await translateFields(fields, "rewrite");
    const locs = locsOf();
    for (const row of data.translations || []) {
      const prev = locs[row.locale] || { name: "" };
      if (field === "name") locs[row.locale] = { ...prev, name: row.name };
      else locs[row.locale] = { ...prev, description: row.description || "" };
    }
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) MessagePlugin.warning(t("iap.translate_no_key"));
    else MessagePlugin.error(err instanceof ApiError ? apiErrorMessage(err) : String(err));
  } finally {
    locLoading.value = false;
  }
}

function removeLocale(locale: string) {
  delete locsOf()[locale];
}

function setLocName(locale: string, value: string | number) {
  const row = locsOf()[locale];
  if (!row) return;
  row.name = String(value ?? "");
}

function setLocDesc(locale: string, value: string | number) {
  const row = locsOf()[locale];
  if (!row) return;
  row.description = String(value ?? "");
}

function setPriceField(field: "baseTerritory" | "baseAmount", value: string | number) {
  const text = String(value ?? "");
  if (item.value) item.value.price = { ...(item.value.price || {}), [field]: text };
  else if (sub.value) sub.value.price = { ...(sub.value.price || {}), [field]: text };
}

function setGroupLevel(value: number | string | undefined) {
  if (!sub.value) return;
  const n = typeof value === "number" ? value : Number(value);
  sub.value.groupLevel = Number.isFinite(n) ? n : null;
}

async function pickShot() {
  if (props.kind === "group") return;
  const path = await browse.pick({
    mode: "file",
    ext: ".png,.jpg,.jpeg",
    initialPath: shotPath(),
  });
  if (!path) return;
  if (item.value) item.value.review = { ...(item.value.review || {}), screenshot: path };
  else if (sub.value) sub.value.review = { ...(sub.value.review || {}), screenshot: path };
}

async function pullOne() {
  const pid = productId();
  if (!pid) return;
  try {
    const data = await httpJson<{ snapshot: IapSnapshot }>("/api/iap/pull", {
      method: "POST",
      body: JSON.stringify({
        iapFile: workflow.iapFile.value,
        productIds: [pid],
        expected_mtime: workflow.mtime.value,
        write: false,
      }),
    });
    workflow.applySnapshot(data.snapshot, { dirty: true, storeDraft: true });
    committed = true;
    emit("pulled");
    emit("update:visible", false);
    emit("update:visible", false);
  } catch (err) {
    MessagePlugin.error(err instanceof ApiError ? apiErrorMessage(err) : String(err));
  }
}

function openAgent() {
  const locales = Object.keys(locsOf()).join(", ") || "en-US";
  rail.openAgent({
    seedPrompt: t("iap.agent_seed_edit", { productId: productId() || "(new)", locales }),
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
    width="760px"
    placement="center"
    attach="body"
    :close-on-overlay-click="true"
    @update:visible="onVisible"
  >
    <div class="editor-body dialog-form">
      <div v-if="plan?.status === 'changed'" class="diff-box">
        <p>{{ t("iap.changed_hint") }}</p>
        <ul>
          <li v-for="field in plan.fields" :key="field.field">
            {{ field.field }}: {{ field.local }} → {{ field.asc }}
          </li>
        </ul>
        <t-button size="small" @click="pullOne">{{ t("iap.overwrite_store") }}</t-button>
      </div>

      <section v-if="group" class="mod">
        <h3 class="mod-title">{{ t("iap.section_basics") }}</h3>
        <label class="field">{{ t("iap.reference_name") }}
          <t-input v-model="group.referenceName" />
        </label>
      </section>
      <template v-else-if="item">
        <section class="mod">
          <h3 class="mod-title">{{ t("iap.section_basics") }}</h3>
          <label class="field">productId
            <t-input v-model="item.productId" />
          </label>
          <label class="field">{{ t("iap.reference_name") }}
            <t-input v-model="item.name" />
          </label>
          <label class="field">{{ t("iap.type") }}
            <t-select v-model="item.inAppPurchaseType" :options="[{label:'CONSUMABLE',value:'CONSUMABLE'},{label:'NON_CONSUMABLE',value:'NON_CONSUMABLE'},{label:'NON_RENEWING_SUBSCRIPTION',value:'NON_RENEWING_SUBSCRIPTION'}]" />
          </label>
        </section>
        <section class="mod">
          <h3 class="mod-title">{{ t("iap.section_price") }}</h3>
          <div class="field-row">
            <label class="field">{{ t("iap.base_territory") }}
              <t-input :value="item.price?.baseTerritory || 'USA'" @change="(v) => setPriceField('baseTerritory', v)" />
            </label>
            <label class="field">{{ t("iap.base_amount") }}
              <t-input :value="item.price?.baseAmount || ''" @change="(v) => setPriceField('baseAmount', v)" />
            </label>
          </div>
        </section>
        <section class="mod">
          <h3 class="mod-title">{{ t("iap.review_shot") }}</h3>
          <div class="field-row shot-field">
            <IapReviewThumb :path="shotPath()" size="field" />
            <span class="shot-name" :title="shotPath() || undefined">{{ shotName() || t("iap.status.missing-shot") }}</span>
            <t-button size="small" @click="pickShot">{{ t("filebrowser.browse") }}</t-button>
          </div>
        </section>
      </template>
      <template v-else-if="sub">
        <section class="mod">
          <h3 class="mod-title">{{ t("iap.section_basics") }}</h3>
          <label class="field">productId
            <t-input v-model="sub.productId" />
          </label>
          <label class="field">{{ t("iap.reference_name") }}
            <t-input v-model="sub.name" />
          </label>
          <label class="field">{{ t("iap.period") }}
            <t-select v-model="sub.subscriptionPeriod" :options="PERIODS.map((p) => ({ label: p, value: p }))" />
          </label>
          <label class="field">groupLevel
            <t-input-number :value="sub.groupLevel || undefined" :min="1" theme="column" @change="setGroupLevel" />
            <span class="muted">{{ t("iap.group_level_hint") }}</span>
          </label>
        </section>
        <section class="mod">
          <h3 class="mod-title">{{ t("iap.section_price") }}</h3>
          <div class="field-row">
            <label class="field">{{ t("iap.base_territory") }}
              <t-input :value="sub.price?.baseTerritory || 'USA'" @change="(v) => setPriceField('baseTerritory', v)" />
            </label>
            <label class="field">{{ t("iap.base_amount") }}
              <t-input :value="sub.price?.baseAmount || ''" @change="(v) => setPriceField('baseAmount', v)" />
            </label>
          </div>
        </section>
        <section class="mod">
          <h3 class="mod-title">{{ t("iap.review_shot") }}</h3>
          <div class="field-row shot-field">
            <IapReviewThumb :path="shotPath()" size="field" />
            <span class="shot-name" :title="shotPath() || undefined">{{ shotName() || t("iap.status.missing-shot") }}</span>
            <t-button size="small" @click="pickShot">{{ t("filebrowser.browse") }}</t-button>
          </div>
        </section>
      </template>

      <section class="mod">
        <header class="mod-head">
          <h3 class="mod-title">{{ t("iap.localizations") }}</h3>
          <t-checkbox v-model="workflow.autoTranslate.value" @change="workflow.persistMemory()">{{ t("iap.auto_translate") }}</t-checkbox>
        </header>
        <div class="mod-toolbar">
          <t-select
            class="locale-add"
            v-model="addingLocale"
            filterable
            :placeholder="t('iap.add_locale')"
            :options="localeOptions"
            :popup-props="{ attach: 'body' }"
          />
          <t-button size="small" variant="outline" :title="t('metadata.locales_title')" @click="pickerOpen = true">
            {{ t("metadata.locales_btn") }}
          </t-button>
          <t-button size="small" :disabled="!addingLocale" @click="addLocale">{{ t("iap.add_locale") }}</t-button>
          <t-button size="small" variant="outline" :loading="locLoading" @click="fillMissing">{{ t("iap.fill_locales") }}</t-button>
          <t-button size="small" variant="outline" :loading="locLoading" @click="rewrite('name')">{{ t("iap.rewrite_name") }}</t-button>
          <t-button v-if="kind !== 'group'" size="small" variant="outline" :loading="locLoading" @click="rewrite('description')">{{ t("iap.rewrite_desc") }}</t-button>
          <t-button size="small" variant="outline" @click="openAgent">{{ t("iap.agent_tweak") }}</t-button>
        </div>
        <div v-for="row in locRows" :key="row.locale" class="nested">
          <div class="loc-cap">
            <span class="loc-code">{{ catalog.labelFor(row.locale) }}</span>
            <span v-if="autoTranslated[row.locale]" class="muted">{{ t("iap.auto_translated") }}</span>
            <t-button size="small" variant="text" theme="danger" @click="removeLocale(row.locale)">{{ t("common.delete") }}</t-button>
          </div>
          <t-input
            :value="row.name"
            :placeholder="t('iap.display_name')"
            :status="row.name && (row.name.length < 2 || row.name.length > 30) ? 'warning' : undefined"
            :disabled="!!translating[row.locale]"
            @change="(v) => setLocName(row.locale, v)"
          />
          <t-input
            v-if="kind !== 'group'"
            :value="row.description || ''"
            :placeholder="t('iap.display_desc')"
            :status="(row.description || '').length > 45 ? 'warning' : undefined"
            :disabled="!!translating[row.locale]"
            @change="(v) => setLocDesc(row.locale, v)"
          />
        </div>
      </section>
    </div>
    <template #footer>
      <t-button variant="outline" @click="cancel">{{ t("common.cancel") }}</t-button>
      <t-button theme="primary" @click="confirm">{{ t("iap.dialog_ok") }}</t-button>
    </template>
  </t-dialog>
  <LocalePicker v-model:open="pickerOpen" />
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
.mod-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.mod-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  justify-content: space-between;
}
.mod-head :deep(.t-checkbox) {
  display: inline-flex;
  align-items: center;
  width: auto;
}
.mod-head :deep(.t-checkbox__label) {
  padding-left: 0;
  margin-left: 8px;
}
.mod-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.locale-add {
  min-width: 240px;
  flex: 1;
}
.nested {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-left: 8px;
  padding: 10px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.loc-cap {
  display: flex;
  align-items: center;
  gap: 8px;
}
.loc-code {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
}
.loc-cap .t-button { margin-left: auto; }
.field-row { display: flex; gap: 8px; align-items: center; }
.shot-field { align-items: center; }
.shot-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--text-muted);
}
.field { display: flex; flex-direction: column; gap: 6px; flex: 1; }
.muted { color: var(--text-muted); font-size: 12px; }
.diff-box {
  background: var(--raised);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
}
</style>
