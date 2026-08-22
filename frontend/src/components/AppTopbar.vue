<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { MessagePlugin } from "tdesign-vue-next";
import { httpForm } from "@/api/http";
import { useAddProfile } from "@/composables/useAddProfile";
import { useProfile } from "@/composables/useProfile";

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const { snapshot, switchProfile } = useProfile();
const { requestOpen } = useAddProfile();

const TITLE_KEYS: Array<{ test: (path: string) => boolean; key: string }> = [
  { test: (p) => p === "/", key: "nav.dashboard" },
  { test: (p) => p === "/listing", key: "nav.listing" },
  { test: (p) => p === "/whats-new", key: "nav.whats_new" },
  { test: (p) => p === "/urls", key: "nav.urls" },
  { test: (p) => p === "/build", key: "nav.build" },
  { test: (p) => p === "/iap", key: "nav.iap" },
  { test: (p) => p === "/profiles", key: "nav.profiles" },
  { test: (p) => p === "/guard", key: "nav.guard" },
  { test: (p) => p === "/settings", key: "nav.settings" },
  { test: (p) => p === "/update", key: "nav.update" },
];

const titleKey = computed(() => {
  const path = route.path;
  return TITLE_KEYS.find((row) => row.test(path))?.key ?? "nav.dashboard";
});

const currentName = computed(() => snapshot.value?.current_profile || "");
const profiles = computed(() => snapshot.value?.profiles ?? []);
const access = computed(() => snapshot.value?.profile_access ?? {});
const hasMachine = computed(() => Boolean(snapshot.value?.has_machine_profile));
const lang = computed(() => (locale.value === "zh" ? "zh" : "en"));

async function onProfileChange(name: unknown) {
  const next = String(name ?? "");
  if (!next || next === currentName.value) return;
  try {
    await switchProfile(next);
  } catch (err) {
    MessagePlugin.error(err instanceof Error ? err.message : String(err));
  }
}

async function setLang(code: unknown) {
  if (code !== "zh" && code !== "en") return;
  try {
    await httpForm("/api/settings/lang", new URLSearchParams({ lang: code }));
    locale.value = code;
    document.documentElement.lang = code === "zh" ? "zh-CN" : "en";
    localStorage.setItem("asc_lang", code);
  } catch {
    MessagePlugin.error(t("lang.switch_failed"));
  }
}

function onNewProfile(event: MouseEvent) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
    return;
  }
  event.preventDefault();
  requestOpen();
  if (route.path === "/profiles") return;
  void router.push({ path: "/profiles", query: { new: "1" } });
}
</script>

<template>
  <header class="topbar">
    <div class="topbar-left">
      <h1>{{ t(titleKey) }}</h1>
      <span class="profile-name mono">{{ currentName || t("nav.select_app") }}</span>
    </div>
    <div class="topbar-right">
      <a
        v-if="!hasMachine"
        class="new-profile"
        href="/profiles?new=1"
        @click="onNewProfile"
      >
        {{ t("nav.new_profile") }}
      </a>
      <t-select
        class="profile-select"
        :value="currentName"
        :placeholder="t('nav.select_app')"
        @change="onProfileChange"
      >
        <t-option
          v-for="name in profiles"
          :key="name"
          :value="name"
          :label="name + (access[name]?.enabled === false ? t('nav.other_machine') : '')"
          :disabled="access[name]?.enabled === false"
        />
      </t-select>
      <t-radio-group
        class="lang-switch"
        :value="lang"
        size="small"
        variant="default-filled"
        @change="setLang"
      >
        <t-radio-button value="zh">zh</t-radio-button>
        <t-radio-button value="en">en</t-radio-button>
      </t-radio-group>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: var(--topbar-height);
  padding: 0 24px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.topbar-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
}

.topbar-left h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.profile-name {
  color: var(--text-muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.new-profile {
  font-size: 12px;
  color: var(--accent);
  white-space: nowrap;
}

.profile-select {
  min-width: 160px;
  max-width: 240px;
}

.topbar-right > .lang-switch {
  flex: 0 0 auto;
  flex-wrap: nowrap;
  width: max-content;
}

.lang-switch :deep(.t-radio-button) {
  flex: 0 0 auto;
}
</style>
