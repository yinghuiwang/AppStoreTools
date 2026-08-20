<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { MessagePlugin } from "tdesign-vue-next";
import PageLoading from "@/components/PageLoading.vue";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";
import { classifyLogLevel } from "@/utils/logLevel";

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
const errorsOnly = ref(false);

function lineLevel(line: { message: string; level?: string }) {
  return classifyLogLevel(line.message, line.level);
}

const visibleLines = computed(() => (
  errorsOnly.value
    ? lines.value.filter((line) => lineLevel(line) === "error")
    : lines.value
));

function canCancel() {
  return !["done", "error", "canceled"].includes(status.value);
}

async function copyLogs() {
  try {
    await navigator.clipboard.writeText(visibleLines.value.map((l) => l.message).join("\n"));
    MessagePlugin.success(t("drawer.copied"));
  } catch {
    MessagePlugin.error(t("drawer.copy_failed"));
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
      <t-progress v-if="progress.pct" :percentage="Math.min(100, progress.pct)" :label="false" size="small" />
      <div v-if="logTaskId" class="tools">
        <t-button size="small" @click="copyLogs">{{ t("drawer.copy") }}</t-button>
        <t-button size="small" @click="clearLocal()">{{ t("drawer.clear") }}</t-button>
        <t-button size="small" :variant="errorsOnly ? 'base' : 'outline'" :theme="errorsOnly ? 'primary' : 'default'" @click="errorsOnly = !errorsOnly">
          {{ t("drawer.errors_only") }}
        </t-button>
        <t-button size="small" :variant="follow ? 'base' : 'outline'" :theme="follow ? 'primary' : 'default'" @click="follow = !follow">
          {{ t("drawer.follow") }}
        </t-button>
        <t-button v-if="canCancel()" size="small" @click="cancel()">{{ t("index.cancel") }}</t-button>
        <t-button v-if="status === 'error'" size="small" theme="primary" variant="outline" @click="explain">
          {{ t("drawer.explain_with_agent") }}
        </t-button>
      </div>
    </header>
    <t-empty v-if="!logTaskId" :description="t('rail.logs.empty')" />
    <PageLoading
      v-else-if="!lines.length && (connection === 'connecting' || connection === 'reconnecting')"
      size="block"
      :text="t('common.loading')"
    />
    <pre v-else ref="scroller" class="stream mono">
      <div
        v-for="line in visibleLines"
        :key="line.seq"
        class="line"
        :class="{
          err: lineLevel(line) === 'error',
          warn: lineLevel(line) === 'warning',
        }"
        :data-level="lineLevel(line)"
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

.head :deep(.t-progress) {
  margin-top: 6px;
}

.tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
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

.line.warn {
  color: var(--warn);
}
</style>
