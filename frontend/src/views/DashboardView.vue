<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { MessagePlugin } from "tdesign-vue-next";
import { httpJson } from "@/api/http";
import { mapRetryPath } from "@/api/types";
import PageLoading from "@/components/PageLoading.vue";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";

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
  cancel_requested?: boolean;
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

const QUICK_ACTIONS = [
  {
    to: { path: "/listing", query: { tab: "upload", action: "check" } },
    titleKey: "index.action_check",
    descKey: "index.action_check_desc",
    mark: "◎",
  },
  {
    to: { path: "/listing", query: { tab: "upload", action: "all" } },
    titleKey: "index.action_all",
    descKey: "index.action_all_desc",
    mark: "↑",
  },
  {
    to: { path: "/listing", query: { tab: "upload", action: "metadata" } },
    titleKey: "index.action_metadata",
    descKey: "index.action_metadata_desc",
    mark: "≡",
  },
  {
    to: { path: "/listing", query: { tab: "upload", action: "screenshots" } },
    titleKey: "index.action_screenshots",
    descKey: "index.action_screenshots_desc",
    mark: "▦",
  },
  {
    to: { path: "/build", query: { action: "build-upload" } },
    titleKey: "index.action_build",
    descKey: "index.action_build_desc",
    mark: "▶",
  },
] as const;

const { t } = useI18n();
const router = useRouter();
const { snapshot } = useProfile();
const rail = useRightRail();
const { channels } = useTaskLog();
defineOptions({ name: "DashboardView" });
const loading = ref(true);
const refreshError = ref("");
const summary = ref<Summary | null>(null);
const range = ref<"7d" | "30d" | "90d">("30d");
const profileFilter = ref(snapshot.value?.current_profile || "");
const kind = ref("");
const statusFilter = ref("");
const cancellingIds = ref<string[]>([]);

let refreshRequest = 0;
let refreshController: AbortController | null = null;
let pollTimer: number | null = null;

const running = computed(() =>
  (summary.value?.tasks || []).filter((task) => task.status === "pending" || task.status === "running"),
);

const historyTasks = computed(() => (summary.value?.tasks || []).slice(0, 20));

function formatDuration(seconds: number) {
  const n = Math.max(0, Math.floor(seconds || 0));
  if (n < 60) return t("index.duration.seconds", { n });
  if (n < 3600) return t("index.duration.minutes", { n: Math.floor(n / 60) });
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  return m >= 1 ? t("index.duration.hours_minutes", { h, m }) : t("index.duration.hours", { n: h });
}

function durationUnit(kind: "seconds" | "minutes" | "hours") {
  return String(t(`index.duration.${kind}`, { n: "" })).trim();
}

function durationStat(seconds: number) {
  const n = Math.max(0, Math.floor(seconds || 0));
  if (n < 60) return { value: n, unit: durationUnit("seconds"), suffix: "" };
  if (n < 3600) return { value: Math.floor(n / 60), unit: durationUnit("minutes"), suffix: "" };
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  return {
    value: h,
    unit: durationUnit("hours"),
    suffix: m >= 1 ? String(t("index.duration.minutes", { n: m })) : "",
  };
}

const savedStat = computed(() => durationStat(summary.value?.metrics.saved_seconds || 0));
const failedStat = computed(() => durationStat(summary.value?.metrics.failed_seconds || 0));
const successRate = computed(() => summary.value?.metrics.success_rate ?? null);

function statusLabel(status: string) {
  const key = `index.status.${status}`;
  const label = t(key);
  return label === key ? status || "--" : label;
}

function statusTheme(status: string): "success" | "danger" | "warning" | "primary" | "default" {
  if (status === "done") return "success";
  if (status === "error") return "danger";
  if (status === "canceled") return "warning";
  if (status === "running" || status === "pending") return "primary";
  return "default";
}

const historyColumns = computed(() => [
  { colKey: "task", title: t("index.col_task") },
  { colKey: "status", title: t("index.col_status"), width: 120 },
  { colKey: "profile", title: t("index.col_app"), width: 140 },
  { colKey: "started", title: t("index.col_started"), width: 150 },
  { colKey: "duration", title: t("index.col_duration"), width: 130 },
  { colKey: "actions", title: t("index.col_actions"), width: 240 },
]);

function historyRowClass({ row }: { row: Task }) {
  if (row.status === "error") return "is-error";
  if (row.status === "running" || row.status === "pending") return "is-running";
  return "";
}

function startedAt(value?: string) {
  return String(value || "").slice(0, 16).replace("T", " ") || "--";
}

function retryTo(path?: string) {
  const mapped = mapRetryPath(path);
  if (!ALLOWED_RETRY.has(mapped)) return "";
  return mapped === "/listing" ? "/listing?tab=upload" : mapped;
}

function isCancelling(task: Task) {
  return Boolean(task.cancel_requested) || cancellingIds.value.includes(task.id);
}

function clearPoll() {
  if (pollTimer != null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function schedulePoll() {
  clearPoll();
  if (Number(summary.value?.metrics.active_count || 0) <= 0) return;
  pollTimer = window.setTimeout(() => {
    if (document.visibilityState === "visible") void load();
    else schedulePoll();
  }, 3000);
}

async function load() {
  clearPoll();
  refreshController?.abort();
  const controller = new AbortController();
  const requestId = ++refreshRequest;
  refreshController = controller;
  const first = !summary.value;
  loading.value = first;
  try {
    const qs = new URLSearchParams({ range: range.value, profile: profileFilter.value });
    if (kind.value) qs.set("kind", kind.value);
    if (statusFilter.value) qs.set("status", statusFilter.value);
    const next = await httpJson<Summary>(`/api/dashboard/summary?${qs}`, {
      signal: controller.signal,
      skipNotify: true,
    });
    if (requestId !== refreshRequest) return;
    summary.value = next;
    refreshError.value = "";
  } catch (err) {
    if (requestId !== refreshRequest) return;
    if (err instanceof DOMException && err.name === "AbortError") return;
    refreshError.value = t("dashboard.refresh_failed");
  } finally {
    if (requestId === refreshRequest) {
      loading.value = false;
      refreshController = null;
      schedulePoll();
    }
  }
}

async function cancel(id: string) {
  cancellingIds.value = [...cancellingIds.value, id];
  try {
    await httpJson(`/api/task/${encodeURIComponent(id)}/cancel`, { method: "POST" });
    await load();
  } catch {
    MessagePlugin.error(t("dashboard.cancel_failed"));
  } finally {
    cancellingIds.value = cancellingIds.value.filter((item) => item !== id);
  }
}

function onVisible() {
  if (document.visibilityState === "visible" && Number(summary.value?.metrics.active_count || 0) > 0) {
    void load();
  }
}

watch([range, profileFilter, kind, statusFilter], () => {
  void load();
});

watch(
  channels,
  () => {
    const tasks = summary.value?.tasks;
    if (!tasks) return;
    for (const task of tasks) {
      const ch = channels[task.id];
      if (!ch) continue;
      task.progress = { pct: ch.progress.pct, msg: ch.progress.msg };
    }
  },
  { deep: true },
);

watch(
  () => Object.entries(channels).map(([id, ch]) => `${id}:${ch.status}`).sort().join(","),
  (next, prev) => {
    if (!prev || next === prev) return;
    if (/(?:^|,)[^:]+:(?:done|error|canceled)(?:,|$)/.test(next)) void load();
  },
);

onMounted(() => {
  document.addEventListener("visibilitychange", onVisible);
});

onActivated(() => {
  void load();
});

onDeactivated(() => {
  refreshController?.abort();
  clearPoll();
});

onUnmounted(() => {
  document.removeEventListener("visibilitychange", onVisible);
  refreshController?.abort();
  clearPoll();
});
</script>

<template>
  <div class="page-stack dash" :aria-busy="loading && !summary">
    <header class="dash-toolbar">
      <div class="dash-id">
        <p class="kicker">COMMAND WORKSPACE</p>
        <h1>{{ t("index.title") }}</h1>
        <p v-if="refreshError" class="refresh-status" role="status" aria-live="polite">{{ refreshError }}</p>
      </div>
      <section class="filters" :aria-label="t('index.filter_aria')">
        <fieldset>
          <legend>{{ t("index.range") }}</legend>
          <t-radio-group v-model="range" variant="default-filled" size="small">
            <t-radio-button
              v-for="item in (['7d', '30d', '90d'] as const)"
              :key="item"
              :value="item"
            >
              {{ t(`index.range_${item}`) }}
            </t-radio-button>
          </t-radio-group>
        </fieldset>
        <label>
          <span>App</span>
          <t-select v-model="profileFilter" class="filter-select" clearable :placeholder="t('index.all_apps')">
            <t-option value="" :label='t("index.all_apps")' />
            <t-option v-for="name in snapshot?.profiles || []" :key="name" :value="name" :label="name" />
          </t-select>
        </label>
        <label>
          <span>{{ t("index.status") }}</span>
          <t-select v-model="statusFilter" class="filter-select" clearable :placeholder="t('index.all_statuses')">
            <t-option value="" :label='t("index.all_statuses")' />
            <t-option value="pending" :label="t('index.status.pending')" />
            <t-option value="running" :label="t('index.status.running')" />
            <t-option value="done" :label="t('index.status.done')" />
            <t-option value="error" :label="t('index.status.error')" />
            <t-option value="canceled" :label="t('index.status.canceled')" />
          </t-select>
        </label>
        <label>
          <span>{{ t("index.kind") }}</span>
          <t-select v-model="kind" class="filter-select" clearable :placeholder="t('index.all_kinds')">
            <t-option value="" :label='t("index.all_kinds")' />
            <t-option value="metadata" :label="t('index.kind_metadata')" />
            <t-option value="build" :label="t('index.kind_build')" />
            <t-option value="whats-new" :label="t('index.kind_whats_new')" />
            <t-option value="iap" :label="t('index.kind_iap')" />
            <t-option value="iap-review-screenshots" :label="t('index.kind_iap_review')" />
            <t-option value="urls" :label="t('index.kind_urls')" />
            <t-option value="update" :label="t('index.kind_update')" />
          </t-select>
        </label>
      </section>
    </header>

    <div class="dash-top">
      <section v-if="loading && !summary" class="metrics-loading" :aria-label="t('index.summary_aria')">
        <PageLoading size="page" />
      </section>
      <template v-else-if="summary">
        <section class="metrics" :aria-label="t('index.metrics_aria')">
          <article class="metric metric--accent">
            <t-statistic
              :title='t("index.metric_saved")'
              :value="savedStat.value"
              :unit="savedStat.unit"
              :suffix="savedStat.suffix"
              :extra='t("index.metric_saved_hint")'
              color="blue"
              trend="increase"
            />
          </article>
          <article class="metric metric--ok" :class="{ 'is-empty': successRate == null }">
            <t-statistic
              :title='t("index.metric_success")'
              :value="successRate ?? 0"
              :unit="successRate == null ? '' : '%'"
              :extra='t("index.metric_completed", { n: summary.metrics.completed_count })'
              color="green"
              :trend="successRate == null ? undefined : 'increase'"
              trend-placement="right"
            >
              <template v-if="successRate == null" #suffix>—</template>
            </t-statistic>
          </article>
          <article class="metric metric--err">
            <t-statistic
              :title='t("index.metric_failed")'
              :value="failedStat.value"
              :unit="failedStat.unit"
              :suffix="failedStat.suffix"
              :extra='t("index.metric_failed_hint")'
              color="red"
              trend="decrease"
            />
          </article>
          <article class="metric metric--info">
            <t-statistic
              :title='t("index.metric_running")'
              :value="summary.metrics.running_count"
              :extra='t("index.metric_running_hint")'
              :color="'var(--info)'"
            />
          </article>
        </section>
        <details class="estimate">
          <summary>{{ t("index.estimate_summary") }}</summary>
          <p><strong>{{ t("index.estimate_p1") }}</strong></p>
          <p>{{ t("index.estimate_p2") }}</p>
        </details>
      </template>
    </div>

    <div class="dash-split">
      <section class="card running" aria-labelledby="running-tasks-title">
        <div class="section-head">
          <div>
            <p class="kicker">ACTIVE QUEUE</p>
            <h2 id="running-tasks-title">{{ t("index.running_title") }}</h2>
          </div>
          <span class="count">{{ running.length }}</span>
        </div>
        <div class="run-list">
          <template v-if="summary">
            <article v-for="task in running" :key="task.id" class="run-row">
              <div class="run-pulse" aria-hidden="true"><span /></div>
              <div class="run-main">
                <div class="run-title">
                  <strong>{{ task.title || t("dashboard.unnamed_task") }}</strong>
                  <span>{{ task.profile || t("index.no_profile") }}</span>
                </div>
                <t-progress
                  :percentage="task.progress?.pct || 0"
                  :label="false"
                  size="small"
                  :aria-label="t('index.progress_aria', { title: task.title || t('dashboard.unnamed_task') })"
                />
                <small>{{ task.progress?.msg || (task.status === "pending" ? t("index.waiting") : t("index.executing")) }}</small>
              </div>
              <div class="run-actions">
                <t-button size="small" @click="rail.openLogs(task.id)">{{ t("index.log") }}</t-button>
                <t-popconfirm :content="t('dashboard.confirm_cancel')" @confirm="cancel(task.id)">
                  <t-button size="small" :disabled="isCancelling(task)">
                    {{ isCancelling(task) ? t("dashboard.canceling") : t("index.cancel") }}
                  </t-button>
                </t-popconfirm>
              </div>
            </article>
            <t-empty v-if="!running.length" :description="t('index.empty_running')" />
          </template>
          <t-empty v-else-if="!loading" :description="refreshError || t('index.empty_running')" />
        </div>
      </section>

      <nav class="card quick" :aria-label="t('index.quick_aria')">
        <div class="section-head">
          <div>
            <p class="kicker">RUNBOOK</p>
            <h2 id="quick-actions-title">{{ t("index.quick_title") }}</h2>
          </div>
          <span>{{ t("index.quick_hint") }}</span>
        </div>
        <div class="quick-list">
          <router-link
            v-for="action in QUICK_ACTIONS"
            :key="action.titleKey"
            class="quick-link"
            :to="action.to"
          >
            <span class="quick-mark" aria-hidden="true">{{ action.mark }}</span>
            <span>
              <strong>{{ t(action.titleKey) }}</strong>
              <small>{{ t(action.descKey) }}</small>
            </span>
            <span class="quick-arrow" aria-hidden="true">›</span>
          </router-link>
        </div>
      </nav>
    </div>

    <section class="card history" aria-labelledby="task-history-title">
      <div class="section-head">
        <div>
          <p class="kicker">TASK LEDGER</p>
          <h2 id="task-history-title">{{ t("index.history_title") }}</h2>
        </div>
        <span>{{ t("index.recent_n", { n: historyTasks.length }) }}</span>
      </div>
      <div class="table-wrap">
        <t-table
          :data="historyTasks"
          :columns="historyColumns"
          row-key="id"
          size="small"
          :row-class-name="historyRowClass"
        >
          <template #task="{ row }">
            <strong>{{ row.title || t("dashboard.unnamed_task") }}</strong>
            <small>{{ row.kind }}</small>
          </template>
          <template #status="{ row }">
            <t-tag :theme="statusTheme(row.status)" variant="light" size="small">{{ statusLabel(row.status) }}</t-tag>
          </template>
          <template #profile="{ row }"><span class="mono">{{ row.profile || "--" }}</span></template>
          <template #started="{ row }"><span class="mono">{{ startedAt(row.created_at) }}</span></template>
          <template #duration="{ row }">
            <span class="mono">{{ row.duration_label || formatDuration(row.duration_seconds || 0) }}</span>
          </template>
          <template #actions="{ row }">
            <div class="actions">
              <t-button size="small" @click="rail.openLogs(row.id)">{{ t("index.log") }}</t-button>
              <t-button
                v-if="row.status === 'error'"
                size="small"
                @click="rail.openAgent({ taskId: row.id, autoAnalyze: true })"
              >
                {{ t("drawer.explain_with_agent") }}
              </t-button>
              <t-button
                v-if="row.status === 'error' && retryTo(row.retry_path)"
                size="small"
                @click="router.push(retryTo(row.retry_path))"
              >
                {{ t("index.retry") }}
              </t-button>
            </div>
          </template>
          <template #empty>
            <t-empty :description="t('index.empty_history')" />
          </template>
        </t-table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dash {
  width: 100%;
  flex: 1 1 auto;
  gap: 8px;
}
.dash-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 8px 16px;
  flex-wrap: wrap;
  width: 100%;
  flex: 0 0 auto;
}
.dash-id { min-width: 180px; }
.dash-id h1 {
  margin: 0;
  font-size: 22px;
  letter-spacing: -0.03em;
  line-height: 1.2;
}
.kicker {
  margin: 0 0 4px;
  font-size: 10px;
  letter-spacing: 0.16em;
  color: var(--accent-dim);
}
.refresh-status {
  margin: 2px 0 0;
  min-height: 1.1em;
  color: var(--text-muted);
  font-size: 12px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: end;
  margin-left: auto;
}
.filters fieldset { border: 0; padding: 0; margin: 0; }
.filters legend,
.filters span {
  display: block;
  font-size: 10px;
  color: var(--text-faint);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 4px;
}
.filters .filter-select {
  width: 140px;
}
.dash-top {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  flex: 0 0 auto;
}
.metrics {
  width: 100%;
  gap: 8px;
}
.metrics-loading { min-height: 64px; }
.metric {
  position: relative;
  overflow: hidden;
  padding: 10px 12px;
  border-radius: 8px;
}
.metric::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 2px;
  background: var(--accent-dim);
}
.metric--ok::before { background: var(--ok); }
.metric--err::before { background: var(--err); }
.metric--info::before { background: var(--info); }
.metric :deep(.t-statistic) { width: 100%; }
.metric :deep(.t-statistic-title) {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.3;
}
.metric :deep(.t-statistic-content) {
  align-items: baseline;
  margin: 4px 0 2px;
  font-size: 20px;
  font-weight: 600;
  line-height: 1.2;
}
.metric :deep(.t-statistic-content-unit),
.metric :deep(.t-statistic-content-suffix) {
  font-size: 13px;
  font-weight: 500;
}
.metric :deep(.t-statistic-extra) {
  color: var(--text-faint);
  font-size: 12px;
  line-height: 1.35;
}
.metric.is-empty :deep(.t-statistic-content-value) { display: none; }
.estimate {
  padding: 4px 2px 0;
  color: var(--text-muted);
  font-size: 12px;
}
.estimate summary {
  cursor: pointer;
  color: var(--text-muted);
  font-size: 12px;
}
.estimate p { margin: 6px 0 0; color: var(--text-muted); font-size: 12px; line-height: 1.45; }
.dash-split {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  gap: 8px;
  align-items: stretch;
  flex: 0 0 auto;
}
.running,
.quick,
.history {
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-radius: 8px;
}
.running,
.history {
  padding: 10px 12px 12px;
}
.section-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  flex: 0 0 auto;
}
.section-head h2 { margin: 0; font-size: 14px; }
.section-head > span { color: var(--text-faint); font-size: 12px; }
.count {
  min-width: 28px;
  padding: 2px 8px;
  border: 1px solid color-mix(in srgb, var(--info) 35%, var(--border));
  border-radius: 6px;
  background: color-mix(in srgb, var(--info) 12%, transparent);
  color: var(--info);
  font-family: "Fira Code", ui-monospace, monospace;
  font-size: 12px;
  text-align: center;
}
.run-list,
.quick-list,
.table-wrap {
  flex: 1 1 auto;
}
.run-row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
}
.run-row:last-of-type { border-bottom: 0; }
.run-pulse {
  width: 16px;
  height: 16px;
  display: grid;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--info) 40%, var(--border));
  border-radius: 50%;
}
.run-pulse span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--info);
  animation: dash-pulse 1.4s ease-in-out infinite;
}
.run-main { min-width: 0; }
.run-title { display: flex; justify-content: space-between; gap: 12px; }
.run-title span,
.run-main small { color: var(--text-muted); font-size: 12px; }
.run-main small { display: block; margin-top: 4px; }
.run-actions { display: flex; gap: 6px; flex-shrink: 0; }
.run-main :deep(.t-progress) { margin-top: 6px; }
.quick { padding: 10px 0 8px; }
.quick .section-head { padding: 0 12px; }
.quick-link {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 12px;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  color: var(--text);
  text-decoration: none;
  border-top: 1px solid var(--border);
}
.quick-link:hover {
  background: var(--overlay);
  text-decoration: none;
  box-shadow: inset 3px 0 0 var(--accent-dim);
}
.quick-mark {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--accent);
  font-size: 13px;
}
.quick-link strong,
.quick-link small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.quick-link small { margin-top: 2px; color: var(--text-muted); font-size: 12px; }
.quick-arrow { color: var(--text-faint); font-size: 18px; }
.history {
  flex: 1 1 auto;
}
.table-wrap :deep(strong),
.table-wrap :deep(small) { display: block; }
.table-wrap :deep(strong) { color: var(--text); font-weight: 500; }
.table-wrap :deep(small) { margin-top: 2px; color: var(--text-faint); font-size: 11px; }
.table-wrap :deep(tr.is-error td) { background: color-mix(in srgb, var(--err) 8%, transparent); }
.table-wrap :deep(tr.is-running td) { background: color-mix(in srgb, var(--info) 7%, transparent); }
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
@keyframes dash-pulse { 50% { opacity: 0.35; } }
@media (max-width: 1100px) {
  .dash-split {
    grid-template-columns: 1fr;
  }
}
</style>
