<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { GlobalConfigProvider } from "tdesign-vue-next";
import enUS from "tdesign-vue-next/es/locale/en_US";
import zhCN from "tdesign-vue-next/es/locale/zh_CN";
import AppShell from "@/layouts/AppShell.vue";

const { locale } = useI18n();
const tdLocale = computed(
  () => (locale.value === "zh" ? zhCN : enUS) as unknown as GlobalConfigProvider,
);
</script>

<template>
  <t-config-provider :global-config="tdLocale">
    <AppShell />
  </t-config-provider>
</template>
