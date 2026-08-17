<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { LoadingIcon } from "tdesign-icons-vue-next";

const props = withDefaults(
  defineProps<{
    /** Override default `common.loading` label. */
    text?: string;
    /** page: reserved for rare full-region placeholders; prefer block/inline in business UI. */
    size?: "page" | "block" | "inline";
  }>(),
  { size: "block" },
);

const { t } = useI18n();
const label = computed(() => props.text || t("common.loading"));
const iconSize = computed(() => (props.size === "inline" ? "14px" : "18px"));
</script>

<template>
  <div
    class="page-loading"
    :class="`is-${size}`"
    role="status"
    :aria-busy="true"
    :aria-label="label"
  >
    <LoadingIcon class="page-loading__icon" :size="iconSize" />
    <span class="page-loading__text">{{ label }}</span>
  </div>
</template>

<style scoped>
.page-loading {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.4;
}

.page-loading.is-page {
  justify-content: center;
  min-height: 72px;
  padding: 16px 8px;
}

.page-loading.is-block {
  padding: 10px 2px;
}

.page-loading.is-inline {
  display: inline-flex;
  gap: 6px;
  padding: 0;
  font-size: 12px;
}

.page-loading__icon {
  color: var(--accent-dim);
  animation: page-loading-spin 0.85s linear infinite;
}

.page-loading__text {
  letter-spacing: 0.01em;
}

@keyframes page-loading-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
