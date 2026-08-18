<script setup lang="ts">
import { computed, onActivated, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, apiErrorMessage, httpForm } from "@/api/http";
import LocaleSelectTabs from "@/components/LocaleSelectTabs.vue";
import PageLoading from "@/components/PageLoading.vue";
import TaskRunBar from "@/components/TaskRunBar.vue";
import { useAppLocales } from "@/composables/useAppLocales";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskPagePhase } from "@/composables/useTaskPagePhase";

const { t } = useI18n();
const { snapshot } = useProfile();
const rail = useRightRail();
const { check, checking, ensure, refresh } = useAppLocales("urls");
defineOptions({ name: "UrlsView" });

const { isForm, isRun, taskId, enterRun, backToForm } = useTaskPagePhase("urls");
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const alert = ref("");
const field = ref("supportUrl");
const url = ref("");
const locales = ref<string[]>([]);
const activeLocale = ref("");
const dryRun = ref(false);
const verbose = ref(false);

function syncSelectedLocales() {
  const available = check.value?.detail?.locales || [];
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

watch(check, syncSelectedLocales, { immediate: true });

onMounted(() => {
  ensure();
});
onActivated(() => {
  ensure();
});
</script>

<template>
  <div class="page-stack">
    <h1>{{ t("urls.title") }}</h1>
    <p class="muted">{{ t("urls.subtitle") }}</p>
    <t-alert v-if="empty" theme="warning" :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </t-alert>
    <t-alert v-if="alert" theme="error" :title="alert" />
    <div v-if="isForm" class="card">
      <div class="field-row">
        <PageLoading v-if="checking && !check" size="inline" />
        <p v-else-if="check">{{ check.message }}</p>
        <t-button
          size="small"
          :loading="checking && !!check"
          :disabled="checking && !check"
          @click="loadCheck"
        >{{ t("common.check_env") }}</t-button>
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
      <LocaleSelectTabs
        v-model="activeLocale"
        v-model:selected="locales"
        :locales="check?.detail?.locales || []"
        :hint="t('urls.locales_hint')"
      >
        <template #default="{ locale }">
          <p class="muted">{{ t("urls.locale_apply_hint", { locale }) }}</p>
        </template>
      </LocaleSelectTabs>
      <label class="check"><input v-model="dryRun" type="checkbox" /> {{ t("common.dry_run") }}</label>
      <label class="check"><input v-model="verbose" type="checkbox" /> {{ t("build.verbose") }}</label>
      <t-button theme="primary" :disabled="empty" @click="run">{{ t("urls.submit") }}</t-button>
    </div>
    <TaskRunBar v-if="isRun && taskId" :task-id="taskId" @back="backToForm" />
  </div>
</template>

<style scoped>
h1 { margin: 0; }
.muted { color: var(--text-muted); font-size: 13px; }
.card { display: flex; flex-direction: column; gap: 10px; }
.check { display: flex; gap: 8px; align-items: center; }
</style>
