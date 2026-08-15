<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, apiErrorMessage, httpForm, httpJson } from "@/api/http";
import TaskRunBar from "@/components/TaskRunBar.vue";
import { useBrowse } from "@/composables/useBrowse";
import { useImageViewer } from "@/composables/useImageViewer";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskPagePhase } from "@/composables/useTaskPagePhase";

type Target = {
  kind: string;
  id: string;
  productId: string;
  name: string;
  groupName: string;
  defaultPath: string;
  pathStatus: string;
};

const { t } = useI18n();
const browse = useBrowse();
const viewer = useImageViewer();
const { snapshot } = useProfile();
const rail = useRightRail();
const { isForm, isRun, enterRun, backToForm } = useTaskPagePhase();
const empty = computed(() => (snapshot.value?.current_profile || "") === "");
const alert = ref("");
const checkMsg = ref("");
const taskId = ref("");
const iapFile = ref(snapshot.value?.paths.iap || "data/iap_packages.json");
const dryRun = ref(false);
const updateExisting = ref(false);
const verbose = ref(false);
const targets = ref<Target[]>([]);
const paths = ref<Record<string, string>>({});
const reviewDry = ref(false);
const reviewVerbose = ref(false);

async function check() {
  alert.value = "";
  try {
    const data = await httpForm<{ ok: boolean; message: string }>("/api/iap/check", new URLSearchParams());
    checkMsg.value = data.message;
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  }
}

async function run() {
  alert.value = "";
  try {
    const body = new URLSearchParams({
      iap_file: iapFile.value,
      dry_run: dryRun.value ? "true" : "",
      update_existing: updateExisting.value ? "true" : "",
      verbose: verbose.value ? "true" : "",
    });
    const { task_id } = await httpForm<{ task_id: string }>("/api/iap/run", body);
    taskId.value = task_id;
    enterRun();
    rail.openLogs(task_id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) alert.value = apiErrorMessage(err);
    else throw err;
  }
}

async function scan() {
  const data = await httpJson<{ targets: Target[]; count: number }>("/api/iap/review-screenshots/scan", {
    method: "POST",
    body: JSON.stringify({ iapFile: iapFile.value }),
  });
  targets.value = data.targets || [];
  const next: Record<string, string> = {};
  for (const item of targets.value) next[item.id] = item.defaultPath || "";
  paths.value = next;
}

function previewPath(path: string) {
  const root = path.replace(/[/\\][^/\\]+$/, "") || ".";
  viewer.show([{
    src: `/api/listing/thumb?path=${encodeURIComponent(path)}&root=${encodeURIComponent(root)}`,
    title: path,
  }]);
}

async function pickPath(id: string) {
  const path = await browse.pick({ mode: "file", ext: ".png", initialPath: paths.value[id] });
  if (path) paths.value[id] = path;
}

async function uploadShots() {
  const items = targets.value
    .filter((item) => (paths.value[item.id] || "").trim())
    .map((item) => ({
      kind: item.kind,
      id: item.id,
      productId: item.productId,
      path: paths.value[item.id],
    }));
  const { task_id } = await httpJson<{ task_id: string }>("/api/iap/review-screenshots/upload", {
    method: "POST",
    body: JSON.stringify({ items, dryRun: reviewDry.value, verbose: reviewVerbose.value }),
  });
  taskId.value = task_id;
  enterRun();
  rail.openLogs(task_id);
}

onMounted(() => { void check(); });
</script>

<template>
  <div class="page-stack">
    <h1>{{ t("iap.title") }}</h1>
    <el-alert v-if="empty" type="warning" show-icon :title="t('index.no_app')">
      <router-link to="/profiles">{{ t("nav.profiles") }}</router-link>
    </el-alert>
    <el-alert v-if="alert" type="error" show-icon :title="alert" />
    <template v-if="isForm">
      <div class="card">
        <label class="field">
          <span>{{ t("iap.file") }}</span>
          <div class="field-row">
            <input v-model="iapFile" class="field-input" />
            <el-button @click="browse.pick({ mode: 'file', ext: '.json', initialPath: iapFile }).then((p) => { if (p) iapFile = p; })">{{ t("filebrowser.browse") }}</el-button>
          </div>
        </label>
        <a href="/api/examples/iap.json">{{ t("iap.download_sample") }}</a>
        <p v-if="checkMsg">{{ checkMsg }}</p>
        <label class="check"><input v-model="dryRun" type="checkbox" /> {{ t("iap.dry_run") }}</label>
        <label class="check"><input v-model="updateExisting" type="checkbox" /> {{ t("iap.update_existing") }}</label>
        <label class="check"><input v-model="verbose" type="checkbox" /> {{ t("build.verbose") }}</label>
        <div class="field-row">
          <el-button :disabled="empty" @click="check">{{ t("iap.check_config") }}</el-button>
          <el-button type="primary" :disabled="empty" @click="run">{{ t("common.submit") }}</el-button>
        </div>
      </div>
      <div class="card">
        <h2>{{ t("iap.review_title") }}</h2>
        <el-button :disabled="empty" @click="scan">{{ t("iap.scan_missing") }}</el-button>
        <p v-if="targets.length">{{ t("iap.found_missing", { n: targets.length }) }}</p>
        <p v-else class="muted">{{ t("iap.no_missing") }}</p>
        <div v-for="item in targets" :key="item.id" class="shot-row">
          <div>
            <strong>{{ item.name || item.productId }}</strong>
            <div class="muted">{{ item.kind === "subscription" ? t("iap.kind_sub") : "IAP" }} · {{ item.productId }}</div>
          </div>
          <div class="field-row">
            <input v-model="paths[item.id]" class="field-input" />
            <el-button size="small" @click="pickPath(item.id)">{{ t("filebrowser.browse") }}</el-button>
            <img v-if="paths[item.id]" class="thumb" :src="`/api/listing/thumb?path=${encodeURIComponent(paths[item.id])}&root=${encodeURIComponent(paths[item.id].replace(/[/\\\\][^/\\\\]+$/, '') || '.')}`" alt="" @click="previewPath(paths[item.id])" />
          </div>
        </div>
        <label class="check"><input v-model="reviewDry" type="checkbox" /> {{ t("iap.preview") }}</label>
        <label class="check"><input v-model="reviewVerbose" type="checkbox" /> {{ t("build.verbose") }}</label>
        <el-button type="primary" :disabled="empty || !targets.length" @click="uploadShots">{{ t("iap.upload_shots") }}</el-button>
      </div>
    </template>
    <TaskRunBar v-if="isRun && taskId" :task-id="taskId" @back="backToForm" />
  </div>
</template>

<style scoped>
h1, h2 { margin: 0 0 8px; }
.card { display: flex; flex-direction: column; gap: 10px; }
.check { display: flex; gap: 8px; align-items: center; }
.muted { color: var(--text-muted); font-size: 12px; }
.shot-row { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--border); }
.thumb { width: 48px; height: 48px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border); }
</style>
