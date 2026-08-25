<script setup lang="ts">
import { computed, onActivated, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, apiErrorMessage, httpForm, httpJson } from "@/api/http";
import LocaleSelectTabs from "@/components/LocaleSelectTabs.vue";
import PageLoading from "@/components/PageLoading.vue";
import TaskRunBar from "@/components/TaskRunBar.vue";
import { useAppLocales } from "@/composables/useAppLocales";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";
import { useTaskPagePhase } from "@/composables/useTaskPagePhase";
import {
  WHATS_NEW_FORM_KEY_PREFIX,
  formMemoryKey,
  parseWhatsNewStored,
  readFormMemory,
  whatsNewFormPayload,
  writeFormMemory,
} from "@/composables/useFormMemory";

const { t } = useI18n();
const { snapshot } = useProfile();
const rail = useRightRail();
const { channelOf } = useTaskLog();
const { check, checking, ensure, refresh } = useAppLocales("whats-new");
defineOptions({ name: "WhatsNewView" });

const { isForm, isRun, taskId, meta, enterRun, backToForm } = useTaskPagePhase("whats-new");
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const appProfile = computed(() => snapshot.value?.current_profile || "");
const alert = ref("");
const text = ref("");
const texts = ref<Record<string, string>>({});
const locales = ref<string[]>([]);
const activeLocale = ref("");
const previewLocale = ref("");
const dryRun = ref(false);
const verbose = ref(false);
const translateMode = ref(false);
const sourceLocale = ref("auto");
const translations = ref<Record<string, string>>({});
const translateTaskId = computed(() => meta.value.translateTaskId || "");
const translateLog = channelOf(translateTaskId);
const availableLocales = computed(() => check.value?.detail?.locales || []);
const previewLocales = computed(() => Object.keys(translations.value));
const sharedPlaceholder = computed(() => {
  const filled = locales.value.map((code) => (texts.value[code] || "").trim()).find(Boolean);
  return filled || t("whats_new.placeholder");
});

function syncSelectedLocales() {
  const available = availableLocales.value;
  if (available.length && !locales.value.length) {
    locales.value = [...available];
  }
  if (!activeLocale.value || !available.includes(activeLocale.value)) {
    activeLocale.value = available[0] || "";
  }
}

async function loadCheck() {
  await refresh();
}

function setLocaleText(code: string, value: string) {
  texts.value = { ...texts.value, [code]: value };
}

function directPayload(): Record<string, string> {
  const selected = locales.value;
  const filled = selected
    .map((code) => [code, (texts.value[code] || "").trim()] as const)
    .filter(([, value]) => value);
  const fallback = filled[0]?.[1] || text.value;
  const unique = new Set(filled.map(([, value]) => value));
  if (unique.size > 1) {
    const translationsByLocale: Record<string, string> = {};
    for (const code of selected) {
      translationsByLocale[code] = (texts.value[code] || "").trim() || fallback;
    }
    return { translations_json: JSON.stringify(translationsByLocale) };
  }
  return { text: fallback, locales: selected.join(",") };
}

async function runDirect() {
  alert.value = "";
  try {
    const body = new URLSearchParams({
      dry_run: dryRun.value ? "true" : "",
      verbose: verbose.value ? "true" : "",
      ...directPayload(),
    });
    const { task_id } = await httpForm<{ task_id: string }>("/api/whats-new/run", body);
    enterRun(task_id, { translateTaskId: "" });
    rail.openLogs(task_id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  }
}

async function previewTranslate() {
  alert.value = "";
  try {
    const { task_id } = await httpJson<{ task_id: string }>("/api/whats-new/translate", {
      method: "POST",
      body: JSON.stringify({ text: text.value, source_locale: sourceLocale.value, verbose: verbose.value }),
    });
    enterRun(task_id, { translateTaskId: task_id });
    rail.openLogs(task_id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  }
}

async function runTranslateAndUpload() {
  alert.value = "";
  translations.value = {};
  try {
    const { task_id } = await httpJson<{ task_id: string }>("/api/whats-new/run", {
      method: "POST",
      body: JSON.stringify({
        text: text.value,
        source_locale: sourceLocale.value,
        translate: true,
        dry_run: dryRun.value,
        verbose: verbose.value,
      }),
    });
    enterRun(task_id, { translateTaskId: "" });
    rail.openLogs(task_id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  }
}

async function uploadTranslations() {
  const body = new URLSearchParams({
    translations_json: JSON.stringify(translations.value),
    dry_run: dryRun.value ? "true" : "",
    verbose: verbose.value ? "true" : "",
  });
  const { task_id } = await httpForm<{ task_id: string }>("/api/whats-new/run", body);
  enterRun(task_id, { translateTaskId: "" });
  rail.openLogs(task_id);
}

async function pullTranslateResult() {
  const id = translateTaskId.value;
  if (!id || Object.keys(translations.value).length) return;
  try {
    const state = await httpJson<{ result?: { translations?: Record<string, string> } }>(
      `/api/task/${encodeURIComponent(id)}/status`,
    );
    translations.value = state.result?.translations || {};
  } catch {
    /* ignore */
  }
}

watch(
  () => translateLog.status.value,
  async (st) => {
    if (translateTaskId.value && st === "done") await pullTranslateResult();
  },
);

watch(previewLocales, (keys) => {
  if (!keys.includes(previewLocale.value)) previewLocale.value = keys[0] || "";
});

function restoreWhatsNewMemory() {
  const saved = parseWhatsNewStored(readFormMemory(formMemoryKey(WHATS_NEW_FORM_KEY_PREFIX, appProfile.value)));
  if (!saved) return;
  if (saved.text) text.value = saved.text;
  if (saved.texts && Object.keys(saved.texts).length) texts.value = { ...saved.texts };
  dryRun.value = !!saved.dry_run;
  verbose.value = !!saved.verbose;
  translateMode.value = !!saved.translate_mode;
  if (saved.source_locale) sourceLocale.value = saved.source_locale;
}

function saveWhatsNewMemory() {
  if (!appProfile.value) return;
  writeFormMemory(
    formMemoryKey(WHATS_NEW_FORM_KEY_PREFIX, appProfile.value),
    whatsNewFormPayload({
      text: text.value,
      texts: texts.value,
      dry_run: dryRun.value,
      verbose: verbose.value,
      translate_mode: translateMode.value,
      source_locale: sourceLocale.value,
    }),
  );
}

restoreWhatsNewMemory();
watch([text, texts, dryRun, verbose, translateMode, sourceLocale], saveWhatsNewMemory);

watch(check, syncSelectedLocales, { immediate: true });

onMounted(() => {
  ensure();
  void pullTranslateResult();
});
onActivated(() => {
  ensure();
});
</script>

<template>
  <div class="page-stack">
    <h1>{{ t("whats_new.title") }}</h1>
    <t-alert v-if="empty" theme="warning" :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </t-alert>
    <t-alert v-if="alert" theme="error" :title="alert" />
    <div v-if="isForm" class="card">
      <div class="field-row check-row">
        <p v-if="check">{{ check.message }}</p>
        <p v-if="check?.detail?.version || check?.detail?.locales?.length" class="muted">
          <span v-if="check.detail.version">{{ check.detail.version }}</span>
          <span v-if="check.detail.locales?.length"> · {{ check.detail.locales.join(", ") }}</span>
        </p>
        <PageLoading v-else-if="checking" size="inline" :text="t('whats_new.checking')" />
        <t-button
          size="small"
          :loading="checking && !!check"
          :disabled="checking && !check"
          @click="loadCheck"
        >{{ t("whats_new.recheck") }}</t-button>
      </div>
    </div>
    <div v-if="isForm" class="card">
      <div class="mode-block">
        <t-checkbox v-model="translateMode">{{ t("whats_new.translate_mode") }}</t-checkbox>
        <label v-if="translateMode" class="field">
          <span>{{ t("whats_new.source_lang") }}</span>
          <t-select v-model="sourceLocale">
            <t-option value="auto" :label="t('whats_new.auto_detect')" />
            <t-option v-for="code in check?.detail?.locales || []" :key="code" :value="code" :label="code" />
          </t-select>
        </label>
      </div>
      <label v-if="translateMode" class="field">
        <span>{{ t("whats_new.text") }}</span>
        <t-textarea v-model="text" :autosize="{ minRows: 8, maxRows: 14 }" :placeholder="t('whats_new.placeholder')" />
      </label>
      <LocaleSelectTabs
        v-if="!translateMode"
        v-model="activeLocale"
        v-model:selected="locales"
        :locales="check?.detail?.locales || []"
      >
        <template #default="{ locale }">
          <label class="field">
            <span>{{ t("whats_new.text") }}</span>
            <t-textarea
              :value="texts[locale] || ''"
              :autosize="{ minRows: 8, maxRows: 14 }"
              :placeholder="sharedPlaceholder"
              @change="(value) => setLocaleText(locale, String(value ?? ''))"
            />
          </label>
        </template>
      </LocaleSelectTabs>
      <t-checkbox v-model="dryRun">{{ t("common.dry_run") }}</t-checkbox>
      <t-checkbox v-model="verbose">{{ t("build.verbose") }}</t-checkbox>
      <div class="field-row">
        <t-button v-if="translateMode" :disabled="empty" @click="previewTranslate">{{ t("whats_new.preview_translate") }}</t-button>
        <t-button v-if="translateMode" theme="primary" :disabled="empty" @click="runTranslateAndUpload">{{ t("whats_new.translate_upload") }}</t-button>
        <t-button v-else theme="primary" :disabled="empty" @click="runDirect">{{ t("whats_new.upload_direct") }}</t-button>
      </div>
    </div>
    <div v-if="isForm && translateMode && Object.keys(translations).length" class="card">
      <h2>{{ t("whats_new.preview_title") }}</h2>
      <LocaleSelectTabs
        v-model="previewLocale"
        :locales="previewLocales"
        :selected="previewLocales"
        :selectable="false"
        :show-select-all="false"
        :show-toolbar="false"
      >
        <template #default="{ locale }">
          <label class="field">
            <span>{{ locale }}</span>
            <t-textarea v-model="translations[locale]" :autosize="{ minRows: 4, maxRows: 10 }" />
          </label>
        </template>
      </LocaleSelectTabs>
      <t-button theme="primary" :disabled="empty" @click="uploadTranslations">{{ t("whats_new.confirm_upload") }}</t-button>
    </div>
    <TaskRunBar v-if="isRun && taskId" :task-id="taskId" @back="backToForm">
      <template #after>
        <div v-if="Object.keys(translations).length" class="preview">
          <h2>{{ t("whats_new.preview_title") }}</h2>
          <LocaleSelectTabs
            v-model="previewLocale"
            :locales="previewLocales"
            :selected="previewLocales"
            :selectable="false"
            :show-select-all="false"
            :show-toolbar="false"
          >
            <template #default="{ locale }">
              <label class="field">
                <span>{{ locale }}</span>
                <t-textarea v-model="translations[locale]" :autosize="{ minRows: 4, maxRows: 10 }" />
              </label>
            </template>
          </LocaleSelectTabs>
          <t-button theme="primary" :disabled="empty" @click="uploadTranslations">{{ t("whats_new.confirm_upload") }}</t-button>
        </div>
      </template>
    </TaskRunBar>
  </div>
</template>

<style scoped>
h1, h2 { margin: 0 0 8px; }
.muted { color: var(--text-muted); font-size: 12px; }
.card { display: flex; flex-direction: column; gap: 10px; }
.mode-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--raised);
}
.preview { display: flex; flex-direction: column; gap: 10px; padding-top: 4px; }
</style>
