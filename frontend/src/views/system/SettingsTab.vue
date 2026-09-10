<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import PageLoading from "@/components/PageLoading.vue";

type LlmItem = { base_url: string; model: string; has_api_key: boolean };
type LlmPreset = {
  id: string;
  name: string;
  base_url: string;
  api_style: string;
  models: string[];
  default_model: string;
  api_key_optional: boolean;
  custom: boolean;
};
type Provider = { enabled: boolean; url: string; secret: string; has_secret?: boolean };
type WebhookConfig = {
  enabled: boolean;
  notify_kinds: string[];
  notify_statuses: string[];
  providers: Record<string, Provider>;
};

const { t } = useI18n();
const configs = ref<Record<string, LlmItem>>({});
const presets = ref<LlmPreset[]>([]);
const defaultName = ref("");
const showForm = ref(false);
const isEditing = ref(false);
const selectedPresetId = ref("");
const showAdvanced = ref(false);
const llmForm = reactive({ name: "", base_url: "", api_key: "", model: "" });
const llmError = ref("");
const llmLoadError = ref("");
const webhookLoadError = ref("");
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

function presetById(id: string): LlmPreset | undefined {
  return presets.value.find((item) => item.id === id);
}

function presetLabel(preset: LlmPreset): string {
  const key = `settings.llm_preset.${preset.id}`;
  const label = t(key);
  return label === key ? preset.name : label;
}

function unusedName(base: string): string {
  const raw = base.trim();
  if (!raw) return "";
  if (!configs.value[raw]) return raw;
  let n = 2;
  while (configs.value[`${raw}-${n}`]) n += 1;
  return `${raw}-${n}`;
}

function matchPreset(baseUrl: string): LlmPreset | undefined {
  const needle = baseUrl.trim().replace(/\/+$/, "");
  if (!needle) return undefined;
  return presets.value.find((item) => !item.custom && item.base_url.replace(/\/+$/, "") === needle);
}

const selectedPreset = computed(() => presetById(selectedPresetId.value));
const matchedPreset = computed(() => matchPreset(llmForm.base_url));
const showPresetPicker = computed(() => showForm.value && !isEditing.value && !selectedPresetId.value);
const isCustomPreset = computed(() => Boolean(selectedPreset.value?.custom) || (isEditing.value && !matchedPreset.value));
const showBaseUrlField = computed(() => isEditing.value || isCustomPreset.value || showAdvanced.value);
const modelChoices = computed(() => {
  const fromPreset = selectedPreset.value?.models || matchedPreset.value?.models || [];
  const current = llmForm.model.trim();
  const seen = new Set(fromPreset);
  const options = fromPreset.map((model) => ({ label: model, value: model }));
  if (current && !seen.has(current)) options.unshift({ label: current, value: current });
  return options;
});

async function loadLlm() {
  const data = await httpJson<{
    configs: Record<string, LlmItem>;
    default: string;
    presets?: LlmPreset[];
  }>("/api/settings/llm");
  configs.value = data.configs || {};
  defaultName.value = data.default || "";
  if (data.presets?.length) presets.value = data.presets;
}

async function loadPresets() {
  if (presets.value.length) return;
  try {
    const data = await httpJson<{ presets: LlmPreset[] }>("/api/settings/llm/presets");
    presets.value = data.presets || [];
  } catch {
    presets.value = [];
  }
  if (!presets.value.length) {
    presets.value = [{
      id: "custom",
      name: "Custom",
      base_url: "",
      api_style: "openai",
      models: [],
      default_model: "",
      api_key_optional: false,
      custom: true,
    }];
  }
}

function loadErrorMessage(err: unknown): string {
  return err instanceof ApiError ? apiErrorMessage(err) || t("settings.load_failed") : t("settings.load_failed");
}

function resetForm() {
  Object.assign(llmForm, { name: "", base_url: "", api_key: "", model: "" });
  selectedPresetId.value = "";
  showAdvanced.value = false;
  llmError.value = "";
}

function openCreate() {
  isEditing.value = false;
  resetForm();
  showForm.value = true;
}

function backToPresets() {
  resetForm();
  showForm.value = true;
}

function selectPreset(preset: LlmPreset) {
  selectedPresetId.value = preset.id;
  llmError.value = "";
  showAdvanced.value = Boolean(preset.custom);
  Object.assign(llmForm, {
    name: preset.custom ? unusedName("custom") : unusedName(preset.id),
    base_url: preset.base_url,
    api_key: "",
    model: preset.default_model,
  });
}

function openEdit(name: string) {
  const cfg = configs.value[name];
  isEditing.value = true;
  llmError.value = "";
  showAdvanced.value = true;
  Object.assign(llmForm, { name, base_url: cfg.base_url, api_key: "", model: cfg.model });
  selectedPresetId.value = matchPreset(cfg.base_url)?.id || "custom";
  showForm.value = true;
}

async function saveLlm() {
  llmError.value = "";
  const preset = selectedPreset.value;
  const name = isEditing.value
    ? llmForm.name
    : llmForm.name.trim() || unusedName(preset && !preset.custom ? preset.id : "") || `config${Object.keys(configs.value).length + 1}`;
  if (!isCustomPreset.value && !llmForm.base_url.trim() && preset && !preset.custom) {
    llmForm.base_url = preset.base_url;
  }
  if (!llmForm.base_url.trim()) {
    llmError.value = t("settings.llm_base_url_required");
    return;
  }
  if (!llmForm.model.trim()) {
    llmError.value = t("settings.llm_model_required");
    return;
  }
  const needsKey = !(preset?.api_key_optional || matchedPreset.value?.api_key_optional);
  if (needsKey && !isEditing.value && !llmForm.api_key.trim()) {
    llmError.value = t("settings.llm_api_key_required");
    return;
  }
  try {
    await httpJson("/api/settings/llm", {
      method: "POST",
      body: JSON.stringify({
        name,
        base_url: llmForm.base_url.trim(),
        api_key: llmForm.api_key,
        model: llmForm.model.trim(),
        preset_id: selectedPresetId.value || undefined,
        set_default: true,
      }),
    });
    showForm.value = false;
    resetForm();
    await loadLlm();
  } catch (err) {
    llmError.value = err instanceof ApiError ? apiErrorMessage(err) || t("settings.save_failed") : t("settings.save_failed");
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

async function loadPage() {
  if (!loaded.value) loading.value = true;
  llmLoadError.value = "";
  webhookLoadError.value = "";
  try {
    const [llmResult, hookResult] = await Promise.allSettled([loadLlm(), loadWebhook()]);
    if (llmResult.status === "rejected") llmLoadError.value = loadErrorMessage(llmResult.reason);
    if (hookResult.status === "rejected") webhookLoadError.value = loadErrorMessage(hookResult.reason);
    if (!presets.value.length) await loadPresets();
    loaded.value = true;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadPage();
});
</script>

<template>
  <div class="page-stack">
    <PageLoading v-if="loading && !loaded" size="page" />
    <div class="card">
      <div class="toolbar">
        <h2>{{ t("settings.llm_title") }}</h2>
        <t-button :disabled="loading" @click="openCreate">{{ t("settings.add_config") }}</t-button>
      </div>
      <div v-if="loaded" class="card-body">
      <p v-if="llmLoadError" class="err">{{ llmLoadError }}</p>
      <t-button v-if="llmLoadError" size="small" @click="loadPage">{{ t("index.retry") }}</t-button>
      <div v-if="showForm" class="form-box">
        <div class="form-head">
          <p>{{ isEditing ? t("settings.edit_config") : t("settings.new_config") }}</p>
          <t-button
            v-if="!isEditing && selectedPresetId"
            size="small"
            variant="text"
            @click="backToPresets"
          >
            {{ t("settings.llm_change_provider") }}
          </t-button>
        </div>
        <div v-if="showPresetPicker" class="preset-picker">
          <p class="preset-lead">{{ t("settings.llm_choose_provider") }}</p>
          <div class="preset-grid">
            <button
              v-for="preset in presets"
              :key="preset.id"
              type="button"
              class="preset-card"
              :class="{ custom: preset.custom }"
              @click="selectPreset(preset)"
            >
              <strong>{{ presetLabel(preset) }}</strong>
              <span>{{ preset.custom ? t("settings.llm_custom_hint") : preset.base_url }}</span>
            </button>
          </div>
        </div>
        <template v-else>
          <label class="field">
            <span>{{ t("settings.config_name") }}</span>
            <t-input v-model="llmForm.name" :disabled="isEditing" :placeholder="t('settings.config_name_ph')" />
          </label>
          <div v-if="selectedPreset && !selectedPreset.custom" class="preset-meta">
            <span>{{ presetLabel(selectedPreset) }}</span>
            <span class="badge">{{ t("settings.llm_api_style_openai") }}</span>
          </div>
          <p v-if="!showBaseUrlField && llmForm.base_url" class="url-readonly">
            <span>{{ t("settings.llm_base_url") }}</span>
            <code>{{ llmForm.base_url }}</code>
          </p>
          <t-button
            v-if="!isEditing && !isCustomPreset && !showAdvanced"
            size="small"
            variant="text"
            class="advanced-toggle"
            @click="showAdvanced = true"
          >
            {{ t("settings.llm_advanced") }}
          </t-button>
          <label v-if="showBaseUrlField" class="field">
            <span>{{ t("settings.llm_base_url") }}</span>
            <t-input v-model="llmForm.base_url" :placeholder="t('settings.llm_base_url_ph')" />
          </label>
          <label class="field">
            <span>{{ t("settings.llm_api_key") }}</span>
            <t-input
              v-model="llmForm.api_key"
              type="password"
              :placeholder="isEditing ? t('settings.llm_api_key_kept') : (selectedPreset?.api_key_optional ? t('settings.llm_api_key_optional') : 'sk-...')"
            />
          </label>
          <p v-if="selectedPreset?.api_key_optional" class="hint">{{ t("settings.llm_ollama_hint") }}</p>
          <label class="field">
            <span>{{ t("settings.llm_model") }}</span>
            <t-input
              v-if="!modelChoices.length"
              v-model="llmForm.model"
              :placeholder="t('settings.llm_model_ph')"
            />
            <t-select
              v-else
              v-model="llmForm.model"
              filterable
              creatable
              clearable
              :options="modelChoices"
              :placeholder="t('settings.llm_model_ph')"
            />
          </label>
          <p v-if="llmError" class="err">{{ llmError }}</p>
          <div class="field-row">
            <t-button theme="primary" @click="saveLlm">{{ t("common.save") }}</t-button>
            <t-button @click="showForm = false; resetForm()">{{ t("common.cancel") }}</t-button>
          </div>
        </template>
      </div>
      <t-empty v-if="!showForm && !Object.keys(configs).length" :description="t('settings.empty_configs')" />
      <div v-for="(cfg, name) in configs" :key="name" class="llm-row">
        <div>
          <strong>{{ name }}</strong>
          <span v-if="name === defaultName" class="badge">{{ t("common.default") }}</span>
          <div class="muted">{{ cfg.base_url }} / {{ cfg.model }}</div>
        </div>
        <div class="field-row">
          <t-button v-if="name !== defaultName" size="small" @click="setDefault(String(name))">{{ t("common.set_default") }}</t-button>
          <t-button size="small" @click="openEdit(String(name))">{{ t("common.edit") }}</t-button>
          <t-button size="small" @click="deleteLlm(String(name))">{{ t("common.delete") }}</t-button>
        </div>
      </div>
      </div>
    </div>

    <div class="card">
      <div class="toolbar">
        <h2>{{ t("settings.webhook_title") }}</h2>
        <t-button theme="primary" :disabled="loading" @click="saveWebhook">{{ t("common.save") }}</t-button>
      </div>
      <div v-if="loaded" class="card-body">
      <p v-if="webhookLoadError" class="err">{{ webhookLoadError }}</p>
      <t-button v-if="webhookLoadError" size="small" @click="loadPage">{{ t("index.retry") }}</t-button>
      <p v-if="webhookError" class="err">{{ webhookError }}</p>
      <t-checkbox v-model="webhook.enabled">{{ t("settings.webhook_enable") }}</t-checkbox>
      <div class="split">
        <div>
          <h3>{{ t("settings.webhook_tasks") }}</h3>
          <t-checkbox
            v-for="[id, key] in kinds"
            :key="id"
            :checked="webhook.notify_kinds.includes(id)"
            @change="(on: boolean) => toggle('notify_kinds', id, on)"
          >
            {{ t(key) }}
          </t-checkbox>
        </div>
        <div>
          <h3>{{ t("settings.webhook_status") }}</h3>
          <t-checkbox
            v-for="[id, key] in statuses"
            :key="id"
            :checked="webhook.notify_statuses.includes(id)"
            @change="(on: boolean) => toggle('notify_statuses', id, on)"
          >
            {{ t(key) }}
          </t-checkbox>
        </div>
      </div>
      <div v-for="[id, key] in providers" :key="id" class="provider">
        <t-checkbox v-model="webhook.providers[id].enabled">
          {{ t(key) }}
        </t-checkbox>
        <label class="field"><span>URL</span><t-input v-model="webhook.providers[id].url" /></label>
        <label class="field">
          <span>{{ t("settings.secret_ph") }}</span>
          <t-input v-model="webhook.providers[id].secret" type="password" :placeholder="webhook.providers[id].has_secret ? t('settings.secret_kept') : ''" />
        </label>
        <t-button size="small" @click="testProvider(id)">{{ t("settings.save_test") }}</t-button>
      </div>
      <ul v-if="testResults.length" class="results">
        <li v-for="row in testResults" :key="row.provider">{{ row.provider }}: {{ row.ok ? t("settings.test_ok") : (row.error || t("settings.test_failed")) }}</li>
      </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.card { display: flex; flex-direction: column; min-width: 0; overflow: visible; }
.card-body { min-width: 0; overflow: visible; }
.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
h2, h3 { margin: 0 0 8px; font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-muted); }
.form-box, .provider, .llm-row { border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin: 10px 0; display: flex; flex-direction: column; gap: 8px; }
.form-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.form-head p { margin: 0; }
.preset-lead { margin: 0 0 4px; color: var(--text-muted); font-size: 12px; }
.preset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
.preset-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--raised);
  color: var(--text);
  cursor: pointer;
  text-align: left;
  transition: border-color 160ms ease, background-color 160ms ease;
}
.preset-card:hover { border-color: var(--accent-dim); }
.preset-card.custom { border-style: dashed; }
.preset-card strong { font-size: 13px; }
.preset-card span { color: var(--text-muted); font-size: 11px; word-break: break-all; }
.preset-meta { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.url-readonly { margin: 0; display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-muted); }
.url-readonly code { color: var(--text); font-size: 12px; word-break: break-all; }
.advanced-toggle { align-self: flex-start; }
.hint { margin: 0; color: var(--text-muted); font-size: 12px; }
.llm-row { flex-direction: row; justify-content: space-between; align-items: center; }
.muted { color: var(--text-muted); font-size: 12px; }
.err { color: var(--err); }
.badge { margin-left: 8px; font-size: 10px; color: var(--accent); }
.split :deep(.t-checkbox) { display: flex; margin: 4px 0; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 12px 0; }
.results { color: var(--text-muted); font-size: 12px; }
@media (max-width: 1100px) { .split, .llm-row { grid-template-columns: 1fr; flex-direction: column; } }
</style>
