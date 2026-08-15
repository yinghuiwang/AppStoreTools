<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";

type BuildMode = "full" | "build" | "deploy";
type PhaseId = "archive" | "export" | "upload";
type PhaseState = "wait" | "running" | "done" | "error" | "canceled";

const PHASES: Record<BuildMode, PhaseId[]> = {
  full: ["archive", "export", "upload"],
  build: ["archive", "export"],
  deploy: ["upload"],
};

const PHASE_LABEL: Record<PhaseId, string> = {
  archive: "build.phase_archive",
  export: "build.phase_export",
  upload: "build.phase_upload",
};

const STATE_LABEL: Record<PhaseState, string> = {
  wait: "build.phase_state_wait",
  running: "build.phase_state_running",
  done: "build.phase_state_done",
  error: "build.phase_state_error",
  canceled: "build.phase_state_canceled",
};

const props = defineProps<{
  taskId: string;
  mode: BuildMode;
}>();

const emit = defineEmits<{ retry: [] }>();

const { t } = useI18n();
const rail = useRightRail();
const { status, progress, cancel, subscribe, logTaskId } = useTaskLog();
const canceling = ref(false);

watch(
  () => props.taskId,
  (id) => {
    canceling.value = false;
    if (id && logTaskId.value !== id) subscribe(id);
  },
  { immediate: true },
);

watch(status, (value) => {
  if (["done", "error", "canceled"].includes(value)) canceling.value = false;
});

const phaseIds = computed(() => PHASES[props.mode] || PHASES.full);

const runStatus = computed(() => {
  if (["done", "error", "canceled"].includes(status.value)) return status.value;
  return props.taskId ? "running" : "idle";
});

const currentIndex = computed(() => {
  const ids = phaseIds.value;
  const name = progress.value.phase;
  if (name) {
    const found = ids.indexOf(name as PhaseId);
    if (found >= 0) return found;
  }
  const idx = Number(progress.value.phase_index) || 0;
  if (idx >= 1 && idx <= ids.length) return idx - 1;
  return -1;
});

function stateOf(index: number): PhaseState {
  const st = runStatus.value;
  const cur = currentIndex.value;
  if (st === "done") return "done";
  if (st === "canceled") {
    if (index < cur) return "done";
    if (index === cur || cur < 0) return "canceled";
    return "wait";
  }
  if (st === "error") {
    const failAt = cur >= 0 ? cur : 0;
    if (index < failAt) return "done";
    if (index === failAt) return "error";
    return "wait";
  }
  if (cur < 0) return "wait";
  if (index < cur) return "done";
  if (index === cur) return "running";
  return "wait";
}

const stages = computed(() =>
  phaseIds.value.map((id, index) => {
    const state = stateOf(index);
    return {
      id,
      index,
      label: t(PHASE_LABEL[id]),
      state,
      stateLabel: t(STATE_LABEL[state]),
    };
  }),
);

const headline = computed(() => {
  if (runStatus.value === "done") return t("build.status_done");
  if (runStatus.value === "error") return t("build.status_error");
  if (runStatus.value === "canceled") return t("build.status_canceled");
  return t("build.status_running");
});

const pct = computed(() => {
  if (runStatus.value === "done") return 100;
  return Math.min(100, Math.max(0, Number(progress.value.pct) || 0));
});

const canCancel = computed(
  () => Boolean(props.taskId) && !["done", "error", "canceled"].includes(runStatus.value),
);

async function onCancel() {
  if (!canCancel.value || canceling.value) return;
  canceling.value = true;
  try {
    await cancel();
  } catch {
    canceling.value = false;
  }
}
</script>

<template>
  <section
    class="stage-panel"
    :class="`is-${runStatus}`"
    :aria-label="headline"
  >
    <div v-if="runStatus === 'error'" class="fail-banner" role="alert">
      <strong>{{ t("build.fail_banner_title") }}</strong>
      <p>{{ progress.msg || t("build.fail_banner_hint") }}</p>
    </div>

    <header class="head">
      <h2>{{ headline }}</h2>
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
        <el-button size="small" @click="emit('retry')">{{ t("build.retry") }}</el-button>
      </div>
    </header>

    <div class="stages" role="list">
      <template v-for="(stage, index) in stages" :key="stage.id">
        <div
          class="stage"
          role="listitem"
          :class="`is-${stage.state}`"
          :aria-current="stage.state === 'running' ? 'step' : undefined"
        >
          <span class="glyph" aria-hidden="true">
            <svg v-if="stage.state === 'running'" class="spin" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity="0.25" />
              <path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" opacity="0.85" />
            </svg>
            <svg v-else-if="stage.id === 'archive'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5m8.25 3v6.75m0 0-3-3m3 3 3-3M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" />
            </svg>
            <svg v-else-if="stage.id === 'export'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
            </svg>
          </span>
          <span class="copy">
            <span class="name">{{ stage.label }}</span>
            <span class="state">{{ stage.stateLabel }}</span>
          </span>
        </div>
        <span v-if="index < stages.length - 1" class="arrow" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
          </svg>
        </span>
      </template>
    </div>

    <div class="meter" :class="{ error: runStatus === 'error', live: runStatus === 'running' }">
      <i :style="{ width: `${pct}%` }" />
    </div>
    <div class="meter-meta">
      <p>{{ progress.msg }}</p>
      <span v-if="pct > 0" class="mono">{{ pct }}%</span>
    </div>
    <p v-if="runStatus === 'running'" class="hint">
      <span class="dot" aria-hidden="true" />
      {{ t("build.running_hint") }}
    </p>
  </section>
</template>

<style scoped>
.stage-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 6px;
  padding: 14px 16px 16px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--raised);
}

.stage-panel.is-error {
  border-color: rgba(248, 113, 113, 0.35);
}

.stage-panel.is-done {
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

.stages {
  display: flex;
  align-items: stretch;
  gap: 6px;
  margin: 0;
  padding: 8px;
  list-style: none;
  border-radius: 10px;
  background: var(--bg);
}

.stage {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 8px 10px;
  border-radius: 8px;
  color: var(--text-faint);
  transition: background-color 180ms ease, color 180ms ease, box-shadow 180ms ease;
}

.stage.is-running,
.stage.is-done {
  color: var(--accent);
  background: var(--accent-glow);
  box-shadow: inset 0 0 0 1px rgba(143, 245, 210, 0.22);
}

.stage.is-error {
  color: var(--err);
  background: rgba(248, 113, 113, 0.1);
  box-shadow: inset 0 0 0 1px rgba(248, 113, 113, 0.4);
}

.stage.is-canceled {
  color: var(--warn);
  background: rgba(245, 158, 11, 0.1);
}

.glyph {
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  background: var(--overlay);
}

.stage.is-running .glyph,
.stage.is-done .glyph {
  background: rgba(143, 245, 210, 0.16);
}

.stage.is-error .glyph {
  background: rgba(248, 113, 113, 0.18);
}

.glyph svg {
  width: 12px;
  height: 12px;
}

.copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 1px;
}

.name {
  font-size: 12px;
  font-weight: 650;
  color: inherit;
}

.state {
  font-size: 10px;
  letter-spacing: 0.04em;
  color: var(--text-muted);
}

.stage.is-running .state,
.stage.is-done .state {
  color: var(--accent-bright);
}

.stage.is-error .state {
  color: var(--err);
}

.arrow {
  display: grid;
  place-items: center;
  flex: 0 0 16px;
  color: var(--text-faint);
}

.arrow svg {
  width: 14px;
  height: 14px;
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

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes live {
  0% { box-shadow: 0 0 0 0 var(--accent-glow-strong); }
  70% { box-shadow: 0 0 0 6px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}

@media (max-width: 720px) {
  .stages {
    flex-direction: column;
  }
  .arrow {
    transform: rotate(90deg);
    height: 12px;
  }
}
</style>
