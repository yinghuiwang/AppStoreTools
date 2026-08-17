<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, apiErrorMessage, httpForm, httpJson } from "@/api/http";
import PageLoading from "@/components/PageLoading.vue";
import TaskRunBar from "@/components/TaskRunBar.vue";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskPagePhase } from "@/composables/useTaskPagePhase";

type Check = { ok: boolean; message: string; detail?: { locales?: string[] } };

const { t } = useI18n();
const { snapshot } = useProfile();
const rail = useRightRail();
defineOptions({ name: "UrlsView" });

const { isForm, isRun, taskId, enterRun, backToForm } = useTaskPagePhase("urls");
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const alert = ref("");
const check = ref<Check | null>(null);
const checking = ref(false);
const field = ref("supportUrl");
const url = ref("");
const locales = ref<string[]>([]);
const dryRun = ref(false);
const verbose = ref(false);

async function loadCheck() {
  checking.value = true;
  try {
    check.value = await httpJson<Check>("/api/urls/check");
    if (check.value.detail?.locales?.length && !locales.value.length) {
      locales.value = [...check.value.detail.locales];
    }
  } finally {
    checking.value = false;
  }
}

function toggle(code: string, on: boolean) {
  locales.value = on ? Array.from(new Set([...locales.value, code])) : locales.value.filter((item) => item !== code);
}

async function run() {
  alert.value = "";
  try {
    const body = new URLSearchParams({
      field: field.value,
      url: url.value,
      locales: locales.value.join(","),
      dry_run: dryRun.value ? "true" : "",
      verbose: verbose.value ? "true" : "",
    });
    const { task_id } = await httpForm<{ task_id: string }>("/api/urls/set", body);
    enterRun(task_id);
    rail.openLogs(task_id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  }
}

onMounted(() => { void loadCheck(); });
</script>

<template>
  <div class="page-stack">
    <h1>{{ t("urls.title") }}</h1>
    <p class="muted">{{ t("urls.subtitle") }}</p>
    <el-alert v-if="empty" type="warning" show-icon :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </el-alert>
    <el-alert v-if="alert" type="error" show-icon :title="alert" />
    <div v-if="isForm" class="card">
      <div class="field-row">
        <PageLoading v-if="checking && !check" size="inline" />
        <p v-else-if="check">{{ check.message }}</p>
        <el-button
          size="small"
          :loading="checking && !!check"
          :disabled="checking && !check"
          @click="loadCheck"
        >{{ t("common.check_env") }}</el-button>
      </div>
      <label class="field">
        <span>{{ t("urls.choose_type") }}</span>
        <select v-model="field" class="field-input">
          <option value="supportUrl">{{ t("urls.support") }}</option>
          <option value="marketingUrl">{{ t("urls.marketing") }}</option>
          <option value="privacyPolicyUrl">{{ t("urls.privacy") }}</option>
        </select>
      </label>
      <label class="field"><span>{{ t("urls.address") }}</span><input v-model="url" class="field-input" /></label>
      <div>
        <span class="lbl">{{ t("urls.locales") }}</span>
        <p class="muted">{{ t("urls.locales_hint") }}</p>
        <label v-for="code in check?.detail?.locales || []" :key="code" class="check">
          <input type="checkbox" :checked="locales.includes(code)" @change="toggle(code, ($event.target as HTMLInputElement).checked)" />
          {{ code }}
        </label>
      </div>
      <label class="check"><input v-model="dryRun" type="checkbox" /> {{ t("common.dry_run") }}</label>
      <label class="check"><input v-model="verbose" type="checkbox" /> {{ t("build.verbose") }}</label>
      <el-button type="primary" :disabled="empty" @click="run">{{ t("urls.submit") }}</el-button>
    </div>
    <TaskRunBar v-if="isRun && taskId" :task-id="taskId" @back="backToForm" />
  </div>
</template>

<style scoped>
h1 { margin: 0; }
.muted { color: var(--text-muted); font-size: 13px; }
.card { display: flex; flex-direction: column; gap: 10px; }
.check { display: flex; gap: 8px; align-items: center; }
.lbl { display: block; font-size: 12px; color: var(--text-muted); }
</style>
