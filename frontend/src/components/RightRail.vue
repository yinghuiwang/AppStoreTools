<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRightRail } from "@/composables/useRightRail";
import TaskLogPanel from "@/components/TaskLogPanel.vue";

const { t } = useI18n();
const { open, tab, width, collapse, openAgent, persistChrome, setWidth } = useRightRail();
const narrow = ref(false);

function onResize() {
  narrow.value = window.innerWidth < 1100;
}

function toggleAgent() {
  if (open.value && tab.value === "agent") {
    collapse();
    return;
  }
  openAgent();
}

function toggleLogs() {
  if (open.value && tab.value === "logs") {
    collapse();
    return;
  }
  tab.value = "logs";
  open.value = true;
  persistChrome();
}

function onPointerDown(event: PointerEvent) {
  const startX = event.clientX;
  const startW = width.value;
  function onMove(ev: PointerEvent) {
    setWidth(startW + (startX - ev.clientX));
  }
  function onUp() {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
  }
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}

const overlay = computed(() => narrow.value && open.value);

onMounted(() => {
  onResize();
  window.addEventListener("resize", onResize);
});
onBeforeUnmount(() => {
  window.removeEventListener("resize", onResize);
});
</script>

<template>
  <div class="rail" :class="{ overlay }">
    <section
      v-show="open"
      class="panel"
      data-right-rail-panel
      :style="{ width: `${width}px` }"
    >
      <button
        type="button"
        class="resize"
        :aria-label="t('agent.resize')"
        @pointerdown="onPointerDown"
      />
      <div v-show="tab === 'agent'" class="pane" data-agent-panel>
        <slot name="agent" />
      </div>
      <div v-show="tab === 'logs'" class="pane">
        <TaskLogPanel />
      </div>
    </section>
    <aside class="strip" data-agent-rail>
      <button
        type="button"
        class="icon-btn"
        data-agent-toggle
        :aria-pressed="open && tab === 'agent' ? 'true' : 'false'"
        :title="t('rail.tab.agent')"
        :aria-label="t('rail.tab.agent')"
        @click="toggleAgent"
      >
        <svg fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
        </svg>
      </button>
      <button
        type="button"
        class="icon-btn"
        data-rail-logs-toggle
        :aria-pressed="open && tab === 'logs' ? 'true' : 'false'"
        :title="t('rail.tab.logs')"
        :aria-label="t('rail.tab.logs')"
        @click="toggleLogs"
      >
        <svg fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" />
        </svg>
      </button>
    </aside>
  </div>
</template>

<style scoped>
.rail {
  display: flex;
  height: 100vh;
  flex: 0 0 auto;
  position: relative;
  z-index: 30;
}

.rail.overlay .panel {
  position: absolute;
  right: var(--rail-strip);
  top: 0;
  bottom: 0;
  z-index: 35;
  box-shadow: -16px 0 40px rgba(0, 0, 0, 0.45);
}

.strip {
  flex: 0 0 var(--rail-strip);
  width: var(--rail-strip);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px 0;
  background: var(--surface);
  border-left: 1px solid var(--border);
}

.icon-btn {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.icon-btn svg {
  width: 18px;
  height: 18px;
}

.icon-btn[aria-pressed="true"] {
  background: var(--accent-glow);
  color: var(--accent);
}

.panel {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0c0c10;
  border-left: 1px solid var(--border);
  min-width: 0;
}

.resize {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  z-index: 20;
  width: 8px;
  border: 0;
  padding: 0;
  cursor: col-resize;
  background: transparent;
}

.pane {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
