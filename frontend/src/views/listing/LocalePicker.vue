<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { httpJson } from "@/api/http";
import PageLoading from "@/components/PageLoading.vue";

type Row = { code: string; name_en: string; name_zh: string; present?: boolean };

const open = defineModel<boolean>("open", { default: false });
const { t, locale } = useI18n();
const query = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref<Row[]>([]);
const presenceAvailable = ref(false);
const copied = ref("");

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  const items = rows.value.filter((row) => {
    if (!q) return true;
    return [row.code, row.name_en, row.name_zh].some((v) => v.toLowerCase().includes(q));
  });
  return items.slice().sort((a, b) => a.code.localeCompare(b.code));
});

async function load() {
  loading.value = true;
  error.value = "";
  presenceAvailable.value = false;
  try {
    const data = await httpJson<{ locales: Row[] }>("/api/metadata/locales");
    rows.value = data.locales || [];
    try {
      const presence = await httpJson<{ codes: string[]; presenceAvailable: boolean }>(
        "/api/metadata/locales/presence",
      );
      presenceAvailable.value = presence.presenceAvailable === true;
      const codes = new Set(presence.codes || []);
      if (presenceAvailable.value) {
        rows.value = rows.value.map((row) => ({ ...row, present: codes.has(row.code) }));
      }
    } catch {
      presenceAvailable.value = false;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : t("metadata.locales_catalog_unavailable");
  } finally {
    loading.value = false;
  }
}

async function copy(code: string) {
  try {
    await navigator.clipboard.writeText(code);
    copied.value = code;
  } catch {
    copied.value = "";
  }
}

onMounted(() => { void load(); });
</script>

<template>
  <el-dialog v-model="open" :title="t('metadata.locales_title')" width="560px">
    <p class="hint">{{ t("metadata.locales_hint") }}</p>
    <p v-if="!presenceAvailable" class="hint">{{ t("metadata.locales_presence_unavailable") }}</p>
    <div class="field-row">
      <input v-model="query" class="field-input" :placeholder="t('metadata.locales_search')" />
      <el-button
        :loading="loading && rows.length > 0"
        :disabled="loading && !rows.length"
        @click="load"
      >{{ t("metadata.locales_refresh") }}</el-button>
    </div>
    <PageLoading v-if="loading && !rows.length" size="block" />
    <p v-else-if="error" class="err">{{ error }}</p>
    <ul v-else class="list">
      <li v-for="row in filtered" :key="row.code" @click="copy(row.code)">
        <strong class="mono">{{ row.code }}</strong>
        <span>{{ locale.startsWith("zh") ? row.name_zh : row.name_en }}</span>
        <em v-if="presenceAvailable && row.present">{{ t("metadata.locales_present") }}</em>
        <em v-if="copied === row.code">{{ t("metadata.locales_copied") }}</em>
      </li>
      <li v-if="!filtered.length">{{ t("metadata.locales_empty") }}</li>
    </ul>
  </el-dialog>
</template>

<style scoped>
.hint { color: var(--text-muted); font-size: 12px; }
.err { color: var(--err); }
.list { list-style: none; padding: 0; margin: 12px 0 0; max-height: 360px; overflow: auto; }
.list li { display: flex; gap: 10px; padding: 8px; border-bottom: 1px solid var(--border); cursor: pointer; }
.list li:hover { background: var(--raised); }
em { font-style: normal; color: var(--accent); font-size: 11px; }
</style>
