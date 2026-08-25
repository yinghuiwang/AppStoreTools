<script setup lang="ts">
import { onMounted, watch } from "vue";
import AppSidebar from "@/components/AppSidebar.vue";
import AppTopbar from "@/components/AppTopbar.vue";
import RightRail from "@/components/RightRail.vue";
import FileBrowser from "@/components/FileBrowser.vue";
import ImageViewer from "@/components/ImageViewer.vue";
import { useProfile } from "@/composables/useProfile";
import { useTaskLog } from "@/composables/useTaskLog";
import { useAgent } from "@/composables/useAgent";
import { bindTaskPageProfile, TASK_KEEP_ALIVE_NAMES } from "@/composables/useTaskPagePhase";

const { snapshot } = useProfile();

watch(
  () => snapshot.value?.current_profile ?? "",
  (profile) => bindTaskPageProfile(profile),
  { immediate: true },
);

onMounted(() => {
  window.addEventListener("pagehide", () => {
    useTaskLog().disconnect();
    void useAgent().stop();
  });
});
</script>

<template>
  <div class="shell">
    <AppSidebar />
    <div class="shell-col">
      <AppTopbar />
      <main class="shell-main">
        <router-view v-slot="{ Component }">
          <!-- Cache task form pages only. Dashboard / system pages remount so watches and images drop. -->
          <!-- Profile key recreates the cache when the App changes. -->
          <keep-alive :include="TASK_KEEP_ALIVE_NAMES" :key="snapshot?.current_profile ?? ''">
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </main>
    </div>
    <RightRail />
    <FileBrowser />
    <ImageViewer />
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  width: 100%;
  height: 100vh;
  overflow: hidden;
  background: var(--bg);
}

.shell-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.shell-main {
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 0;
  width: 100%;
  overflow: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
}
</style>
