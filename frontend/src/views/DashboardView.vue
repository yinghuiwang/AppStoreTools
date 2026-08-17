<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
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
const logs = useTaskLog();
const loading = ref(true);
const refreshStatus = ref("");
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

function statusLabel(status: string) {
  const key = `index.status.${status}`;
  const label = t(key);
  return label === key ? status || "--" : label;
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
  if (!first) refreshStatus.value = t("dashboard.refreshing");
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
    refreshStatus.value = "";
  } catch (err) {
    if (requestId !== refreshRequest) return;
    if (err instanceof DOMException && err.name === "AbortError") return;
    refreshStatus.value = t("dashboard.refresh_failed");
  } finally {
    if (requestId === refreshRequest) {
      loading.value = false;
      refreshController = null;
      schedulePoll();
    }
  }
}

async function cancel(id: string) {
  if (!window.confirm(t("dashboard.confirm_cancel"))) return;
  cancellingIds.value = [...cancellingIds.value, id];
  try {
    await httpJson(`/api/task/${encodeURIComponent(id)}/cancel`, { method: "POST" });
    await load();
  } catch {
    window.alert(t("dashboard.cancel_failed"));
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
  () => [logs.logTaskId.value, logs.progress.value.pct, logs.progress.value.msg] as const,
  ([taskId, pct, msg]) => {
    const task = summary.value?.tasks.find((item) => item.id === taskId);
    if (!task) return;
    task.progress = { pct, msg };
  },
);

watch(
  () => logs.status.value,
  (status) => {
    if (status === "done" || status === "error" || status === "canceled") void load();
  },
);

onMounted(() => {
  document.addEventListener("visibilitychange", onVisible);
  void load();
});

onUnmounted(() => {
  document.removeEventListener("visibilitychange", onVisible);
  refreshController?.abort();
  clearPoll();
});
</script>

<template>
  <div class="page-stack dash" :aria-busy="Boolean(refreshStatus)">
    <header class="dash-head">
      <div>
        <p class="kicker">COMMAND WORKSPACE</p>
        <h1>{{ t("index.title") }}</h1>
      </div>
      <p class="refresh-status" role="status" aria-live="polite">{{ refreshStatus }}</p>
    </header>

    <section class="filters" :aria-label="t('index.filter_aria')">
      <fieldset>
        <legend>{{ t("index.range") }}</legend>
        <div class="seg">
          <button
            v-for="item in (['7d', '30d', '90d'] as const)"
            :key="item"
            type="button"
            :class="{ on: range === item }"
            :aria-pressed="range === item"
            @click="range = item"
          >
            {{ t(`index.range_${item}`) }}
          </button>
        </div>
      </fieldset>
      <label>
        <span>App</span>
        <select v-model="profileFilter" class="field-input">
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
    </section>

    <section v-if="loading && !summary" class="metrics-loading" :aria-label="t('index.summary_aria')">
      <PageLoading size="block" />
    </section>

    <template v-else-if="summary">
      <section class="metrics" :aria-label="t('index.metrics_aria')">
        <article class="metric metric--accent">
          <span>{{ t("index.metric_saved") }}</span>
          <strong>{{ formatDuration(summary.metrics.saved_seconds) }}</strong>
          <small>{{ t("index.metric_saved_hint") }}</small>
        </article>
        <article class="metric metric--ok">
          <span>{{ t("index.metric_success") }}</span>
          <strong>{{ summary.metrics.success_rate == null ? "—" : `${summary.metrics.success_rate}%` }}</strong>
          <small>{{ t("index.metric_completed", { n: summary.metrics.completed_count }) }}</small>
        </article>
        <article class="metric metric--err">
          <span>{{ t("index.metric_failed") }}</span>
          <strong>{{ formatDuration(summary.metrics.failed_seconds) }}</strong>
          <small>{{ t("index.metric_failed_hint") }}</small>
        </article>
        <article class="metric metric--info">
          <span>{{ t("index.metric_running") }}</span>
          <strong>{{ summary.metrics.running_count }}</strong>
          <small>{{ t("index.metric_running_hint") }}</small>
        </article>
      </section>
      <details class="card estimate">
        <summary>{{ t("index.estimate_summary") }}</summary>
        <p><strong>{{ t("index.estimate_p1") }}</strong></p>
        <p>{{ t("index.estimate_p2") }}</p>
      </details>
    </template>

    <div class="dash-split">
      <section class="card running" aria-labelledby="running-tasks-title">
        <div class="section-head">
          <div>
            <p class="kicker">ACTIVE QUEUE</p>
            <h2 id="running-tasks-title">{{ t("index.running_title") }}</h2>
          </div>
          <span class="count">{{ running.length }}</span>
        </div>
        <template v-if="summary">
        <article v-for="task in running" :key="task.id" class="run-row">
          <div class="run-pulse" aria-hidden="true"><span /></div>
          <div class="run-main">
            <div class="run-title">
              <strong>{{ task.title || t("dashboard.unnamed_task") }}</strong>
              <span>{{ task.profile || t("index.no_profile") }}</span>
            </div>
            <div
              class="bar"
              role="progressbar"
              :aria-label="t('index.progress_aria', { title: task.title || t('dashboard.unnamed_task') })"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-valuenow="task.progress?.pct || 0"
            >
              <span :style="{ width: `${task.progress?.pct || 0}%` }" />
            </div>
            <small>{{ task.progress?.msg || (task.status === "pending" ? t("index.waiting") : t("index.executing")) }}</small>
          </div>
          <div class="run-actions">
            <el-button size="small" @click="rail.openLogs(task.id)">{{ t("index.log") }}</el-button>
            <el-button size="small" :disabled="isCancelling(task)" @click="cancel(task.id)">
              {{ isCancelling(task) ? t("dashboard.canceling") : t("index.cancel") }}
            </el-button>
          </div>
        </article>
        <p v-if="!running.length" class="empty-state">{{ t("index.empty_running") }}</p>
        </template>
        <p v-else-if="!loading" class="empty-state">{{ refreshStatus || t("index.empty_running") }}</p>
      </section>

      <nav class="card quick" :aria-label="t('index.quick_aria')">
        <div class="section-head">
          <div>
            <p class="kicker">RUNBOOK</p>
            <h2 id="quick-actions-title">{{ t("index.quick_title") }}</h2>
          </div>
          <span>{{ t("index.quick_hint") }}</span>
        </div>
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
      </nav>
    </div>

    <section v-if="summary" class="card history" aria-labelledby="task-history-title">
      <div class="section-head">
        <div>
          <p class="kicker">TASK LEDGER</p>
          <h2 id="task-history-title">{{ t("index.history_title") }}</h2>
        </div>
        <span>{{ t("index.recent_n", { n: historyTasks.length }) }}</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">{{ t("index.col_task") }}</th>
              <th scope="col">{{ t("index.col_status") }}</th>
              <th scope="col">{{ t("index.col_app") }}</th>
              <th scope="col">{{ t("index.col_started") }}</th>
              <th scope="col">{{ t("index.col_duration") }}</th>
              <th scope="col">{{ t("index.col_actions") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in historyTasks"
              :key="row.id"
              :class="{
                'is-error': row.status === 'error',
                'is-running': row.status === 'running' || row.status === 'pending',
              }"
            >
              <td>
                <strong>{{ row.title || t("dashboard.unnamed_task") }}</strong>
                <small>{{ row.kind }}</small>
              </td>
              <td>
                <span class="status" :class="`is-${row.status}`">{{ statusLabel(row.status) }}</span>
              </td>
              <td class="mono">{{ row.profile || "--" }}</td>
              <td class="mono">{{ startedAt(row.created_at) }}</td>
              <td class="mono">{{ row.duration_label || formatDuration(row.duration_seconds || 0) }}</td>
              <td class="actions">
                <el-button size="small" @click="rail.openLogs(row.id)">{{ t("index.log") }}</el-button>
                <el-button
                  v-if="row.status === 'error'"
                  size="small"
                  @click="rail.openAgent({ taskId: row.id, autoAnalyze: true })"
                >
                  {{ t("drawer.explain_with_agent") }}
                </el-button>
                <el-button
                  v-if="row.status === 'error' && retryTo(row.retry_path)"
                  size="small"
                  @click="router.push(retryTo(row.retry_path))"
                >
                  {{ t("index.retry") }}
                </el-button>
              </td>
            </tr>
            <tr v-if="!historyTasks.length">
              <td colspan="6" class="empty-state">{{ t("index.empty_history") }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dash { width: 100%; }
.metrics-loading { min-height: 72px; }
.dash-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}
.dash-head h1 { margin: 0; font-size: 28px; letter-spacing: -0.03em; }
.kicker {
  margin: 0 0 6px;
  font-size: 11px;
  letter-spacing: 0.18em;
  color: var(--accent-dim);
}
.refresh-status {
  margin: 0;
  min-height: 1.2em;
  color: var(--text-muted);
  font-size: 12px;
}
.filters { display: flex; flex-wrap: wrap; gap: 16px; align-items: end; }
.filters fieldset { border: 0; padding: 0; margin: 0; }
.filters legend,
.filters span {
  display: block;
  font-size: 11px;
  color: var(--text-faint);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 6px;
}
.seg { display: flex; gap: 4px; }
.seg button {
  background: var(--raised);
  color: var(--text-muted);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 10px;
}
.seg button.on { color: #0a0a0c; background: var(--accent); border-color: transparent; }
.metric { position: relative; overflow: hidden; }
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
.estimate p { margin: 8px 0 0; color: var(--text-muted); font-size: 12px; line-height: 1.5; }
.dash-split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 340px);
  gap: 16px;
  align-items: start;
}
.section-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.section-head h2 { margin: 0; font-size: 15px; }
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
.run-row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 12px 0;
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
.bar {
  height: 4px;
  background: var(--raised);
  border-radius: 99px;
  margin-top: 8px;
  overflow: hidden;
}
.bar span { display: block; height: 100%; background: var(--info); }
.quick { display: flex; flex-direction: column; gap: 0; padding: 18px 0 8px; }
.quick .section-head { padding: 0 20px; }
.quick-link {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 12px;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
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
  width: 28px;
  height: 28px;
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
.table-wrap { overflow: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th {
  text-align: left;
  color: var(--text-faint);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
}
td {
  padding: 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text-muted);
  vertical-align: middle;
}
td strong,
td small { display: block; }
td strong { color: var(--text); font-weight: 500; }
td small { margin-top: 2px; color: var(--text-faint); font-size: 11px; }
tr.is-error td { background: color-mix(in srgb, var(--err) 8%, transparent); }
tr.is-running td { background: color-mix(in srgb, var(--info) 7%, transparent); }
.status { display: inline-flex; align-items: center; gap: 6px; }
.status::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-faint);
}
.status.is-done { color: var(--ok); }
.status.is-done::before { background: var(--ok); }
.status.is-error { color: var(--err); }
.status.is-error::before { background: var(--err); }
.status.is-running { color: var(--info); }
.status.is-running::before { background: var(--info); animation: dash-pulse 1.4s ease-in-out infinite; }
.status.is-pending { color: var(--accent); }
.status.is-pending::before { background: var(--accent); }
.status.is-canceled { color: var(--text-muted); }
.actions { white-space: nowrap; }
@keyframes dash-pulse { 50% { opacity: 0.35; } }
@media (max-width: 1100px) {
  .dash-split { grid-template-columns: 1fr; }
}
</style>
