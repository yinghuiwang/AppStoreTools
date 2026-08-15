<script setup lang="ts">
import { onMounted } from "vue";
import AppSidebar from "@/components/AppSidebar.vue";
import AppTopbar from "@/components/AppTopbar.vue";
import RightRail from "@/components/RightRail.vue";
import FileBrowser from "@/components/FileBrowser.vue";
import ImageViewer from "@/components/ImageViewer.vue";
import { useProfile } from "@/composables/useProfile";
import { useTaskLog } from "@/composables/useTaskLog";
import { useAgent } from "@/composables/useAgent";

const { snapshot } = useProfile();

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
        <router-view :key="snapshot?.current_profile ?? ''" />
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
  flex: 1;
  overflow: auto;
  padding: 24px 28px 40px;
}
</style>
