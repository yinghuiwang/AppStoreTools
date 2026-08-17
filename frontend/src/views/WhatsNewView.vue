<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, apiErrorMessage, httpForm, httpJson } from "@/api/http";
import PageLoading from "@/components/PageLoading.vue";
import TaskRunBar from "@/components/TaskRunBar.vue";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";
import { useTaskPagePhase } from "@/composables/useTaskPagePhase";

type Check = { ok: boolean; level: string; message: string; detail?: { version?: string; locales?: string[] } };

const { t } = useI18n();
const { snapshot } = useProfile();
const rail = useRightRail();
const { channelOf } = useTaskLog();
defineOptions({ name: "WhatsNewView" });

const { isForm, isRun, taskId, meta, enterRun, backToForm } = useTaskPagePhase("whats-new");
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const alert = ref("");
const check = ref<Check | null>(null);
const checking = ref(false);
const text = ref("");
const locales = ref<string[]>([]);
const dryRun = ref(false);
const verbose = ref(false);
const translateMode = ref(false);
const sourceLocale = ref("auto");
const translations = ref<Record<string, string>>({});
const translateTaskId = computed(() => meta.value.translateTaskId || "");
const translateLog = channelOf(translateTaskId);

async function loadCheck() {
  checking.value = true;
  try {
    check.value = await httpJson<Check>("/api/whats-new/check");
    if (check.value.detail?.locales?.length && !locales.value.length) {
      locales.value = [...check.value.detail.locales];
    }
  } finally {
    checking.value = false;
  }
}

async function runDirect() {
  alert.value = "";
  try {
    const body = new URLSearchParams({
      text: text.value,
      locales: locales.value.join(","),
      dry_run: dryRun.value ? "true" : "",
      verbose: verbose.value ? "true" : "",
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

function toggleLocale(code: string, on: boolean) {
  locales.value = on ? Array.from(new Set([...locales.value, code])) : locales.value.filter((item) => item !== code);
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

onMounted(() => {
  if (!check.value) void loadCheck();
  void pullTranslateResult();
});
</script>

<template>
  <div class="page-stack">
    <h1>{{ t("whats_new.title") }}</h1>
    <el-alert v-if="empty" type="warning" show-icon :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </el-alert>
    <el-alert v-if="alert" type="error" show-icon :title="alert" />
    <div v-if="isForm" class="card">
      <div class="field-row check-row">
        <p v-if="check">{{ check.message }}</p>
        <PageLoading v-else-if="checking" size="inline" :text="t('whats_new.checking')" />
        <el-button
          size="small"
          :loading="checking && !!check"
          :disabled="checking && !check"
          @click="loadCheck"
        >{{ t("whats_new.recheck") }}</el-button>
      </div>
    </div>
    <div v-if="isForm" class="card">
      <div class="mode-block">
        <label class="check"><input v-model="translateMode" type="checkbox" /> {{ t("whats_new.translate_mode") }}</label>
        <label v-if="translateMode" class="field">
          <span>{{ t("whats_new.source_lang") }}</span>
          <select v-model="sourceLocale" class="field-input">
            <option value="auto">{{ t("whats_new.auto_detect") }}</option>
            <option v-for="code in check?.detail?.locales || []" :key="code" :value="code">{{ code }}</option>
          </select>
        </label>
      </div>
      <label class="field">
        <span>{{ t("whats_new.text") }}</span>
        <textarea v-model="text" rows="8" class="field-input" :placeholder="t('whats_new.placeholder')" />
      </label>
      <div v-if="!translateMode">
        <span class="lbl">{{ t("urls.locales") }}</span>
        <label v-for="code in check?.detail?.locales || []" :key="code" class="check">
          <input type="checkbox" :checked="locales.includes(code)" @change="toggleLocale(code, ($event.target as HTMLInputElement).checked)" />
          {{ code }}
        </label>
      </div>
      <label class="check"><input v-model="dryRun" type="checkbox" /> {{ t("common.dry_run") }}</label>
      <label class="check"><input v-model="verbose" type="checkbox" /> {{ t("build.verbose") }}</label>
      <div class="field-row">
        <el-button v-if="translateMode" :disabled="empty" @click="previewTranslate">{{ t("whats_new.preview_translate") }}</el-button>
        <el-button v-if="translateMode" type="primary" :disabled="empty" @click="runTranslateAndUpload">{{ t("whats_new.translate_upload") }}</el-button>
        <el-button v-else type="primary" :disabled="empty" @click="runDirect">{{ t("whats_new.upload_direct") }}</el-button>
      </div>
    </div>
    <div v-if="isForm && translateMode && Object.keys(translations).length" class="card">
      <h2>{{ t("whats_new.preview_title") }}</h2>
      <label v-for="(value, locale) in translations" :key="locale" class="field">
        <span>{{ locale }}</span>
        <textarea v-model="translations[locale]" rows="4" class="field-input" />
      </label>
      <el-button type="primary" :disabled="empty" @click="uploadTranslations">{{ t("whats_new.confirm_upload") }}</el-button>
    </div>
    <TaskRunBar v-if="isRun && taskId" :task-id="taskId" @back="backToForm">
      <template #after>
        <div v-if="Object.keys(translations).length" class="preview">
          <h2>{{ t("whats_new.preview_title") }}</h2>
          <label v-for="(value, locale) in translations" :key="locale" class="field">
            <span>{{ locale }}</span>
            <textarea v-model="translations[locale]" rows="4" class="field-input" />
          </label>
          <el-button type="primary" :disabled="empty" @click="uploadTranslations">{{ t("whats_new.confirm_upload") }}</el-button>
        </div>
      </template>
    </TaskRunBar>
  </div>
</template>

<style scoped>
h1, h2 { margin: 0 0 8px; }
.card { display: flex; flex-direction: column; gap: 10px; }
.check { display: flex; gap: 8px; align-items: center; }
.lbl { display: block; font-size: 12px; color: var(--text-muted); margin-bottom: 6px; }
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
