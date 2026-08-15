<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { ApiError, apiErrorMessage, httpForm, httpJson } from "@/api/http";
import TaskRunBar from "@/components/TaskRunBar.vue";
import { useBrowse } from "@/composables/useBrowse";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";

type LocaleRow = { locale: string; fields: Record<string, string>; screenshots: Record<string, { file_name: string }[]> };

const FIELDS = ["name", "subtitle", "description", "keywords", "supportUrl", "marketingUrl", "privacyPolicyUrl"];
const { t } = useI18n();
const route = useRoute();
const browse = useBrowse();
const { snapshot } = useProfile();
const rail = useRightRail();
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const csvPath = ref(snapshot.value?.paths.csv || "data/appstore_info.csv");
const shotsDir = ref(snapshot.value?.paths.screenshots || "data/screenshots");
const includeMetadata = ref(true);
const includeScreenshots = ref(true);
const dryRun = ref(false);
const verbose = ref(false);
const taskId = ref("");
const checkMsg = ref("");
const alert = ref("");
const locales = ref<LocaleRow[]>([]);
const selectedLocales = ref<string[]>([]);
const fieldsByLocale = ref<Record<string, string[]>>({});
const scopes = ref<{ locale: string; display_type: string }[]>([]);
const omitFilters = ref(false);

async function loadLocal() {
  try {
    const qs = new URLSearchParams({ csv_path: csvPath.value, screenshots_dir: shotsDir.value });
    const data = await httpJson<{ snapshot: { locales: LocaleRow[] } }>(`/api/listing/local?${qs}`);
    locales.value = data.snapshot?.locales || [];
  } catch {
    locales.value = [];
  }
}

async function checkEnv() {
  alert.value = "";
  try {
    const data = await httpJson<{ ok?: boolean; message?: string }>("/api/metadata/check", { method: "POST" });
    checkMsg.value = data.message || "";
    if (data.ok === false && data.message) alert.value = data.message;
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  }
}

function toggleLocale(code: string, on: boolean) {
  selectedLocales.value = on
    ? Array.from(new Set([...selectedLocales.value, code]))
    : selectedLocales.value.filter((item) => item !== code);
}

function toggleField(locale: string, field: string, on: boolean) {
  const cur = fieldsByLocale.value[locale] || [];
  fieldsByLocale.value = {
    ...fieldsByLocale.value,
    [locale]: on ? Array.from(new Set([...cur, field])) : cur.filter((item) => item !== field),
  };
}

function toggleScope(locale: string, displayType: string, on: boolean) {
  const next = scopes.value.filter((s) => !(s.locale === locale && s.display_type === displayType));
  scopes.value = on ? [...next, { locale, display_type: displayType }] : next;
}

async function run() {
  alert.value = "";
  try {
    const body = new URLSearchParams();
    body.set("csv_path", csvPath.value);
    body.set("screenshots_dir", shotsDir.value);
    body.set("include_metadata", includeMetadata.value ? "true" : "");
    body.set("include_screenshots", includeScreenshots.value ? "true" : "");
    body.set("dry_run", dryRun.value ? "true" : "");
    body.set("verbose", verbose.value ? "true" : "");
    if (!omitFilters.value) {
      body.set("locales_json", JSON.stringify(selectedLocales.value));
      body.set("fields_by_locale_json", JSON.stringify(fieldsByLocale.value));
      body.set("screenshot_scopes_json", JSON.stringify(scopes.value));
    }
    const { task_id } = await httpForm<{ task_id: string }>("/api/metadata/run", body);
    taskId.value = task_id;
    rail.openLogs(task_id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  }
}

onMounted(() => {
  const action = String(route.query.action || "");
  if (action === "check") {
    void checkEnv();
  } else if (action === "all") {
    includeMetadata.value = true;
    includeScreenshots.value = true;
    omitFilters.value = true;
  } else if (action === "metadata") {
    includeMetadata.value = true;
    includeScreenshots.value = false;
  } else if (action === "screenshots") {
    includeMetadata.value = false;
    includeScreenshots.value = true;
  }
  void loadLocal();
});
</script>

<template>
  <div class="page-stack">
    <el-alert v-if="empty" type="warning" show-icon :title="t('index.no_app')">
      <router-link to="/system/profiles">{{ t("nav.system") }}</router-link>
    </el-alert>
    <el-alert v-if="alert" type="error" show-icon :title="alert" />
    <div class="card">
      <label class="field">
        <span>{{ t("metadata.csv_path") }}</span>
        <div class="field-row">
          <input v-model="csvPath" class="field-input" />
          <el-button @click="browse.pick({ mode: 'file', ext: '.csv', initialPath: csvPath }).then((p) => { if (p) csvPath = p; })">{{ t("filebrowser.browse") }}</el-button>
        </div>
      </label>
      <label class="field">
        <span>{{ t("metadata.shots_dir") }}</span>
        <div class="field-row">
          <input v-model="shotsDir" class="field-input" />
          <el-button @click="browse.pick({ mode: 'dir', initialPath: shotsDir }).then((p) => { if (p) shotsDir = p; })">{{ t("filebrowser.browse") }}</el-button>
        </div>
      </label>
      <div>
        <span class="lbl">{{ t("metadata.scope") }}</span>
        <label class="check"><input v-model="includeMetadata" type="checkbox" /> {{ t("metadata.scope_metadata") }}</label>
        <label class="check"><input v-model="includeScreenshots" type="checkbox" /> {{ t("metadata.scope_screenshots") }}</label>
      </div>
      <div v-for="row in locales" :key="row.locale" class="locale">
        <label class="check">
          <input type="checkbox" :checked="selectedLocales.includes(row.locale)" @change="toggleLocale(row.locale, ($event.target as HTMLInputElement).checked)" />
          {{ row.locale }}
        </label>
        <div class="fields">
          <label v-for="field in FIELDS" :key="field" class="check">
            <input type="checkbox" :checked="(fieldsByLocale[row.locale] || []).includes(field)" @change="toggleField(row.locale, field, ($event.target as HTMLInputElement).checked)" />
            {{ t(`metadata.field_${field}`) }}
          </label>
        </div>
        <label v-for="(_, dtype) in row.screenshots" :key="String(dtype)" class="check">
          <input type="checkbox" :checked="scopes.some((s) => s.locale === row.locale && s.display_type === dtype)" @change="toggleScope(row.locale, String(dtype), ($event.target as HTMLInputElement).checked)" />
          {{ dtype }}
        </label>
      </div>
      <label class="check"><input v-model="dryRun" type="checkbox" /> {{ t("common.dry_run") }}</label>
      <label class="check"><input v-model="verbose" type="checkbox" /> {{ t("build.verbose") }}</label>
      <div class="field-row">
        <el-button :disabled="empty" @click="checkEnv">{{ t("common.check_env") }}</el-button>
        <el-button type="primary" :disabled="empty" @click="run">{{ t("common.submit") }}</el-button>
      </div>
      <p v-if="checkMsg">{{ checkMsg }}</p>
      <TaskRunBar :task-id="taskId" />
    </div>
  </div>
</template>

<style scoped>
.card { display: flex; flex-direction: column; gap: 10px; }
.check { display: flex; gap: 8px; align-items: center; }
.lbl { display: block; font-size: 12px; color: var(--text-muted); }
.locale { border-top: 1px solid var(--border); padding-top: 8px; }
.fields { display: flex; flex-wrap: wrap; gap: 8px 14px; margin: 6px 0 6px 22px; }
</style>
