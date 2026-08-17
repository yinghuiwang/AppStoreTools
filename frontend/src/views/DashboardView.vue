<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { httpJson } from "@/api/http";
import { mapRetryPath } from "@/api/types";
import PageLoading from "@/components/PageLoading.vue";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";

type Task = {
  id: string;
  title?: string;
  kind?: string;
  profile?: string;
  status: string;
  created_at?: string;
  duration_seconds?: number;
  duration_label?: string;
  retry_path?: string;
  progress?: { pct?: number; msg?: string };
};

type Summary = {
  metrics: {
    saved_seconds: number;
    success_rate: number | null;
    failed_seconds: number;
    running_count: number;
    active_count: number;
    completed_count: number;
  };
  tasks: Task[];
  baseline_minutes: Record<string, number>;
  range_days: number;
};

const ALLOWED_RETRY = new Set(["/listing", "/build", "/whats-new", "/iap", "/urls", "/update"]);

const { t } = useI18n();
const router = useRouter();
const { snapshot } = useProfile();
const rail = useRightRail();
const loading = ref(true);
const refreshing = ref(false);
const summary = ref<Summary | null>(null);
const range = ref<"7d" | "30d" | "90d">("30d");
const profileFilter = ref(snapshot.value?.current_profile || "");
const kind = ref("");
const statusFilter = ref("");
const pickedAll = ref(false);
const showNoApp = computed(
  () => (snapshot.value?.current_profile || "") === "" && !pickedAll.value,
);

const running = computed(() =>
  (summary.value?.tasks || []).filter((task) => task.status === "pending" || task.status === "running"),
);

function formatDuration(seconds: number) {
  const n = Math.max(0, Math.floor(seconds || 0));
  if (n < 60) return t("index.duration.seconds", { n });
  if (n < 3600) return t("index.duration.minutes", { n: Math.floor(n / 60) });
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  return m >= 1 ? t("index.duration.hours_minutes", { h, m }) : t("index.duration.hours", { n: h });
}

function retryTo(path?: string) {
  const mapped = mapRetryPath(path);
  return ALLOWED_RETRY.has(mapped) ? mapped : "";
}

async function load() {
  const first = !summary.value;
  loading.value = first;
  refreshing.value = !first;
  try {
    const qs = new URLSearchParams({ range: range.value });
    qs.set("profile", profileFilter.value);
    if (kind.value) qs.set("kind", kind.value);
    if (statusFilter.value) qs.set("status", statusFilter.value);
    summary.value = await httpJson<Summary>(`/api/dashboard/summary?${qs}`);
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

async function cancel(id: string) {
  if (!window.confirm(t("dashboard.confirm_cancel"))) return;
  await httpJson(`/api/task/${encodeURIComponent(id)}/cancel`, { method: "POST" });
  await load();
}

watch([range, profileFilter, kind, statusFilter, pickedAll], () => {
  if (!showNoApp.value) void load();
});
onMounted(() => {
  if (!showNoApp.value) void load();
  else loading.value = false;
});
</script>

<template>
  <div class="page-stack dash">
    <header>
      <p class="kicker">COMMAND WORKSPACE</p>
      <h1>{{ t("index.title") }}</h1>
    </header>

    <section class="filters" :aria-label="t('index.filter_aria')">
      <fieldset>
        <legend>{{ t("index.range") }}</legend>
        <div class="seg">
          <button v-for="item in (['7d','30d','90d'] as const)" :key="item" type="button" :class="{ on: range === item }" @click="range = item">
            {{ t(`index.range_${item}`) }}
          </button>
        </div>
      </fieldset>
      <label>
        <span>App</span>
        <select v-model="profileFilter" class="field-input" @change="pickedAll = profileFilter === ''">
          <option value="">{{ t("index.all_apps") }}</option>
          <option v-for="name in snapshot?.profiles || []" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <label>
        <span>{{ t("index.status") }}</span>
        <select v-model="statusFilter" class="field-input">
          <option value="">{{ t("index.all_statuses") }}</option>
          <option value="pending">{{ t("index.status.pending") }}</option>
          <option value="running">{{ t("index.status.running") }}</option>
          <option value="done">{{ t("index.status.done") }}</option>
          <option value="error">{{ t("index.status.error") }}</option>
          <option value="canceled">{{ t("index.status.canceled") }}</option>
        </select>
      </label>
      <label>
        <span>{{ t("index.kind") }}</span>
        <select v-model="kind" class="field-input">
          <option value="">{{ t("index.all_kinds") }}</option>
          <option value="metadata">{{ t("index.kind_metadata") }}</option>
          <option value="build">{{ t("index.kind_build") }}</option>
          <option value="whats-new">{{ t("index.kind_whats_new") }}</option>
          <option value="iap">{{ t("index.kind_iap") }}</option>
          <option value="iap-review-screenshots">{{ t("index.kind_iap_review") }}</option>
          <option value="urls">{{ t("index.kind_urls") }}</option>
          <option value="update">{{ t("index.kind_update") }}</option>
        </select>
      </label>
      <PageLoading v-if="refreshing" size="inline" />
    </section>

    <p v-if="showNoApp" class="empty-state">{{ t("index.no_app") }}</p>

    <PageLoading v-else-if="loading" size="block" />
    <template v-else-if="summary">
      <section class="metrics" :aria-label="t('index.metrics_aria')">
        <article class="metric">
          <span>{{ t("index.metric_saved") }}</span>
          <strong>{{ formatDuration(summary.metrics.saved_seconds) }}</strong>
          <small>{{ t("index.metric_saved_hint") }}</small>
        </article>
        <article class="metric">
          <span>{{ t("index.metric_success") }}</span>
          <strong>{{ summary.metrics.success_rate == null ? "—" : `${summary.metrics.success_rate}%` }}</strong>
          <small>{{ t("index.metric_completed", { n: summary.metrics.completed_count }) }}</small>
        </article>
        <article class="metric">
          <span>{{ t("index.metric_failed") }}</span>
          <strong>{{ formatDuration(summary.metrics.failed_seconds) }}</strong>
          <small>{{ t("index.metric_failed_hint") }}</small>
        </article>
        <article class="metric">
          <span>{{ t("index.metric_running") }}</span>
          <strong>{{ summary.metrics.active_count }}</strong>
          <small>{{ t("index.metric_running_hint") }}</small>
        </article>
      </section>
      <details class="card">
        <summary>{{ t("index.estimate_summary") }}</summary>
        <p>{{ t("index.estimate_p1") }}</p>
        <p>{{ t("index.estimate_p2") }}</p>
        <ul>
          <li v-for="(mins, key) in summary.baseline_minutes" :key="key">{{ key }}: {{ mins }}</li>
        </ul>
      </details>

      <section class="card">
        <h2>{{ t("index.running_title") }}</h2>
        <article v-for="task in running" :key="task.id" class="run-row">
          <div>
            <strong>{{ task.title || t("dashboard.unnamed_task") }}</strong>
            <small>{{ task.profile || t("index.no_profile") }} · {{ task.progress?.msg || (task.status === "pending" ? t("index.waiting") : t("index.executing")) }}</small>
            <div class="bar"><span :style="{ width: `${task.progress?.pct || 0}%` }" /></div>
          </div>
          <div class="field-row">
            <el-button size="small" @click="rail.openLogs(task.id)">{{ t("index.log") }}</el-button>
            <el-button size="small" @click="cancel(task.id)">{{ t("index.cancel") }}</el-button>
          </div>
        </article>
        <p v-if="!running.length" class="empty-state">{{ t("index.empty_running") }}</p>
      </section>

      <section class="card">
        <h2>{{ t("index.history_title") }} <small>{{ t("index.recent_n", { n: summary.tasks.length }) }}</small></h2>
        <el-table :data="summary.tasks">
          <el-table-column :label="t('index.col_task')">
            <template #default="{ row }">
              <strong>{{ row.title || t("dashboard.unnamed_task") }}</strong>
              <div class="muted">{{ row.kind }}</div>
            </template>
          </el-table-column>
          <el-table-column :label="t('index.col_status')">
            <template #default="{ row }">{{ t(`index.status.${row.status}`, row.status) }}</template>
          </el-table-column>
          <el-table-column :label="t('index.col_app')">
            <template #default="{ row }"><span class="mono">{{ row.profile || "--" }}</span></template>
          </el-table-column>
          <el-table-column :label="t('index.col_started')">
            <template #default="{ row }"><span class="mono">{{ String(row.created_at || "").slice(0, 16).replace("T", " ") }}</span></template>
          </el-table-column>
          <el-table-column :label="t('index.col_duration')">
            <template #default="{ row }"><span class="mono">{{ row.duration_label || formatDuration(row.duration_seconds || 0) }}</span></template>
          </el-table-column>
          <el-table-column :label="t('index.col_actions')">
            <template #default="{ row }">
              <el-button size="small" @click="rail.openLogs(row.id)">{{ t("index.log") }}</el-button>
              <el-button v-if="row.status === 'error'" size="small" @click="rail.openAgent({ taskId: row.id, autoAnalyze: true })">{{ t("drawer.explain_with_agent") }}</el-button>
              <el-button v-if="row.status === 'error' && retryTo(row.retry_path)" size="small" @click="router.push(retryTo(row.retry_path))">{{ t("index.retry") }}</el-button>
            </template>
          </el-table-column>
        </el-table>
        <p v-if="!summary.tasks.length" class="empty-state">{{ t("index.empty_history") }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.dash { width: 100%; }
header h1 { margin: 0; font-size: 28px; letter-spacing: -0.03em; }
.kicker { margin: 0 0 6px; font-size: 11px; letter-spacing: 0.18em; color: var(--accent-dim); }
.filters { display: flex; flex-wrap: wrap; gap: 16px; align-items: end; }
.filters fieldset { border: 0; padding: 0; margin: 0; }
.filters legend, .filters span { display: block; font-size: 11px; color: var(--text-faint); letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 6px; }
.seg { display: flex; gap: 4px; }
.seg button { background: var(--raised); color: var(--text-muted); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; }
.seg button.on { color: #0a0a0c; background: var(--accent); border-color: transparent; }
h2 { margin: 0 0 12px; font-size: 15px; }
h2 small { color: var(--text-faint); font-weight: 400; margin-left: 8px; }
.run-row { display: flex; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border); }
.run-row small, .muted { display: block; color: var(--text-muted); font-size: 12px; }
.bar { height: 4px; background: var(--raised); border-radius: 99px; margin-top: 8px; overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--accent-dim); }
</style>
