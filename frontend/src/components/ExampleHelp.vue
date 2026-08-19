<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{
  kind: "csv" | "shots" | "iap";
  label: string;
}>();

const { t } = useI18n();
const open = ref(false);

const hint = computed(() => {
  if (props.kind === "csv") return t("common.csv_help_btn");
  if (props.kind === "shots") return t("common.shots_help_btn");
  return t("iap.json_help");
});

const title = computed(() => {
  if (props.kind === "csv") return t("common.csv_help_title");
  if (props.kind === "shots") return t("common.shots_help_title");
  return t("iap.json_title");
});

const downloadHref = computed(() => {
  if (props.kind === "csv") return "/api/examples/csv";
  if (props.kind === "shots") return "/api/examples/screenshots";
  return "/api/examples/iap.json";
});

const downloadLabel = computed(() => {
  if (props.kind === "csv") return t("common.download_sample_csv");
  if (props.kind === "shots") return t("common.download_sample_shots");
  return t("iap.download_sample");
});

const downloadName = computed(() => (props.kind === "iap" ? "iap_packages_example.json" : ""));
</script>

<template>
  <div class="ex-help">
    <div class="ex-help__head">
      <span class="ex-help__label">{{ label }}</span>
      <button
        type="button"
        class="ex-help__q"
        :class="{ on: open }"
        :title="hint"
        :aria-label="hint"
        :aria-expanded="open"
        @click="open = true"
      >?</button>
    </div>
    <t-dialog
      v-model:visible="open"
      :header="title"
      :width="kind === 'iap' ? '720px' : '560px'"
      attach="body"
      placement="center"
    >
      <div class="ex-help__body">
        <template v-if="kind === 'csv'">
          <p>{{ t("metadata.csv_help_utf8") }}</p>
          <p>
            <strong>{{ t("metadata.required_cols") }}</strong>
            <code>locale</code> <code>name</code> <code>subtitle</code> <code>description</code> <code>keywords</code>
          </p>
          <p>
            <strong>{{ t("metadata.optional_cols") }}</strong>
            <code>supportUrl</code> <code>marketingUrl</code> <code>privacyPolicyUrl</code>
          </p>
          <p>
            <strong>{{ t("metadata.locale_format") }}</strong>
            <code>简体中文(zh-Hans)</code> {{ t("metadata.or") }} <code>en-US</code>
          </p>
          <p>{{ t("metadata.csv_zh_compat") }}</p>
          <p class="ex-help__muted">{{ t("metadata.empty_skip") }}</p>
        </template>
        <template v-else-if="kind === 'shots'">
          <pre>screenshots/
├── zh-Hans/     ← {{ t("metadata.locale_dir_hint") }}
│   ├── 01_home.png
│   └── 02_detail.png
└── en-US/
    └── 01_home.png</pre>
          <p>
            <strong>{{ t("metadata.locale_dirs") }}</strong>
            <code>zh-Hans</code>、<code>en-US</code>、<code>ja</code> {{ t("metadata.etc") }}
          </p>
          <p>
            <strong>{{ t("metadata.image_format") }}</strong>{{ t("metadata.image_format_desc") }}
          </p>
          <p>
            <strong>{{ t("metadata.device_type") }}</strong>{{ t("metadata.device_type_desc") }}
          </p>
        </template>
        <template v-else>
          <p>{{ t("iap.help_top") }}</p>
          <p><strong>{{ t("iap.help_consumable") }}</strong>{{ t("iap.help_consumable_body") }}</p>
          <pre>{
  "items": [
    {
      "productId": "com.example.app.coins.100",
      "name": "100 Coins",
      "inAppPurchaseType": "CONSUMABLE",
      "availableInAllTerritories": true,
      "price": { "baseTerritory": "USA", "baseAmount": "0.99", "applyEqualizedPrices": true },
      "localizations": {
        "zh-Hans": { "name": "100 金币", "description": "购买后获得 100 枚金币。" },
        "en-US": { "name": "100 Coins", "description": "Get 100 coins after purchase." }
      },
      "review": { "screenshot": "./iap_review/coins.png", "note": "Review note" }
    }
  ]
}</pre>
          <p><strong>{{ t("iap.help_sub") }}</strong>{{ t("iap.help_sub_body") }}</p>
          <pre>{
  "subscriptionGroups": [
    {
      "referenceName": "Premium Membership",
      "localizations": {
        "zh-Hans": { "name": "高级会员" },
        "en-US": { "name": "Premium" }
      },
      "subscriptions": [
        {
          "productId": "com.example.app.premium.monthly",
          "name": "Premium Monthly",
          "subscriptionPeriod": "ONE_MONTH",
          "price": { "baseTerritory": "USA", "baseAmount": "9.99", "applyEqualizedPrices": true },
          "review": { "screenshot": "./iap_review/premium_monthly.png", "note": "Review note" }
        }
      ]
    }
  ]
}</pre>
          <p class="ex-help__muted">{{ t("iap.help_review_path") }}</p>
        </template>
      </div>
      <template #footer>
        <div class="ex-help__footer">
          <a class="ex-help__dl" :href="downloadHref" :download="downloadName">{{ downloadLabel }}</a>
          <t-button theme="primary" @click="open = false">{{ t("common.close") }}</t-button>
        </div>
      </template>
    </t-dialog>
  </div>
</template>

<style scoped>
.ex-help__head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ex-help__label {
  font-size: 12px;
  color: var(--text-muted);
}

.ex-help__q {
  width: 16px;
  height: 16px;
  padding: 0;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  background: transparent;
  color: var(--text-faint);
  font-size: 10px;
  line-height: 1;
  cursor: pointer;
}

.ex-help__q:hover,
.ex-help__q.on {
  color: var(--accent);
  border-color: var(--accent-dim);
}

.ex-help__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--text);
}

.ex-help__body p {
  margin: 0;
}

.ex-help__muted {
  color: var(--text-faint);
}

.ex-help__body code {
  background: var(--raised);
  color: var(--accent);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
}

.ex-help__body pre {
  margin: 0;
  background: var(--raised);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 11px;
  line-height: 1.5;
  overflow-x: auto;
  color: var(--text-muted);
  font-family: "Fira Code", ui-monospace, monospace;
}

.ex-help__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex: 1;
  width: 100%;
}

.ex-help__dl {
  flex: 1 1 auto;
  min-width: 0;
  font-weight: 500;
  white-space: nowrap;
}
</style>
