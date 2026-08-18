<script setup lang="ts">
import { computed, onMounted, onUnmounted } from "vue";
import { useImageViewer } from "@/composables/useImageViewer";

const { open, items, index, transform, close, next, prev, resetTransform } = useImageViewer();
const current = computed(() => items.value[index.value]);
const style = computed(() => {
  const t = transform.value;
  const flip = `scale(${t.flipX ? -1 : 1}, ${t.flipY ? -1 : 1})`;
  return {
    transform: `translate(${t.x}px, ${t.y}px) rotate(${t.rotate}deg) scale(${t.scale}) ${flip}`,
  };
});

let dragging = false;
let lastX = 0;
let lastY = 0;

function onKey(event: KeyboardEvent) {
  if (!open.value) return;
  if (event.key === "Escape") close();
  if (event.key === "ArrowRight") next();
  if (event.key === "ArrowLeft") prev();
}

function onWheel(event: WheelEvent) {
  if (!open.value) return;
  event.preventDefault();
  const nextScale = transform.value.scale + (event.deltaY < 0 ? 0.12 : -0.12);
  transform.value = { ...transform.value, scale: Math.min(5, Math.max(0.2, nextScale)) };
}

function onDown(event: PointerEvent) {
  dragging = true;
  lastX = event.clientX;
  lastY = event.clientY;
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}

function onMove(event: PointerEvent) {
  if (!dragging) return;
  transform.value = {
    ...transform.value,
    x: transform.value.x + event.clientX - lastX,
    y: transform.value.y + event.clientY - lastY,
  };
  lastX = event.clientX;
  lastY = event.clientY;
}

function onUp() { dragging = false; }

function download() {
  const item = current.value;
  if (!item?.src) return;
  const link = document.createElement("a");
  link.href = item.src;
  link.download = item.title || "screenshot";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <div v-if="open" class="viewer" @click.self="close" @wheel.prevent="onWheel">
    <div class="toolbar">
      <span>{{ current?.title }} ({{ index + 1 }}/{{ items.length }})</span>
      <div>
        <button type="button" @click="transform.scale += 0.2">+</button>
        <button type="button" @click="transform.scale = Math.max(0.2, transform.scale - 0.2)">−</button>
        <button type="button" @click="transform.rotate += 90">⟳</button>
        <button type="button" @click="transform.flipX = !transform.flipX">↔</button>
        <button type="button" @click="transform.flipY = !transform.flipY">↕</button>
        <button type="button" @click="resetTransform">reset</button>
        <button type="button" @click="download">{{ $t("metadata.shots_lightbox_download") }}</button>
        <button type="button" @click="prev">←</button>
        <button type="button" @click="next">→</button>
        <button type="button" @click="close">{{ $t("metadata.shots_lightbox_close") }}</button>
      </div>
    </div>
    <img
      v-if="current"
      :src="current.src"
      :alt="current.title"
      :style="style"
      @pointerdown="onDown"
      @pointermove="onMove"
      @pointerup="onUp"
    />
  </div>
</template>

<style scoped>
.viewer {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(6, 6, 8, 0.88);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.toolbar {
  position: absolute;
  top: 16px;
  left: 16px;
  right: 16px;
  display: flex;
  justify-content: space-between;
  color: var(--text);
  z-index: 1;
}
.toolbar button {
  margin-left: 6px;
  background: var(--overlay);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 8px;
}
img {
  max-width: 88vw;
  max-height: 82vh;
  cursor: grab;
  user-select: none;
}
</style>
