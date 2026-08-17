<script setup lang="ts">
import { computed, onActivated, onMounted, provide, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  DEFAULT_LISTING_TAB,
  LISTING_TABS,
  useListingTab,
} from "@/composables/useTaskPagePhase";
import LocalTab from "./listing/LocalTab.vue";
import DiffTab from "./listing/DiffTab.vue";
import UploadTab from "./listing/UploadTab.vue";

defineOptions({ name: "ListingView" });

const route = useRoute();
const router = useRouter();
const reloadTick = ref(0);
provide("listingReload", reloadTick);
const { listingTab, setListingTab } = useListingTab();

const tab = computed({
  get() {
    const raw = String(route.query.tab || "");
    if (LISTING_TABS.has(raw)) return raw;
    return LISTING_TABS.has(listingTab.value) ? listingTab.value : DEFAULT_LISTING_TAB;
  },
  set(value: string) {
    const next = LISTING_TABS.has(value) ? value : DEFAULT_LISTING_TAB;
    setListingTab(next);
    void router.replace({ query: { ...route.query, tab: next } });
  },
});

function syncTabFromRoute() {
  const action = String(route.query.action || "");
  if (["check", "all", "metadata", "screenshots"].includes(action)) {
    tab.value = "upload";
    return;
  }
  const raw = String(route.query.tab || "");
  if (LISTING_TABS.has(raw)) {
    if (raw !== listingTab.value) setListingTab(raw);
    return;
  }
  void router.replace({ query: { ...route.query, tab: listingTab.value } });
}

onMounted(() => {
  syncTabFromRoute();
});

onActivated(() => {
  syncTabFromRoute();
});
</script>

<template>
  <el-tabs v-model="tab">
    <el-tab-pane :label="$t('listing.tab.upload')" name="upload"><UploadTab /></el-tab-pane>
    <el-tab-pane :label="$t('listing.tab.local')" name="local"><LocalTab /></el-tab-pane>
    <el-tab-pane :label="$t('listing.tab.diff')" name="diff"><DiffTab /></el-tab-pane>
  </el-tabs>
</template>
