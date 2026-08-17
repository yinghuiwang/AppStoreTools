<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import PageLoading from "@/components/PageLoading.vue";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";

const { t } = useI18n();
const rail = useRightRail();
const {
  logTaskId,
  lines,
  status,
  progress,
  connection,
  follow,
  setActiveTask,
  cancel,
  clearLocal,
} = useTaskLog();
const scroller = ref<HTMLElement | null>(null);

function isErrorLine(message: string): boolean {
  return /error/i.test(message);
}

function canCancel() {
  return !["done", "error", "canceled"].includes(status.value);
}

async function copyLogs() {
  try {
    await navigator.clipboard.writeText(lines.value.map((l) => l.message).join("\n"));
    ElMessage.success(t("drawer.copied"));
  } catch {
    ElMessage.error(t("drawer.copy_failed"));
  }
}

function explain() {
  if (!logTaskId.value) return;
  rail.openAgent({ taskId: logTaskId.value, autoAnalyze: true });
}

watch(
  () => [logTaskId.value, lines.value.length, follow.value] as const,
  async () => {
    if (!follow.value) return;
    await nextTick();
    const el = scroller.value;
    if (el) el.scrollTop = el.scrollHeight;
  },
);

onMounted(() => {
  if (rail.logTaskId.value) setActiveTask(rail.logTaskId.value);
});
</script>

<template>
  <div class="logs" :data-log-task-id="logTaskId || undefined">
    <header class="head">
      <div class="head-row">
        <span class="title">{{ t("rail.tab.logs") }}</span>
        <span v-if="logTaskId" class="pill" :data-status="status || connection">
          {{ status || connection }}
        </span>
      </div>
      <p v-if="progress.msg || progress.pct" class="progress mono">
        {{ progress.pct }}% {{ progress.msg }}
      </p>
      <div v-if="progress.pct" class="bar">
        <i :style="{ width: `${Math.min(100, progress.pct)}%` }" />
      </div>
      <div v-if="logTaskId" class="tools">
        <button type="button" @click="copyLogs">{{ t("drawer.copy") }}</button>
        <button type="button" @click="clearLocal()">{{ t("drawer.clear") }}</button>
        <button type="button" :class="{ on: follow }" @click="follow = !follow">
          {{ t("drawer.follow") }}
        </button>
        <button v-if="canCancel()" type="button" @click="cancel()">{{ t("index.cancel") }}</button>
        <button v-if="status === 'error'" type="button" class="explain" @click="explain">
          {{ t("drawer.explain_with_agent") }}
        </button>
      </div>
    </header>
    <div v-if="!logTaskId" class="empty">{{ t("rail.logs.empty") }}</div>
    <PageLoading
      v-else-if="!lines.length && (connection === 'connecting' || connection === 'reconnecting')"
      size="block"
      :text="t('common.loading')"
    />
    <pre v-else ref="scroller" class="stream mono">
      <div
        v-for="line in lines"
        :key="line.seq"
        class="line"
        :class="{ err: isErrorLine(line.message) }"
      >{{ line.message }}</div>
    </pre>
  </div>
</template>

<style scoped>
.logs {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.head {
  padding: 12px 16px 10px 18px;
  border-bottom: 1px solid var(--border);
}

.head-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.title {
  font-size: 13px;
  font-weight: 650;
}

.pill {
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--raised);
  color: var(--text-muted);
}

.pill[data-status="live"],
.pill[data-status="done"] {
  color: var(--ok);
  background: rgba(52, 211, 153, 0.12);
}

.pill[data-status="error"] {
  color: var(--err);
  background: rgba(248, 113, 113, 0.12);
}

.pill[data-status="canceled"] {
  color: var(--warn);
}

.progress {
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 11px;
}

.bar {
  margin-top: 6px;
  height: 3px;
  background: var(--raised);
  border-radius: 99px;
  overflow: hidden;
}

.bar i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--accent-dim), var(--accent));
}

.tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.tools button {
  background: var(--raised);
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 6px;
  cursor: pointer;
}

.tools button.on,
.tools button.explain {
  color: var(--accent);
  border-color: rgba(143, 245, 210, 0.28);
}

.empty {
  padding: 24px 18px;
  color: var(--text-muted);
  font-size: 13px;
}

.stream {
  flex: 1;
  margin: 0;
  padding: 12px 16px 20px 18px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-muted);
}

.line.err {
  color: var(--err);
}
</style>
