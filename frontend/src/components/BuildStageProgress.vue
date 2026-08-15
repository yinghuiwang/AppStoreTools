<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import TaskRunBar from "@/components/TaskRunBar.vue";
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

const emit = defineEmits<{ back: [] }>();

const { t } = useI18n();
const { status, progress } = useTaskLog();

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
</script>

<template>
  <TaskRunBar
    :task-id="props.taskId"
    :headline="headline"
    :fail-title="t('build.fail_banner_title')"
    :fail-hint="t('build.fail_banner_hint')"
    :running-hint="t('build.running_hint')"
    @back="emit('back')"
  >
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
  </TaskRunBar>
</template>

<style scoped>
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

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
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
