<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import LocalTab from "./listing/LocalTab.vue";

const TABS = new Set(["local", "diff", "upload"]);
const route = useRoute();
const router = useRouter();
const tab = computed({
  get() {
    const raw = String(route.query.tab || "local");
    return TABS.has(raw) ? raw : "local";
  },
  set(value: string) {
    void router.replace({ query: { ...route.query, tab: value } });
  },
});

onMounted(() => {
  const action = String(route.query.action || "");
  if (["check", "all", "metadata", "screenshots"].includes(action)) {
    void router.replace({ query: { ...route.query, tab: "upload" } });
  }
  if (!TABS.has(String(route.query.tab || "local"))) {
    void router.replace({ query: { ...route.query, tab: "local" } });
  }
});
</script>

<template>
  <el-tabs v-model="tab">
    <el-tab-pane :label="$t('listing.tab.local')" name="local"><LocalTab /></el-tab-pane>
    <el-tab-pane :label="$t('listing.tab.diff')" name="diff"><div /></el-tab-pane>
    <el-tab-pane :label="$t('listing.tab.upload')" name="upload"><div /></el-tab-pane>
  </el-tabs>
</template>
