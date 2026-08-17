<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { Loading } from "@element-plus/icons-vue";

const props = withDefaults(
  defineProps<{
    /** Override default `common.loading` label. */
    text?: string;
    /** page: centered block; block: in-flow; inline: beside controls. */
    size?: "page" | "block" | "inline";
  }>(),
  { size: "block" },
);

const { t } = useI18n();
const label = computed(() => props.text || t("common.loading"));
const iconPx = computed(() => (props.size === "inline" ? 14 : 18));
</script>

<template>
  <div
    class="page-loading"
    :class="`is-${size}`"
    role="status"
    :aria-busy="true"
    :aria-label="label"
  >
    <el-icon class="page-loading__icon" :size="iconPx">
      <Loading />
    </el-icon>
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
  min-height: 160px;
  padding: 28px 8px;
}

.page-loading.is-block {
  padding: 16px 4px;
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
