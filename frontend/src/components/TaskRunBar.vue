<script setup lang="ts">
import { useRightRail } from "@/composables/useRightRail";
import { useTaskLog } from "@/composables/useTaskLog";

const props = defineProps<{ taskId: string }>();
const rail = useRightRail();
const { status, progress, cancel } = useTaskLog();
</script>

<template>
  <div v-if="props.taskId" class="run-bar">
    <span>{{ status }} {{ progress.msg }}</span>
    <el-button size="small" @click="rail.openLogs(props.taskId)">{{ $t("index.log") }}</el-button>
    <el-button size="small" @click="cancel()">{{ $t("index.cancel") }}</el-button>
  </div>
</template>

<style scoped>
.run-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--raised);
  font-size: 12px;
  color: var(--text-muted);
}
</style>
