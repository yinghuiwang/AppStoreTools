<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { AddIcon, ChevronDownIcon, ChevronUpIcon } from "tdesign-icons-vue-next";
import { MessagePlugin } from "tdesign-vue-next";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import PageLoading from "@/components/PageLoading.vue";
import LocalePicker from "@/components/LocalePicker.vue";
import { useAgent } from "@/composables/useAgent";
import { useImageViewer } from "@/composables/useImageViewer";
import { useLocaleCatalog } from "@/composables/useLocaleCatalog";
import {
  useListingWorkflow,
  type ListingLocale,
  type ListingPlanLocale,
  type ListingShot,
  type ListingSnapshot,
} from "@/composables/useListingWorkflow";
import { useTaskLog } from "@/composables/useTaskLog";
import ListingEditorDialog from "./ListingEditorDialog.vue";

const { t } = useI18n();
const viewer = useImageViewer();
const workflow = useListingWorkflow();
const { appliedTick } = useAgent();
const { channelOf } = useTaskLog();
const catalog = useLocaleCatalog({ presence: false });
const compareLog = channelOf(workflow.compareTaskId);

const COMPARE_PHASE_KEYS: Record<string, string> = {
  local: "listing.compare.phase_local",
  text: "listing.compare.phase_text",
  shots: "listing.compare.phase_shots",
  done: "listing.compare.phase_done",
};

const nowTick = ref(Date.now());
let elapsedTimer: number | null = null;

function stopElapsedTimer() {
  if (elapsedTimer != null) {
    window.clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

watch(
  () => workflow.planLoading.value,
  (loading) => {
    stopElapsedTimer();
    if (!loading) return;
    nowTick.value = Date.now();
    elapsedTimer = window.setInterval(() => {
      nowTick.value = Date.now();
    }, 1000);
  },
  { immediate: true },
);

onUnmounted(stopElapsedTimer);

const compareLabel = computed(() => {
  const phase = compareLog.progress.value.phase;
  const key = COMPARE_PHASE_KEYS[phase];
  if (key) return t(key);
  return compareLog.progress.value.phase_label || t("listing.filter.checking");
});

const comparePct = computed(() => {
  const pct = Number(compareLog.progress.value.pct) || 0;
  return Math.min(100, Math.max(0, pct));
});

const compareElapsed = computed(() => {
  const start = workflow.compareStartedAt.value;
  if (!start) return 0;
  return Math.max(0, Math.floor((nowTick.value - start) / 1000));
});

const query = ref("");
const filter = ref<"all" | "local-only" | "changed" | "missing-shot">("all");
const editorOpen = ref(false);
const editorIndex = ref(-1);
const editorDraft = ref<ListingLocale | null>(null);
const addingLocale = ref("");
const pickerOpen = ref(false);
const shotFileInput = ref<HTMLInputElement | null>(null);
type ShotPick = { kind: "add"; locale: string; displayType: string } | { kind: "replace"; path: string };
const shotPick = ref<ShotPick | null>(null);

onMounted(() => {
  void catalog.load();
});

const planByLocale = computed(() => {
  const map: Record<string, ListingPlanLocale> = {};
  for (const row of workflow.planLocales.value) map[row.locale] = row;
  return map;
});

function planStatus(locale: string): string {
  if (workflow.planLoading.value || !workflow.compared.value) return "unchecked";
  const row = planByLocale.value[locale];
  if (row?.status) return row.status;
  if (!workflow.planOk.value) return "unchecked";
  return "local-only";
}

function hasShots(row: ListingLocale): boolean {
  return Object.values(row.screenshots || {}).some((group) => group.length > 0);
}

function descriptionText(row: ListingLocale): string {
  return (row.fields.description || "").trim();
}

function isMissingShot(row: ListingLocale): boolean {
  if (hasShots(row)) return false;
  if (!workflow.compared.value) return true;
  return planByLocale.value[row.locale]?.missingScreenshots !== false;
}

function matchesQuery(row: ListingLocale): boolean {
  const q = query.value.trim().toLowerCase();
  if (!q) return true;
  const name = row.fields.name || "";
  return row.locale.toLowerCase().includes(q) || name.toLowerCase().includes(q);
}

function matchesFilter(row: ListingLocale): boolean {
  if (filter.value === "all") return true;
  if (filter.value === "missing-shot") return isMissingShot(row);
  const status = planStatus(row.locale);
  if (filter.value === "local-only") return status === "local-only";
  if (filter.value === "changed") return status === "changed";
  return true;
}

const filterCounts = computed(() => {
  const rows = workflow.snapshot.value.locales || [];
  let local = 0;
  let changed = 0;
  let shot = 0;
  for (const row of rows) {
    const status = planStatus(row.locale);
    if (status === "local-only") local += 1;
    if (status === "changed") changed += 1;
    if (isMissingShot(row)) shot += 1;
  }
  return { all: rows.length, local, changed, shot };
});

const storeReady = computed(() => workflow.compared.value);
const filterOptions = computed(() => [
  { value: "all" as const, label: t("listing.filter.all"), count: filterCounts.value.all, disabled: false },
  {
    value: "local-only" as const,
    label: t("listing.filter.local"),
    count: storeReady.value ? filterCounts.value.local : null,
    disabled: !storeReady.value,
  },
  {
    value: "changed" as const,
    label: t("listing.filter.changed"),
    count: storeReady.value ? filterCounts.value.changed : null,
    disabled: !storeReady.value,
  },
  { value: "missing-shot" as const, label: t("listing.filter.shot"), count: filterCounts.value.shot, disabled: false },
]);

const visibleLocales = computed(() =>
  (workflow.snapshot.value.locales || [])
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => matchesQuery(row) && matchesFilter(row)),
);

const listEmpty = computed(() => !visibleLocales.value.length);
const showLocaleToc = computed(() => visibleLocales.value.length > 1);
const activeLocale = ref("");
const tocEl = ref<HTMLElement | null>(null);
let sectionObserver: IntersectionObserver | null = null;
let tocLockUntil = 0;

function localeAnchorId(locale: string): string {
  return `listing-locale-${locale.replace(/[^A-Za-z0-9_-]/g, "_")}`;
}

function findScrollRoot(el: HTMLElement | null): HTMLElement | null {
  const named = el?.closest(".listing-body");
  if (named instanceof HTMLElement) return named;
  let node = el?.parentElement ?? null;
  while (node) {
    const style = getComputedStyle(node);
    if (/(auto|scroll)/.test(style.overflowY)) return node;
    node = node.parentElement;
  }
  return null;
}

function syncActiveLocale() {
  const codes = visibleLocales.value.map((entry) => entry.row.locale);
  if (!codes.length) {
    activeLocale.value = "";
    return;
  }
  if (!codes.includes(activeLocale.value)) {
    activeLocale.value = codes[0];
  }
}

function scrollToLocale(locale: string) {
  const el = document.getElementById(localeAnchorId(locale));
  if (!el) return;
  tocLockUntil = Date.now() + 800;
  activeLocale.value = locale;
  workflow.selectedLocale.value = locale;
  el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function disconnectSectionObserver() {
  sectionObserver?.disconnect();
  sectionObserver = null;
}

function bindSectionObserver() {
  disconnectSectionObserver();
  if (!showLocaleToc.value) return;
  const root = findScrollRoot(tocEl.value);
  sectionObserver = new IntersectionObserver(
    (entries) => {
      if (Date.now() < tocLockUntil) return;
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      const id = visible[0]?.target.id || "";
      const prefix = "listing-locale-";
      if (!id.startsWith(prefix)) return;
      const locale = visibleLocales.value.find((entry) => localeAnchorId(entry.row.locale) === id)?.row.locale;
      if (locale) activeLocale.value = locale;
    },
    { root, rootMargin: "0px 0px -55% 0px", threshold: [0.08, 0.24] },
  );
  for (const entry of visibleLocales.value) {
    const el = document.getElementById(localeAnchorId(entry.row.locale));
    if (el) sectionObserver.observe(el);
  }
}

watch(visibleLocales, () => {
  syncActiveLocale();
  void nextTick(bindSectionObserver);
}, { flush: "post" });

onMounted(() => {
  syncActiveLocale();
  void nextTick(bindSectionObserver);
});

onUnmounted(disconnectSectionObserver);

const emptyFilterText = computed(() => {
  if (query.value.trim()) return t("listing.filter.empty_changed");
  if (filter.value === "local-only" || filter.value === "changed") {
    if (!workflow.compared.value) return t("listing.filter.need_compare");
    if (!workflow.planOk.value) return t("listing.filter.plan_failed");
  }
  if (filter.value === "local-only") return t("listing.filter.empty_local");
  if (filter.value === "changed") return t("listing.filter.empty_changed");
  if (filter.value === "missing-shot") return t("listing.filter.empty_shot");
  return t("listing.empty_open");
});

const localeOptions = computed(() => {
  const used = new Set((workflow.snapshot.value.locales || []).map((row) => row.locale));
  return catalog.rows.value.map((row) => ({
    label: catalog.labelFor(row.code),
    value: row.code,
    disabled: used.has(row.code),
  }));
});

function clip(text: string, n: number): string {
  const value = (text || "").trim();
  if (value.length <= n) return value || "—";
  return `${value.slice(0, n)}…`;
}

function dtypeLabel(dtype: string): string {
  return dtype === "UNKNOWN" ? t("metadata.shots_unknown_type") : dtype;
}

function refreshStore() {
  void workflow.ensureCompare({ force: true });
}

watch(appliedTick, () => {
  editorOpen.value = false;
  editorDraft.value = null;
  editorIndex.value = -1;
});

watch(storeReady, (ready) => {
  if (!ready && (filter.value === "local-only" || filter.value === "changed")) {
    filter.value = "all";
  }
});

function cloneOf<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function openEditor(index: number) {
  const row = workflow.snapshot.value.locales[index];
  if (!row) return;
  editorIndex.value = index;
  editorDraft.value = cloneOf(row);
  editorOpen.value = true;
  workflow.selectedLocale.value = row.locale;
}

function applyEditor() {
  const draft = editorDraft.value;
  if (!draft || editorIndex.value < 0) return closeEditor();
  workflow.snapshot.value.locales[editorIndex.value] = {
    ...workflow.snapshot.value.locales[editorIndex.value],
    fields: { ...draft.fields },
  };
  workflow.markDirty();
  closeEditor();
}

function closeEditor() {
  editorOpen.value = false;
  editorDraft.value = null;
  editorIndex.value = -1;
}

async function addLocale() {
  const locale = addingLocale.value;
  if (!locale) return;
  if (workflow.snapshot.value.locales.some((row) => row.locale === locale)) return;
  const row = workflow.blankLocale(locale);
  const src = workflow.snapshot.value.locales.find((item) => item.locale === "en-US" && item.fields.name)
    || workflow.snapshot.value.locales.find((item) => item.fields.name);
  workflow.snapshot.value.locales.push(row);
  addingLocale.value = "";
  workflow.markDirty();
  if (!workflow.autoTranslate.value || !src?.fields.name) return;
  try {
    const data = await httpJson<{ translations?: Array<Record<string, string>> }>("/api/listing/translate", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({
        source_locale: src.locale,
        mode: "translate",
        fields: [{
          locale,
          name: src.fields.name,
          subtitle: src.fields.subtitle,
          keywords: src.fields.keywords,
          description: src.fields.description,
        }],
      }),
    });
    const translated = data.translations?.[0];
    if (translated) {
      row.fields.name = translated.name || row.fields.name;
      row.fields.subtitle = translated.subtitle || row.fields.subtitle;
      row.fields.keywords = translated.keywords || row.fields.keywords;
      row.fields.description = translated.description || row.fields.description;
      workflow.markDirty();
    }
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) MessagePlugin.warning(t("listing.translate_no_key"));
    else MessagePlugin.error(err instanceof ApiError ? apiErrorMessage(err) : String(err));
  }
}

async function pullOne(locale: string) {
  try {
    const data = await httpJson<{ snapshot: ListingSnapshot }>("/api/listing/pull/text", {
      method: "POST",
      body: JSON.stringify({
        csv_path: workflow.csvPath.value,
        screenshots_dir: workflow.screenshotsDir.value,
        expected_mtime: workflow.mtime.value,
        write: false,
        selections: [{ locale, fields: ["name", "subtitle", "description", "keywords", "supportUrl", "marketingUrl", "privacyPolicyUrl"] }],
      }),
    });
    workflow.applySnapshot(data.snapshot, { dirty: true, storeDraft: true });
    await workflow.ensureCompare({ force: true });
  } catch (err) {
    MessagePlugin.error(err instanceof ApiError ? apiErrorMessage(err) : String(err));
  }
}

async function addShot(locale: string, displayType: string, file: File) {
  const body = new FormData();
  body.set("root", workflow.screenshotsDir.value);
  body.set("locale", locale);
  body.set("display_type", displayType);
  body.set("filename", file.name);
  body.set("file", file);
  await httpJson("/api/listing/screenshots/add", { method: "POST", body });
  await workflow.refreshLocaleShots(locale);
}

async function replaceShot(locale: string, path: string, file: File) {
  const body = new FormData();
  body.set("root", workflow.screenshotsDir.value);
  body.set("path", path);
  body.set("new_name", file.name);
  body.set("file", file);
  await httpJson("/api/listing/screenshots/replace", { method: "POST", body });
  await workflow.refreshLocaleShots(locale);
}

async function deleteShot(locale: string, path: string) {
  await httpJson("/api/listing/screenshots/delete", {
    method: "POST",
    body: JSON.stringify({ root: workflow.screenshotsDir.value, path }),
  });
  await workflow.refreshLocaleShots(locale);
}

async function moveShot(locale: string, displayType: string, index: number, delta: number) {
  const row = workflow.snapshot.value.locales.find((item) => item.locale === locale);
  const group = row?.screenshots[displayType] || [];
  const next = index + delta;
  if (next < 0 || next >= group.length) return;
  const names = group.map((item) => item.file_name);
  const [item] = names.splice(index, 1);
  names.splice(next, 0, item);
  await httpJson("/api/listing/screenshots/reorder", {
    method: "POST",
    body: JSON.stringify({
      root: workflow.screenshotsDir.value,
      locale,
      display_type: displayType,
      file_names: names,
    }),
  });
  await workflow.refreshLocaleShots(locale);
}

function openShots(group: ListingShot[], start: number) {
  viewer.show(group.map((item) => ({ src: item.thumb_url, title: item.file_name })), start);
}

function openAddShot(locale: string, displayType: string) {
  shotPick.value = { kind: "add", locale, displayType };
  shotFileInput.value?.click();
}

function openReplaceShot(path: string) {
  shotPick.value = { kind: "replace", path };
  shotFileInput.value?.click();
}

function onShotFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  const pick = shotPick.value;
  input.value = "";
  shotPick.value = null;
  if (!file || !pick) return;
  if (pick.kind === "add") void addShot(pick.locale, pick.displayType, file);
  else {
    const locale = workflow.snapshot.value.locales.find((row) =>
      Object.values(row.screenshots || {}).some((group) => group.some((item) => item.local_path === pick.path)),
    )?.locale || "";
    if (locale) void replaceShot(locale, pick.path, file);
  }
}

const editorPlan = computed(() => {
  if (editorIndex.value < 0) return undefined;
  const locale = workflow.snapshot.value.locales[editorIndex.value]?.locale;
  return locale ? planByLocale.value[locale] : undefined;
});
</script>

<template>
  <div class="edit-stack">
    <p v-if="!workflow.hasContent.value" class="empty-row card">
      {{ t("listing.empty_open") }}
    </p>
    <div class="card toolbar">
      <t-input v-model="query" :placeholder="t('listing.search')" />
      <t-radio-group v-model="filter" variant="default-filled" size="small" class="filter-seg">
        <t-radio-button
          v-for="opt in filterOptions"
          :key="opt.value"
          :value="opt.value"
          :disabled="opt.disabled"
          :title="opt.disabled ? t('listing.filter.need_compare') : undefined"
        >
          {{ opt.label }}
          <span v-if="opt.count != null" class="filter-count">{{ opt.count }}</span>
        </t-radio-button>
      </t-radio-group>
      <div class="tree-actions">
        <t-select
          class="locale-add"
          v-model="addingLocale"
          filterable
          :placeholder="t('listing.add_locale')"
          :options="localeOptions"
          :popup-props="{ attach: 'body' }"
        />
        <t-button size="small" variant="outline" @click="pickerOpen = true">{{ t("metadata.locales_btn") }}</t-button>
        <t-button size="small" :disabled="!addingLocale" @click="addLocale">{{ t("listing.add_locale") }}</t-button>
        <t-button
          size="small"
          variant="outline"
          :disabled="workflow.emptyProfile.value || workflow.planLoading.value"
          @click="refreshStore"
        >
          {{ workflow.compared.value ? t("listing.compare.refresh") : t("listing.compare.button") }}
        </t-button>
        <t-checkbox v-model="workflow.autoTranslate.value" @change="workflow.persistMemory()">{{ t("listing.auto_translate") }}</t-checkbox>
      </div>
      <p v-if="!workflow.planOk.value && !workflow.planLoading.value" class="muted">
        {{ workflow.planError.value || t("listing.plan_unchecked") }}
      </p>
      <p v-else-if="!workflow.compared.value && !workflow.planLoading.value" class="muted">
        {{ t("listing.filter.need_compare") }}
      </p>
    </div>

    <div
      v-if="workflow.planLoading.value"
      class="empty-row card compare-progress"
      role="status"
      aria-busy="true"
    >
      <PageLoading size="inline" :text="compareLabel" />
      <div class="compare-meta">
        <span v-if="comparePct > 0" class="mono">{{ comparePct }}%</span>
        <span class="muted">{{ t("listing.compare.elapsed", { s: compareElapsed }) }}</span>
      </div>
      <div class="meter live">
        <i :style="{ width: `${comparePct}%` }" />
      </div>
    </div>

    <input
      ref="shotFileInput"
      class="file-hidden"
      type="file"
      accept="image/png,image/jpeg"
      tabindex="-1"
      @change="onShotFileChange"
    />

    <div v-if="visibleLocales.length" class="preview-layout" :class="{ 'has-toc': showLocaleToc }">
      <nav
        v-if="showLocaleToc"
        ref="tocEl"
        class="card locale-toc"
        :aria-label="t('listing.toc_title')"
      >
        <div class="toc-head">
          <strong>{{ t("listing.toc_title") }}</strong>
          <span class="muted">{{ visibleLocales.length }} {{ t("listing.entries") }}</span>
        </div>
        <div class="toc-tags" role="list">
          <button
            v-for="entry in visibleLocales"
            :key="`toc:${entry.row.locale}`"
            type="button"
            class="toc-tag"
            role="listitem"
            :class="{ active: activeLocale === entry.row.locale }"
            :data-status="planStatus(entry.row.locale)"
            :title="t('listing.toc_jump', { locale: catalog.labelFor(entry.row.locale) })"
            @click="scrollToLocale(entry.row.locale)"
          >
            <span class="toc-code">{{ entry.row.locale }}</span>
            <i v-if="isMissingShot(entry.row)" class="toc-dot shot" />
          </button>
        </div>
      </nav>
      <div class="preview-main">
    <section
      v-for="entry in visibleLocales"
      :id="localeAnchorId(entry.row.locale)"
      :key="entry.row.locale"
      class="card group-card"
    >
      <div
        class="list-row"
        role="button"
        tabindex="0"
        @click="openEditor(entry.index)"
        @keydown.enter.prevent="openEditor(entry.index)"
      >
        <span class="mono">{{ catalog.labelFor(entry.row.locale) }}</span>
        <span>{{ entry.row.fields.name || "—" }}</span>
        <span>{{ clip(entry.row.fields.subtitle, 30) }}</span>
        <span>{{ clip(entry.row.fields.keywords, 40) }}</span>
        <span class="badges">
          <span class="badge" :data-status="planStatus(entry.row.locale)">
            {{ t(`listing.status.${planStatus(entry.row.locale)}`) }}
          </span>
          <span v-if="isMissingShot(entry.row)" class="badge" data-status="missing-shot">
            {{ t("listing.status.missing-shot") }}
          </span>
        </span>
        <span class="row-actions" @click.stop>
          <t-button size="small" @click="openEditor(entry.index)">{{ t("common.edit") }}</t-button>
          <t-button
            v-if="workflow.compared.value && planByLocale[entry.row.locale]?.status === 'changed'"
            size="small"
            variant="outline"
            @click="pullOne(entry.row.locale)"
          >{{ t("listing.overwrite_store") }}</t-button>
        </span>
      </div>

      <div class="desc-block">
        <h3>{{ t("listing.col_description") }}</h3>
        <p v-if="descriptionText(entry.row)" class="desc-body">{{ descriptionText(entry.row) }}</p>
        <p v-else class="muted desc-empty">{{ t("listing.desc_empty") }}</p>
      </div>

      <h3>{{ t("metadata.shots_section") }}</h3>
      <div v-if="!Object.keys(entry.row.screenshots || {}).length" class="empty-shots">
        <p class="muted">{{ t("metadata.shots_empty") }}</p>
        <t-button size="small" @click="openAddShot(entry.row.locale, '')">
          <template #icon><AddIcon /></template>
          {{ t("metadata.shots_add") }}
        </t-button>
      </div>
      <div v-for="(group, dtype) in entry.row.screenshots" :key="dtype" class="shots">
        <div class="shot-head">
          <strong>{{ dtypeLabel(String(dtype)) }}</strong>
          <t-button size="small" @click="openAddShot(entry.row.locale, String(dtype))">
            <template #icon><AddIcon /></template>
            {{ t("metadata.shots_add") }}
          </t-button>
        </div>
        <div class="thumbs">
          <figure v-for="(item, idx) in group" :key="item.local_path || item.file_name" class="thumb">
            <div class="thumb-frame">
              <img :src="item.thumb_url" :alt="item.file_name" @click="openShots(group, idx)" />
            </div>
            <figcaption :title="item.file_name">{{ item.file_name }}</figcaption>
            <div class="thumb-actions">
              <t-button
                size="small"
                shape="square"
                :disabled="idx === 0"
                :title="t('metadata.shots_move_up')"
                :aria-label="t('metadata.shots_move_up')"
                @click="moveShot(entry.row.locale, String(dtype), idx, -1)"
              >
                <template #icon><ChevronUpIcon /></template>
              </t-button>
              <t-button
                size="small"
                shape="square"
                :disabled="idx === group.length - 1"
                :title="t('metadata.shots_move_down')"
                :aria-label="t('metadata.shots_move_down')"
                @click="moveShot(entry.row.locale, String(dtype), idx, 1)"
              >
                <template #icon><ChevronDownIcon /></template>
              </t-button>
              <t-button size="small" @click="openReplaceShot(item.local_path)">{{ t("metadata.shots_replace") }}</t-button>
              <t-popconfirm :content="t('metadata.shots_confirm_delete')" @confirm="deleteShot(entry.row.locale, item.local_path)">
                <t-button size="small" theme="danger" variant="outline">{{ t("metadata.shots_delete") }}</t-button>
              </t-popconfirm>
            </div>
          </figure>
        </div>
      </div>
    </section>
      </div>
    </div>

    <p v-if="!workflow.planLoading.value && listEmpty && workflow.hasContent.value" class="empty-row card">{{ emptyFilterText }}</p>

    <ListingEditorDialog
      v-if="editorDraft"
      v-model:visible="editorOpen"
      :title="t('listing.dialog_edit')"
      :draft="editorDraft"
      :plan="editorPlan"
      @confirm="applyEditor"
      @cancel="closeEditor"
      @pulled="() => { closeEditor(); void workflow.ensureCompare({ force: true }); }"
    />
    <LocalePicker v-model:open="pickerOpen" />
  </div>
</template>

<style scoped>
.preview-layout {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.preview-layout.has-toc {
  display: grid;
  grid-template-columns: minmax(148px, 188px) minmax(0, 1fr);
  align-items: start;
}
.preview-main {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.locale-toc {
  position: sticky;
  top: 0;
  z-index: 4;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  max-height: calc(100vh - var(--topbar-height) - 168px);
  overflow: auto;
}
.toc-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.toc-head strong {
  font-size: 13px;
  font-weight: 650;
}
.toc-tags {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.toc-tag {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  margin: 0;
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  text-align: left;
}
.toc-tag:hover {
  background: var(--raised);
  color: var(--text);
}
.toc-tag.active {
  background: var(--accent-glow);
  border-color: var(--accent-deep);
  color: var(--accent);
}
.toc-tag[data-status="changed"] .toc-code { color: var(--warn); }
.toc-tag[data-status="local-only"] .toc-code { color: var(--info); }
.toc-tag[data-status="equal"] .toc-code { color: var(--ok); }
.toc-tag.active[data-status="changed"],
.toc-tag.active[data-status="local-only"],
.toc-tag.active[data-status="equal"] {
  color: inherit;
}
.toc-code {
  font-family: "Fira Code", ui-monospace, monospace;
  font-size: 12px;
}
.toc-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--err);
  flex: 0 0 auto;
}
.toc-tag:focus-visible {
  outline: 2px solid var(--accent-dim);
  outline-offset: 1px;
}
@media (max-width: 900px) {
  .preview-layout.has-toc { grid-template-columns: 1fr; }
  .locale-toc { max-height: none; }
  .toc-tags { flex-direction: row; flex-wrap: wrap; }
  .toc-tag { width: auto; }
}
.edit-stack { display: flex; flex-direction: column; gap: 12px; }
.empty-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 13px;
}
.compare-progress { flex-wrap: wrap; gap: 10px 12px; }
.compare-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}
.compare-progress .meter {
  flex: 1 1 100%;
  height: 6px;
  border-radius: 99px;
  overflow: hidden;
  background: var(--overlay);
}
.compare-progress .meter i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--accent-dim), var(--accent));
  transition: width 200ms ease;
}
.compare-progress .meter.live i { box-shadow: 0 0 12px var(--accent-glow-strong); }
.toolbar { display: flex; flex-direction: column; gap: 10px; }
.filter-seg { flex-wrap: wrap; }
.filter-count {
  margin-left: 6px;
  font-size: 11px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.tree-actions, .row-actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.locale-add { min-width: 220px; flex: 1; }
.group-card { display: flex; flex-direction: column; gap: 10px; scroll-margin-top: 8px; }
.desc-block { display: flex; flex-direction: column; gap: 6px; }
.group-card > h3,
.desc-block h3 { margin: 0; font-size: 13px; }
.desc-body {
  margin: 0;
  padding: 10px 12px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.65;
  background: var(--raised);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.desc-empty { margin: 0; }
.list-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(100px, 1.2fr) minmax(80px, 1fr) minmax(80px, 1fr) minmax(90px, 0.8fr) minmax(160px, auto);
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
}
.list-row:hover { background: var(--raised); }
.mono { font-family: "Fira Code", ui-monospace, monospace; font-size: 12px; word-break: break-all; }
.badges { display: flex; flex-wrap: wrap; gap: 4px; }
.badge { font-size: 11px; color: var(--text-muted); }
.badge[data-status="changed"] { color: var(--warn); }
.badge[data-status="local-only"] { color: var(--info); }
.badge[data-status="equal"] { color: var(--ok); }
.badge[data-status="missing-shot"] { color: var(--err); }
.muted { color: var(--text-muted); font-size: 12px; }
.empty-shots { display: flex; align-items: center; gap: 12px; }
.thumbs { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
.thumb { margin: 0; width: 148px; display: flex; flex-direction: column; gap: 6px; }
.thumb-frame { position: relative; }
.thumb img { width: 148px; height: 254px; object-fit: cover; border-radius: 8px; border: 1px solid var(--border); cursor: zoom-in; display: block; }
figcaption { font-size: 11px; color: var(--text-muted); word-break: break-all; line-height: 1.3; }
.thumb-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
.thumb-actions :deep(.t-button) { margin: 0; width: 100%; }
.shot-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 8px 0; }
.file-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
  opacity: 0;
  pointer-events: none;
}
@media (max-width: 900px) {
  .list-row { grid-template-columns: 1fr; }
}
</style>
