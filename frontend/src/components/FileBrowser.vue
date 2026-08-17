<script setup lang="ts">
import { useI18n } from "vue-i18n";
import PageLoading from "@/components/PageLoading.vue";
import { useBrowse } from "@/composables/useBrowse";

const { t } = useI18n();
const { open, mode, currentPath, entries, error, loading, choose, cancel, enter } = useBrowse();

function onClosed(visible: boolean) {
  if (!visible && open.value) cancel();
}
</script>

<template>
  <el-dialog
    :model-value="open"
    :title="t('filebrowser.title')"
    width="520px"
    append-to-body
    @update:model-value="onClosed"
  >
    <p class="path mono">{{ currentPath }}</p>
    <p v-if="error" class="err">{{ error }}</p>
    <PageLoading v-if="loading" size="block" />
    <ul v-else class="list">
      <li v-for="entry in entries" :key="entry.path">
        <button type="button" @click="enter(entry)">
          <span class="kind">{{ entry.is_dir ? "dir" : "file" }}</span>
          {{ entry.name }}
        </button>
      </li>
    </ul>
    <p v-if="!loading && !entries.length && !error" class="empty">{{ t("filebrowser.empty") }}</p>
    <template #footer>
      <el-button @click="cancel()">{{ t("filebrowser.cancel") }}</el-button>
      <el-button
        v-if="mode === 'dir'"
        type="primary"
        :disabled="loading"
        @click="choose(currentPath)"
      >
        {{ t("filebrowser.select_dir") }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.path {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--text-muted);
  word-break: break-all;
}

.err {
  color: var(--err);
  font-size: 13px;
}

.list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 360px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
}

.list button {
  display: flex;
  width: 100%;
  gap: 10px;
  align-items: center;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  padding: 8px 10px;
  text-align: left;
  cursor: pointer;
}

.kind {
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent-dim);
  width: 32px;
}

.empty {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
