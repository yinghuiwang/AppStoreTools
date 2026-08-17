<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { httpJson } from "@/api/http";
import PageLoading from "@/components/PageLoading.vue";

type LlmItem = { base_url: string; model: string; has_api_key: boolean };
type Provider = { enabled: boolean; url: string; secret: string; has_secret?: boolean };
type WebhookConfig = {
  enabled: boolean;
  notify_kinds: string[];
  notify_statuses: string[];
  providers: Record<string, Provider>;
};

const { t } = useI18n();
const configs = ref<Record<string, LlmItem>>({});
const defaultName = ref("");
const showForm = ref(false);
const isEditing = ref(false);
const llmForm = reactive({ name: "", base_url: "https://api.openai.com/v1", api_key: "", model: "gpt-4o" });
const llmError = ref("");
const webhook = reactive<WebhookConfig>({
  enabled: false,
  notify_kinds: [],
  notify_statuses: [],
  providers: {
    feishu: { enabled: false, url: "", secret: "" },
    wecom: { enabled: false, url: "", secret: "" },
    dingtalk: { enabled: false, url: "", secret: "" },
  },
});
const webhookError = ref("");
const testResults = ref<{ provider: string; ok: boolean; error?: string }[]>([]);
const loading = ref(true);
const loaded = ref(false);
const kinds = [
  ["metadata", "settings.task_metadata"],
  ["build", "settings.task_build"],
  ["whats-new", "settings.task_whats_new"],
  ["iap", "settings.task_iap_alt"],
  ["iap-review-screenshots", "settings.task_iap_review"],
  ["urls", "settings.task_urls_alt"],
  ["update", "settings.task_update"],
];
const statuses = [
  ["done", "settings.status_done"],
  ["error", "settings.status_error"],
  ["canceled", "settings.status_canceled"],
];
const providers = [
  ["feishu", "settings.provider_feishu"],
  ["wecom", "settings.provider_wecom"],
  ["dingtalk", "settings.provider_dingtalk"],
];

async function loadLlm() {
  const data = await httpJson<{ configs: Record<string, LlmItem>; default: string }>("/api/settings/llm");
  configs.value = data.configs || {};
  defaultName.value = data.default || "";
}

function openCreate() {
  isEditing.value = false;
  Object.assign(llmForm, { name: "", base_url: "https://api.openai.com/v1", api_key: "", model: "gpt-4o" });
  llmError.value = "";
  showForm.value = true;
}

function openEdit(name: string) {
  const cfg = configs.value[name];
  isEditing.value = true;
  Object.assign(llmForm, { name, base_url: cfg.base_url, api_key: "", model: cfg.model });
  llmError.value = "";
  showForm.value = true;
}

async function saveLlm() {
  llmError.value = "";
  const name = isEditing.value
    ? llmForm.name
    : llmForm.name || `config${Object.keys(configs.value).length + 1}`;
  try {
    await httpJson("/api/settings/llm", {
      method: "POST",
      body: JSON.stringify({
        name,
        base_url: llmForm.base_url,
        api_key: llmForm.api_key,
        model: llmForm.model,
        set_default: true,
      }),
    });
    showForm.value = false;
    await loadLlm();
  } catch {
    llmError.value = t("settings.save_failed");
  }
}

async function deleteLlm(name: string) {
  await httpJson(`/api/settings/llm?name=${encodeURIComponent(name)}`, { method: "DELETE" });
  await loadLlm();
}

async function setDefault(name: string) {
  await httpJson("/api/settings/llm/default", { method: "POST", body: JSON.stringify({ name }) });
  await loadLlm();
}

function applyWebhook(data: Partial<WebhookConfig>) {
  webhook.enabled = Boolean(data.enabled);
  webhook.notify_kinds = [...(data.notify_kinds || [])];
  webhook.notify_statuses = [...(data.notify_statuses || [])];
  for (const key of ["feishu", "wecom", "dingtalk"]) {
    webhook.providers[key] = {
      enabled: Boolean(data.providers?.[key]?.enabled),
      url: data.providers?.[key]?.url || "",
      secret: "",
      has_secret: Boolean(data.providers?.[key]?.has_secret),
    };
  }
}

async function loadWebhook() {
  applyWebhook(await httpJson<WebhookConfig>("/api/settings/webhooks"));
}

function toggle(list: "notify_kinds" | "notify_statuses", value: string, checked: boolean) {
  const cur = webhook[list];
  webhook[list] = checked ? Array.from(new Set([...cur, value])) : cur.filter((item) => item !== value);
}

async function saveWebhook() {
  webhookError.value = "";
  const body = {
    enabled: webhook.enabled,
    notify_kinds: webhook.notify_kinds,
    notify_statuses: webhook.notify_statuses,
    providers: {
      feishu: { ...webhook.providers.feishu },
      wecom: { ...webhook.providers.wecom },
      dingtalk: { ...webhook.providers.dingtalk },
    },
  };
  await httpJson("/api/settings/webhooks", { method: "POST", body: JSON.stringify(body) });
  await loadWebhook();
}

async function testProvider(provider: string) {
  await saveWebhook();
  const data = await httpJson<{ results?: { provider: string; ok: boolean; error?: string }[] }>(
    "/api/settings/webhooks/test",
    { method: "POST", body: JSON.stringify({ provider }) },
  );
  testResults.value = data.results || [];
}

onMounted(async () => {
  if (!loaded.value) loading.value = true;
  try {
    await Promise.all([loadLlm(), loadWebhook()]);
    loaded.value = true;
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="page-stack">
    <div class="card">
      <div class="toolbar">
        <h2>{{ t("settings.llm_title") }}</h2>
        <el-button :disabled="loading" @click="openCreate">{{ t("settings.add_config") }}</el-button>
      </div>
      <PageLoading v-if="loading && !loaded" size="block" />
      <template v-else>
      <div v-if="showForm" class="form-box">
        <p>{{ isEditing ? t("settings.edit_config") : t("settings.new_config") }}</p>
        <label class="field">
          <span>{{ t("settings.config_name") }}</span>
          <input v-model="llmForm.name" class="field-input" :disabled="isEditing" :placeholder="t('settings.config_name_ph')" />
        </label>
        <label class="field"><span>Base URL</span><input v-model="llmForm.base_url" class="field-input" /></label>
        <label class="field"><span>API Key</span><input v-model="llmForm.api_key" type="password" class="field-input" placeholder="sk-..." /></label>
        <label class="field"><span>Model</span><input v-model="llmForm.model" class="field-input" /></label>
        <p v-if="llmError" class="err">{{ llmError }}</p>
        <div class="field-row">
          <el-button type="primary" @click="saveLlm">{{ t("common.save") }}</el-button>
          <el-button @click="showForm = false">{{ t("common.cancel") }}</el-button>
        </div>
      </div>
      <p v-if="!Object.keys(configs).length" class="empty-state">{{ t("settings.empty_configs") }}</p>
      <div v-for="(cfg, name) in configs" :key="name" class="llm-row">
        <div>
          <strong>{{ name }}</strong>
          <span v-if="name === defaultName" class="badge">{{ t("common.default") }}</span>
          <div class="muted">{{ cfg.base_url }} / {{ cfg.model }}</div>
        </div>
        <div class="field-row">
          <el-button v-if="name !== defaultName" size="small" @click="setDefault(String(name))">{{ t("common.set_default") }}</el-button>
          <el-button size="small" @click="openEdit(String(name))">{{ t("common.edit") }}</el-button>
          <el-button size="small" @click="deleteLlm(String(name))">{{ t("common.delete") }}</el-button>
        </div>
      </div>
      </template>
    </div>

    <div class="card">
      <div class="toolbar">
        <h2>{{ t("settings.webhook_title") }}</h2>
        <el-button type="primary" :disabled="loading" @click="saveWebhook">{{ t("common.save") }}</el-button>
      </div>
      <PageLoading v-if="loading && !loaded" size="block" />
      <template v-else>
      <p v-if="webhookError" class="err">{{ webhookError }}</p>
      <label class="check"><input v-model="webhook.enabled" type="checkbox" /> {{ t("settings.webhook_enable") }}</label>
      <div class="split">
        <div>
          <h3>{{ t("settings.webhook_tasks") }}</h3>
          <label v-for="[id, key] in kinds" :key="id" class="check">
            <input
              type="checkbox"
              :checked="webhook.notify_kinds.includes(id)"
              @change="toggle('notify_kinds', id, ($event.target as HTMLInputElement).checked)"
            />
            {{ t(key) }}
          </label>
        </div>
        <div>
          <h3>{{ t("settings.webhook_status") }}</h3>
          <label v-for="[id, key] in statuses" :key="id" class="check">
            <input
              type="checkbox"
              :checked="webhook.notify_statuses.includes(id)"
              @change="toggle('notify_statuses', id, ($event.target as HTMLInputElement).checked)"
            />
            {{ t(key) }}
          </label>
        </div>
      </div>
      <div v-for="[id, key] in providers" :key="id" class="provider">
        <label class="check">
          <input v-model="webhook.providers[id].enabled" type="checkbox" />
          {{ t(key) }}
        </label>
        <label class="field"><span>URL</span><input v-model="webhook.providers[id].url" class="field-input" /></label>
        <label class="field">
          <span>{{ t("settings.secret_ph") }}</span>
          <input v-model="webhook.providers[id].secret" type="password" class="field-input" :placeholder="webhook.providers[id].has_secret ? t('settings.secret_kept') : ''" />
        </label>
        <el-button size="small" @click="testProvider(id)">{{ t("settings.save_test") }}</el-button>
      </div>
      <ul v-if="testResults.length" class="results">
        <li v-for="row in testResults" :key="row.provider">{{ row.provider }}: {{ row.ok ? t("settings.test_ok") : (row.error || t("settings.test_failed")) }}</li>
      </ul>
      </template>
    </div>
  </div>
</template>

<style scoped>
.card { display: flex; flex-direction: column; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
h2, h3 { margin: 0 0 8px; font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-muted); }
.form-box, .provider, .llm-row { border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin: 10px 0; display: flex; flex-direction: column; gap: 8px; }
.llm-row { flex-direction: row; justify-content: space-between; align-items: center; }
.muted { color: var(--text-muted); font-size: 12px; }
.err { color: var(--err); }
.badge { margin-left: 8px; font-size: 10px; color: var(--accent); }
.check { display: flex; gap: 8px; align-items: center; font-size: 13px; margin: 4px 0; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 12px 0; }
.results { color: var(--text-muted); font-size: 12px; }
@media (max-width: 1100px) { .split, .llm-row { grid-template-columns: 1fr; flex-direction: column; } }
</style>
