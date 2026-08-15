<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import ProfilesTab from "./system/ProfilesTab.vue";
import GuardTab from "./system/GuardTab.vue";
import SettingsTab from "./system/SettingsTab.vue";
import UpdateTab from "./system/UpdateTab.vue";

const route = useRoute();
const router = useRouter();
const tab = computed({
  get: () => String(route.params.tab || "profiles"),
  set: (value: string) => { void router.push(`/system/${value}`); },
});
</script>

<template>
  <el-tabs v-model="tab">
    <el-tab-pane :label="$t('system.tab.profiles')" name="profiles"><ProfilesTab /></el-tab-pane>
    <el-tab-pane :label="$t('system.tab.guard')" name="guard"><GuardTab /></el-tab-pane>
    <el-tab-pane :label="$t('system.tab.settings')" name="settings"><SettingsTab /></el-tab-pane>
    <el-tab-pane :label="$t('system.tab.update')" name="update"><UpdateTab /></el-tab-pane>
  </el-tabs>
</template>
