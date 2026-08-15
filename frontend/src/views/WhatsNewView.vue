<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, apiErrorMessage, httpForm, httpJson } from "@/api/http";
import TaskRunBar from "@/components/TaskRunBar.vue";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";
import { useTaskPagePhase } from "@/composables/useTaskPagePhase";

type Check = { ok: boolean; level: string; message: string; detail?: { version?: string; locales?: string[] } };

const { t } = useI18n();
const { snapshot } = useProfile();
const rail = useRightRail();
const { status, logTaskId } = useTaskLog();
const { isForm, isRun, enterRun, backToForm } = useTaskPagePhase();
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const alert = ref("");
const check = ref<Check | null>(null);
const text = ref("");
const locales = ref<string[]>([]);
const dryRun = ref(false);
const verbose = ref(false);
const translateMode = ref(false);
const sourceLocale = ref("auto");
const taskId = ref("");
const translateTaskId = ref("");
const translations = ref<Record<string, string>>({});

async function loadCheck() {
  check.value = await httpJson<Check>("/api/whats-new/check");
  if (check.value.detail?.locales?.length && !locales.value.length) {
    locales.value = [...check.value.detail.locales];
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
    taskId.value = task_id;
    enterRun();
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
    translateTaskId.value = task_id;
    taskId.value = task_id;
    enterRun();
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
  taskId.value = task_id;
  enterRun();
  rail.openLogs(task_id);
}

function toggleLocale(code: string, on: boolean) {
  locales.value = on ? Array.from(new Set([...locales.value, code])) : locales.value.filter((item) => item !== code);
}

watch([status, logTaskId], async () => {
  if (translateTaskId.value && logTaskId.value === translateTaskId.value && status.value === "done") {
    const state = await httpJson<{ result?: { translations?: Record<string, string> } }>(
      `/api/task/${encodeURIComponent(translateTaskId.value)}/status`,
    );
    translations.value = state.result?.translations || {};
  }
});

onMounted(() => { void loadCheck(); });
</script>

<template>
  <div class="page-stack">
    <h1>{{ t("whats_new.title") }}</h1>
    <el-alert v-if="empty" type="warning" show-icon :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </el-alert>
    <el-alert v-if="alert" type="error" show-icon :title="alert" />
    <div v-if="isForm" class="card">
      <p v-if="!check">{{ t("whats_new.checking") }}</p>
      <p v-else>{{ check.message }}</p>
      <el-button size="small" @click="loadCheck">{{ t("whats_new.recheck") }}</el-button>
      <label class="check"><input v-model="translateMode" type="checkbox" /> {{ t("whats_new.translate_mode") }}</label>
      <label class="field">
        <span>{{ t("whats_new.source_lang") }}</span>
        <input v-model="sourceLocale" class="field-input" :placeholder="t('whats_new.auto_detect')" />
      </label>
      <label class="field">
        <span>{{ t("whats_new.text") }}</span>
        <textarea v-model="text" rows="8" class="field-input" :placeholder="t('whats_new.placeholder')" />
      </label>
      <div>
        <span class="lbl">{{ t("urls.locales") }}</span>
        <label v-for="code in check?.detail?.locales || []" :key="code" class="check">
          <input type="checkbox" :checked="locales.includes(code)" @change="toggleLocale(code, ($event.target as HTMLInputElement).checked)" />
          {{ code }}
        </label>
      </div>
      <label class="check"><input v-model="dryRun" type="checkbox" /> {{ t("common.dry_run") }}</label>
      <label class="check"><input v-model="verbose" type="checkbox" /> {{ t("build.verbose") }}</label>
      <div class="field-row">
        <el-button v-if="translateMode" type="primary" :disabled="empty" @click="previewTranslate">{{ t("whats_new.preview_translate") }}</el-button>
        <el-button v-else type="primary" :disabled="empty" @click="runDirect">{{ t("whats_new.upload_direct") }}</el-button>
      </div>
    </div>
    <div v-if="isForm && Object.keys(translations).length" class="card">
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
.preview { display: flex; flex-direction: column; gap: 10px; padding-top: 4px; }
</style>
