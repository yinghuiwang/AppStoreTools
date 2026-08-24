<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { reviewShotThumbUrl, useIapWorkflow } from "@/composables/useIapWorkflow";
import { useImageViewer } from "@/composables/useImageViewer";

const props = withDefaults(defineProps<{
  path?: string;
  size?: "row" | "field";
}>(), {
  path: "",
  size: "row",
});

const { t } = useI18n();
const workflow = useIapWorkflow();
const viewer = useImageViewer();
const failed = ref(false);

const shot = computed(() => (props.path || "").trim());
const src = computed(() => (
  shot.value ? reviewShotThumbUrl(shot.value, workflow.iapFile.value) : ""
));

watch(src, () => {
  failed.value = false;
});

function preview(event: Event) {
  event.stopPropagation();
  if (!src.value || failed.value) return;
  viewer.show([{ src: src.value, title: shot.value }]);
}

function onError() {
  failed.value = true;
}
</script>

<template>
  <button
    v-if="src && !failed"
    type="button"
    class="iap-thumb"
    :class="size"
    :title="shot"
    :aria-label="t('iap.review_shot')"
    @click="preview"
  >
    <img :src="src" alt="" @error="onError" />
  </button>
  <span
    v-else
    class="iap-thumb-empty"
    :class="size"
    :title="t('iap.status.missing-shot')"
  >—</span>
</template>

<style scoped>
.iap-thumb {
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  background: var(--raised);
  cursor: zoom-in;
  flex: 0 0 auto;
}
.iap-thumb.row,
.iap-thumb-empty.row {
  width: 36px;
  height: 36px;
}
.iap-thumb.field,
.iap-thumb-empty.field {
  width: 48px;
  height: 48px;
}
.iap-thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.iap-thumb-empty {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--border);
  border-radius: 6px;
  color: var(--text-muted);
  font-size: 11px;
  background: var(--surface);
  flex: 0 0 auto;
}
</style>
