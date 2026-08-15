<script setup lang="ts">
import AppSidebar from "@/components/AppSidebar.vue";
import AppTopbar from "@/components/AppTopbar.vue";
import { useProfile } from "@/composables/useProfile";

const { snapshot } = useProfile();
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
    <div class="rail-slot" />
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

.rail-slot {
  width: var(--rail-strip);
  flex: 0 0 var(--rail-strip);
  background: var(--surface);
  border-left: 1px solid var(--border);
}
</style>
