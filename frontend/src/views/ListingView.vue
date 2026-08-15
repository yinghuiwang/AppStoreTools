<script setup lang="ts">
import { computed, onMounted, provide, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import LocalTab from "./listing/LocalTab.vue";
import DiffTab from "./listing/DiffTab.vue";
import UploadTab from "./listing/UploadTab.vue";

const TABS = new Set(["local", "diff", "upload"]);
const route = useRoute();
const router = useRouter();
const reloadTick = ref(0);
provide("listingReload", reloadTick);
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
    <el-tab-pane :label="$t('listing.tab.diff')" name="diff"><DiffTab /></el-tab-pane>
    <el-tab-pane :label="$t('listing.tab.upload')" name="upload"><UploadTab /></el-tab-pane>
  </el-tabs>
</template>
