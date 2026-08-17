<script setup lang="ts">
import { computed, nextTick, onActivated, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";

const props = defineProps<{
  taskId: string;
  headline?: string;
  failTitle?: string;
  failHint?: string;
  runningHint?: string;
}>();

const emit = defineEmits<{ back: [] }>();

const { t } = useI18n();
const rail = useRightRail();
const { cancel, subscribeIfNeeded, setActiveTask, channelOf } = useTaskLog();
const { status, progress } = channelOf(() => props.taskId);
const canceling = ref(false);
const rootEl = ref<HTMLElement | null>(null);

function focusIfVisible() {
  if (!props.taskId) return;
  const el = rootEl.value;
  if (el && el.getClientRects().length === 0) return;
  setActiveTask(props.taskId);
}

watch(
  () => props.taskId,
  (id) => {
    canceling.value = false;
    if (!id) return;
    subscribeIfNeeded(id);
    if (rootEl.value) focusIfVisible();
  },
  { immediate: true },
);

onMounted(() => {
  void nextTick(focusIfVisible);
});

onActivated(() => {
  void nextTick(focusIfVisible);
});

watch(status, (value) => {
  if (["done", "error", "canceled"].includes(value)) canceling.value = false;
});

const runStatus = computed(() => {
  if (["done", "error", "canceled"].includes(status.value)) return status.value;
  return props.taskId ? "running" : "idle";
});

const finished = computed(() =>
  ["done", "error", "canceled"].includes(runStatus.value),
);

const resolvedHeadline = computed(() => {
  if (props.headline) return props.headline;
  if (runStatus.value === "done") return t("index.status.done");
  if (runStatus.value === "error") return t("index.status.error");
  if (runStatus.value === "canceled") return t("index.status.canceled");
  if (runStatus.value === "running") return t("index.status.running");
  return t("index.status.pending");
});

const pct = computed(() => {
  if (runStatus.value === "done") return 100;
  return Math.min(100, Math.max(0, Number(progress.value.pct) || 0));
});

const canCancel = computed(
  () => Boolean(props.taskId) && !finished.value,
);

const backLabel = computed(() =>
  finished.value ? t("task.edit_and_rerun") : t("task.back_to_form"),
);

async function onCancel() {
  if (!canCancel.value || canceling.value) return;
  canceling.value = true;
  try {
    await cancel(props.taskId);
  } catch {
    canceling.value = false;
  }
}
</script>

<template>
  <section
    v-if="props.taskId"
    ref="rootEl"
    class="run-panel"
    :class="`is-${runStatus}`"
    :aria-label="resolvedHeadline"
  >
    <div v-if="runStatus === 'error'" class="fail-banner" role="alert">
      <strong>{{ props.failTitle || t("common.fail_banner_title") }}</strong>
      <p>{{ progress.msg || props.failHint || t("common.fail_banner_hint") }}</p>
    </div>

    <header class="head">
      <h2>{{ resolvedHeadline }}</h2>
      <div class="actions">
        <el-button size="small" @click="rail.openLogs(props.taskId)">{{ t("common.logs") }}</el-button>
        <el-button
          v-if="canCancel"
          size="small"
          type="danger"
          plain
          :disabled="canceling"
          @click="onCancel"
        >
          {{ canceling ? t("common.canceling") : t("common.cancel_upload") }}
        </el-button>
        <el-button
          size="small"
          :type="finished ? 'primary' : 'default'"
          @click="emit('back')"
        >
          {{ backLabel }}
        </el-button>
      </div>
    </header>

    <slot />

    <div class="meter" :class="{ error: runStatus === 'error', live: runStatus === 'running' }">
      <i :style="{ width: `${pct}%` }" />
    </div>
    <div class="meter-meta">
      <p>{{ progress.msg }}</p>
      <span v-if="pct > 0" class="mono">{{ pct }}%</span>
    </div>
    <p v-if="runStatus === 'running'" class="hint">
      <span class="dot" aria-hidden="true" />
      {{ props.runningHint || t("common.running_hint") }}
    </p>

    <slot name="after" />
  </section>
</template>

<style scoped>
.run-panel {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  gap: 12px;
  padding: 14px 16px 16px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--raised);
}

.run-panel.is-error {
  border-color: rgba(248, 113, 113, 0.35);
}

.run-panel.is-done {
  border-color: rgba(52, 211, 153, 0.28);
}

.fail-banner {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(248, 113, 113, 0.1);
  color: var(--err);
}

.fail-banner p {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.head h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

.is-done .head h2 { color: var(--ok); }
.is-error .head h2 { color: var(--err); }
.is-canceled .head h2 { color: var(--text-muted); }
.is-running .head h2 { color: var(--accent); }

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.meter {
  height: 6px;
  border-radius: 99px;
  overflow: hidden;
  background: var(--overlay);
}

.meter i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--accent-dim), var(--accent));
  transition: width 200ms ease;
}

.meter.live i {
  box-shadow: 0 0 12px var(--accent-glow-strong);
}

.meter.error i {
  background: var(--err);
  box-shadow: none;
}

.meter-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-muted);
  font-size: 12px;
}

.meter-meta p {
  margin: 0;
}

.is-error .meter-meta p {
  color: var(--err);
}

.hint {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--accent);
  font-size: 11px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 0 var(--accent-glow-strong);
  animation: live 1.4s ease-out infinite;
}

@keyframes live {
  0% { box-shadow: 0 0 0 0 var(--accent-glow-strong); }
  70% { box-shadow: 0 0 0 6px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}
</style>
