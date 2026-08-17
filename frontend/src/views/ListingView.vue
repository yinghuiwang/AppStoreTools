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
  <t-tabs class="listing-tabs" v-model="tab">
    <t-tab-panel :label="$t('listing.tab.upload')" value="upload" :destroy-on-hide="false"><UploadTab /></t-tab-panel>
    <t-tab-panel :label="$t('listing.tab.local')" value="local" :destroy-on-hide="false"><LocalTab /></t-tab-panel>
    <t-tab-panel :label="$t('listing.tab.diff')" value="diff" :destroy-on-hide="false"><DiffTab /></t-tab-panel>
  </t-tabs>
</template>

<style scoped>
.listing-tabs {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  overflow: visible;
  background: transparent;
}
.listing-tabs :deep(.t-tabs__header) {
  flex: 0 0 auto;
}
.listing-tabs :deep(.t-tabs__content) {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  overflow: visible;
  background: transparent;
}
.listing-tabs :deep(.t-tab-panel) {
  flex: 1 1 auto;
  overflow: visible;
  background: transparent;
}
</style>
