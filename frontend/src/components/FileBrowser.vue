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
  <t-dialog
    :visible="open"
    :header="t('filebrowser.title')"
    width="520px"
    attach="body"
    placement="center"
    @update:visible="onClosed"
  >
    <p class="path mono">{{ currentPath }}</p>
    <p v-if="error" class="err">{{ error }}</p>
    <PageLoading v-if="loading" size="block" />
    <ul v-else class="list">
      <li v-for="entry in entries" :key="entry.path">
        <t-button variant="text" block @click="enter(entry)">
          <span class="kind">{{ entry.is_dir ? "dir" : "file" }}</span>
          {{ entry.name }}
        </t-button>
      </li>
    </ul>
    <t-empty v-if="!loading && !entries.length && !error" :description="t('filebrowser.empty')" />
    <template #footer>
      <t-button @click="cancel()">{{ t("filebrowser.cancel") }}</t-button>
      <t-button
        v-if="mode === 'dir'"
        theme="primary"
        :disabled="loading"
        @click="choose(currentPath)"
      >
        {{ t("filebrowser.select_dir") }}
      </t-button>
    </template>
  </t-dialog>
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

.list :deep(.t-button) {
  justify-content: flex-start;
  width: 100%;
  gap: 10px;
  border-bottom: 1px solid var(--border);
  border-radius: 0;
  padding: 8px 10px;
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
