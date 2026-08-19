<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { LoadingIcon } from "tdesign-icons-vue-next";

const props = withDefaults(
  defineProps<{
    /** Override default `common.loading` label. */
    text?: string;
    /** page: in-route placeholder; stay in-tree so keep-alive hide also hides it. */
    size?: "page" | "block" | "inline";
  }>(),
  { size: "block" },
);

const { t } = useI18n();
const label = computed(() => props.text || t("common.loading"));
const iconSize = computed(() => {
  if (props.size === "inline") return "14px";
  if (props.size === "page") return "22px";
  return "18px";
});
const logoSrc = "/static/logo.svg";
</script>

<template>
  <div
    class="page-loading"
    :class="`is-${size}`"
    role="status"
    :aria-busy="true"
    :aria-label="label"
  >
    <img
      v-if="size === 'page'"
      class="page-loading__logo"
      :src="logoSrc"
      alt=""
      width="56"
      height="56"
    />
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
  flex: 1 1 auto;
  align-self: stretch;
  min-height: min(52vh, 360px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin: 0;
  padding: 24px 0;
  color: var(--text-muted);
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

.page-loading__logo {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  box-shadow:
    0 0 0 1px var(--border),
    0 10px 36px var(--accent-glow);
}

.page-loading__icon {
  color: var(--accent-dim);
  animation: page-loading-spin 0.85s linear infinite;
}

.page-loading.is-page .page-loading__text {
  letter-spacing: 0.02em;
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
