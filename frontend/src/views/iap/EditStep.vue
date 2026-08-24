<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { AddIcon } from "tdesign-icons-vue-next";
import { MessagePlugin } from "tdesign-vue-next";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import PageLoading from "@/components/PageLoading.vue";
import { useAgent } from "@/composables/useAgent";
import { useBrowse } from "@/composables/useBrowse";
import {
  useIapWorkflow,
  type IapGroup,
  type IapItem,
  type IapSnapshot,
  type IapSubscription,
  type LocMap,
  type PlanItem,
} from "@/composables/useIapWorkflow";
import { useTaskLog } from "@/composables/useTaskLog";
import IapEditorDialog from "./IapEditorDialog.vue";
import IapReviewThumb from "./IapReviewThumb.vue";

const { t } = useI18n();
const browse = useBrowse();
const workflow = useIapWorkflow();
const { appliedTick } = useAgent();
const { channelOf } = useTaskLog();
const compareLog = channelOf(workflow.compareTaskId);

const COMPARE_PHASE_KEYS: Record<string, string> = {
  local: "iap.compare.phase_local",
  iap: "iap.compare.phase_iap",
  groups: "iap.compare.phase_groups",
  shots: "iap.compare.phase_shots",
  done: "iap.compare.phase_done",
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
  return compareLog.progress.value.phase_label || t("iap.filter.checking");
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

type EditorKind = "item" | "group" | "sub";
type EditorTarget =
  | { kind: "item"; index: number }
  | { kind: "group"; index: number }
  | { kind: "sub"; gIndex: number; sIndex: number };

const query = ref("");
const filter = ref<"all" | "local-only" | "changed" | "missing-shot">("all");
const editorOpen = ref(false);
const editorKind = ref<EditorKind>("item");
const editorTitle = ref("");
const editorDraft = ref<IapItem | IapGroup | IapSubscription | null>(null);
const editorTarget = ref<EditorTarget | null>(null);
const editorMode = ref<"add" | "edit">("edit");
const groupPickerOpen = ref(false);
const pendingGroupIndex = ref<number | undefined>(undefined);

type AddKind = "consumable" | "non_consumable" | "group" | "sub";

const hasGroups = computed(() => (workflow.snapshot.value.subscriptionGroups || []).length > 0);

const groupSelectOptions = computed(() =>
  (workflow.snapshot.value.subscriptionGroups || []).map((group, index) => ({
    label: group.referenceName || t("iap.untitled_group"),
    value: index,
  })),
);

const addTypeOptions = computed(() => [
  { content: t("iap.add_consumable"), value: "consumable" as AddKind },
  { content: t("iap.add_non_consumable"), value: "non_consumable" as AddKind },
  { content: t("iap.add_group"), value: "group" as AddKind },
  {
    content: hasGroups.value
      ? t("iap.add_sub")
      : `${t("iap.add_sub")}（${t("iap.need_group_first")}）`,
    value: "sub" as AddKind,
    disabled: !hasGroups.value,
  },
]);

const planById = computed(() => {
  const map: Record<string, PlanItem> = {};
  for (const item of workflow.planItems.value) map[item.productId] = item;
  return map;
});

function locCount(locs?: LocMap): number {
  return Object.keys(locs || {}).length;
}

function priceLabel(price?: { baseTerritory?: string; baseAmount?: string }): string {
  if (!price?.baseAmount) return "—";
  return `${price.baseAmount} ${price.baseTerritory || "USA"}`;
}

function planStatus(pid: string): string {
  if (workflow.planLoading.value || !workflow.compared.value) return "unchecked";
  const row = planById.value[pid];
  if (row?.status) return row.status;
  if (!workflow.planOk.value) return "unchecked";
  return "local-only";
}

function shotPath(shot?: string): string {
  return (shot || "").trim();
}

function isMissingShot(pid: string, shot: string): boolean {
  if (!shotPath(shot)) return true;
  if (!workflow.compared.value) return false;
  if (planById.value[pid]?.missingScreenshot) return true;
  return !!workflow.missingOnStore.value[pid];
}

function matchesQuery(label: string, pid: string): boolean {
  const q = query.value.trim().toLowerCase();
  if (!q) return true;
  return label.toLowerCase().includes(q) || pid.toLowerCase().includes(q);
}

function matchesFilter(pid: string, shot: string): boolean {
  if (filter.value === "all") return true;
  if (filter.value === "missing-shot") return isMissingShot(pid, shot);
  const status = planStatus(pid);
  if (filter.value === "local-only") return status === "local-only";
  if (filter.value === "changed") return status === "changed";
  return true;
}

type ProductEntry = { pid: string; shot: string };

function allProductEntries(): ProductEntry[] {
  const snap = workflow.snapshot.value;
  const rows: ProductEntry[] = [];
  for (const item of snap.items || []) {
    rows.push({ pid: item.productId, shot: shotPath(item.review?.screenshot) });
  }
  for (const group of snap.subscriptionGroups || []) {
    for (const sub of group.subscriptions || []) {
      rows.push({ pid: sub.productId, shot: shotPath(sub.review?.screenshot) });
    }
  }
  return rows;
}

const filterCounts = computed(() => {
  const rows = allProductEntries();
  let local = 0;
  let changed = 0;
  let shot = 0;
  for (const row of rows) {
    const status = planStatus(row.pid);
    if (status === "local-only") local += 1;
    if (status === "changed") changed += 1;
    if (isMissingShot(row.pid, row.shot)) shot += 1;
  }
  return { all: rows.length, local, changed, shot };
});

const storeReady = computed(() => workflow.compared.value);
const filterOptions = computed(() => [
  { value: "all" as const, label: t("iap.filter.all"), count: filterCounts.value.all, disabled: false },
  {
    value: "local-only" as const,
    label: t("iap.filter.local"),
    count: storeReady.value ? filterCounts.value.local : null,
    disabled: !storeReady.value,
  },
  {
    value: "changed" as const,
    label: t("iap.filter.changed"),
    count: storeReady.value ? filterCounts.value.changed : null,
    disabled: !storeReady.value,
  },
  { value: "missing-shot" as const, label: t("iap.filter.shot"), count: filterCounts.value.shot, disabled: false },
]);

const visibleGroups = computed(() => {
  const snap = workflow.snapshot.value;
  return (snap.subscriptionGroups || [])
    .map((group, gIndex) => {
      const subs = (group.subscriptions || [])
        .map((sub, sIndex) => ({ sub, sIndex }))
        .filter(({ sub }) => {
          const label = sub.name || sub.productId;
          const shot = shotPath(sub.review?.screenshot);
          return matchesQuery(label, sub.productId) && matchesFilter(sub.productId, shot);
        });
      const groupHit = matchesQuery(group.referenceName || t("iap.untitled_group"), "");
      if (!groupHit && !subs.length) return null;
      if (filter.value !== "all" && !subs.length && !groupHit) return null;
      if (filter.value !== "all" && !subs.length) return null;
      return { group, gIndex, subs };
    })
    .filter((row): row is { group: IapGroup; gIndex: number; subs: Array<{ sub: IapSubscription; sIndex: number }> } => !!row);
});

const visibleItems = computed(() => {
  return (workflow.snapshot.value.items || [])
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => {
      const label = item.name || item.productId;
      const shot = shotPath(item.review?.screenshot);
      return matchesQuery(label, item.productId) && matchesFilter(item.productId, shot);
    });
});

const listEmpty = computed(
  () => !visibleGroups.value.length && !visibleItems.value.length,
);

const emptyFilterText = computed(() => {
  if (query.value.trim()) return t("iap.tree_empty");
  if (filter.value === "local-only" || filter.value === "changed") {
    if (!workflow.compared.value) return t("iap.filter.need_compare");
    if (!workflow.planOk.value) return t("iap.filter.plan_failed");
  }
  if (filter.value === "local-only") return t("iap.filter.empty_local");
  if (filter.value === "changed") return t("iap.filter.empty_changed");
  if (filter.value === "missing-shot") return t("iap.filter.empty_shot");
  return t("iap.pick_or_add");
});

function touch() {
  workflow.markDirty();
}

async function loadPlan(force = false) {
  await workflow.ensureCompare({ force });
}

function refreshStore() {
  void workflow.ensureCompare({ force: true });
}

onMounted(async () => {
  if (!workflow.loaded.value && !workflow.emptyProfile.value) await workflow.load();
});

watch(appliedTick, () => {
  editorOpen.value = false;
  editorDraft.value = null;
  editorTarget.value = null;
  groupPickerOpen.value = false;
  pendingGroupIndex.value = undefined;
});

watch(storeReady, (ready) => {
  if (!ready && (filter.value === "local-only" || filter.value === "changed")) {
    filter.value = "all";
  }
});

async function openExistingJson() {
  const path = await browse.pick({ mode: "file", ext: ".json", initialPath: workflow.iapFile.value });
  if (!path) return;
  workflow.setIapFile(path);
  await workflow.load(path);
}

function cloneOf<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function openEditor(kind: EditorKind, draft: IapItem | IapGroup | IapSubscription, target: EditorTarget, title: string, mode: "add" | "edit") {
  editorKind.value = kind;
  editorDraft.value = cloneOf(draft);
  editorTarget.value = target;
  editorTitle.value = title;
  editorMode.value = mode;
  editorOpen.value = true;
  workflow.selectedKey.value =
    target.kind === "item"
      ? `item:${target.index}`
      : target.kind === "group"
        ? `group:${target.index}`
        : `sub:${target.gIndex}:${target.sIndex}`;
}

function addItem(type: "CONSUMABLE" | "NON_CONSUMABLE") {
  const n = (workflow.snapshot.value.items?.length || 0) + 1;
  const draft: IapItem = {
    productId: `com.example.item.${n}`,
    name: type === "CONSUMABLE" ? "Consumable" : "Non-Consumable",
    inAppPurchaseType: type,
    localizations: { "en-US": { name: "New item", description: "Description" } },
    review: { screenshot: "", note: "" },
  };
  const title = type === "CONSUMABLE" ? t("iap.dialog_add_consumable") : t("iap.dialog_add_non_consumable");
  openEditor("item", draft, { kind: "item", index: -1 }, title, "add");
}

function addGroup() {
  const draft: IapGroup = {
    referenceName: "New Group",
    localizations: { "en-US": { name: "Premium" } },
    subscriptions: [],
  };
  openEditor("group", draft, { kind: "group", index: -1 }, t("iap.dialog_add_group"), "add");
}

function onAddType(item: string | number | { value?: string | number } | undefined) {
  const value = typeof item === "object" && item ? item.value : item;
  switch (value) {
    case "consumable":
      addItem("CONSUMABLE");
      break;
    case "non_consumable":
      addItem("NON_CONSUMABLE");
      break;
    case "group":
      addGroup();
      break;
    case "sub":
      openGroupPicker();
      break;
    default:
      break;
  }
}

function openGroupPicker() {
  const groups = workflow.snapshot.value.subscriptionGroups || [];
  if (!groups.length) return;
  pendingGroupIndex.value = groups.length === 1 ? 0 : undefined;
  groupPickerOpen.value = true;
}

function closeGroupPicker() {
  groupPickerOpen.value = false;
  pendingGroupIndex.value = undefined;
}

function confirmGroupAndAdd() {
  const gi = Number(pendingGroupIndex.value);
  if (!Number.isInteger(gi) || gi < 0) return;
  closeGroupPicker();
  addSubscription(gi);
}

function addSubscription(gIndex: number) {
  const groups = workflow.snapshot.value.subscriptionGroups || [];
  if (gIndex < 0 || gIndex >= groups.length) return;
  const group = groups[gIndex];
  const n = (group.subscriptions?.length || 0) + 1;
  const draft: IapSubscription = {
    productId: `com.example.sub.${n}`,
    name: "Monthly",
    subscriptionPeriod: "ONE_MONTH",
    localizations: { "en-US": { name: "Monthly", description: "Full access." } },
    review: { screenshot: "", note: "" },
  };
  openEditor("sub", draft, { kind: "sub", gIndex, sIndex: -1 }, t("iap.dialog_add_sub"), "add");
}

function editGroup(gIndex: number) {
  const group = workflow.snapshot.value.subscriptionGroups[gIndex];
  openEditor("group", group, { kind: "group", index: gIndex }, t("iap.dialog_edit"), "edit");
}

function editItem(index: number) {
  const item = workflow.snapshot.value.items[index];
  openEditor("item", item, { kind: "item", index }, t("iap.dialog_edit"), "edit");
}

function editSub(gIndex: number, sIndex: number) {
  const sub = workflow.snapshot.value.subscriptionGroups[gIndex].subscriptions![sIndex];
  openEditor("sub", sub, { kind: "sub", gIndex, sIndex }, t("iap.dialog_edit"), "edit");
}

function applyEditor() {
  const draft = editorDraft.value;
  const target = editorTarget.value;
  if (!draft || !target) return closeEditor();
  const snap = workflow.snapshot.value;
  if (editorMode.value === "add") {
    if (target.kind === "item") {
      snap.items = snap.items || [];
      snap.items.push(draft as IapItem);
    } else if (target.kind === "group") {
      snap.subscriptionGroups = snap.subscriptionGroups || [];
      snap.subscriptionGroups.push(draft as IapGroup);
    } else {
      const group = snap.subscriptionGroups[target.gIndex];
      group.subscriptions = group.subscriptions || [];
      group.subscriptions.push(draft as IapSubscription);
    }
  } else if (target.kind === "item") {
    snap.items[target.index] = draft as IapItem;
  } else if (target.kind === "group") {
    const prev = snap.subscriptionGroups[target.index];
    snap.subscriptionGroups[target.index] = {
      ...(draft as IapGroup),
      subscriptions: prev.subscriptions,
    };
  } else {
    snap.subscriptionGroups[target.gIndex].subscriptions![target.sIndex] = draft as IapSubscription;
  }
  touch();
  closeEditor();
}

function closeEditor() {
  editorOpen.value = false;
  editorDraft.value = null;
  editorTarget.value = null;
}

function removeItem(index: number) {
  workflow.snapshot.value.items.splice(index, 1);
  touch();
}

function removeGroup(index: number) {
  workflow.snapshot.value.subscriptionGroups.splice(index, 1);
  touch();
}

function removeSub(gIndex: number, sIndex: number) {
  workflow.snapshot.value.subscriptionGroups[gIndex].subscriptions?.splice(sIndex, 1);
  touch();
}

function copyItem(index: number) {
  const copy = cloneOf(workflow.snapshot.value.items[index]);
  copy.productId = `${copy.productId}.copy`;
  workflow.snapshot.value.items.push(copy);
  touch();
}

function copySub(gIndex: number, sIndex: number) {
  const group = workflow.snapshot.value.subscriptionGroups[gIndex];
  const copy = cloneOf(group.subscriptions![sIndex]);
  copy.productId = `${copy.productId}.copy`;
  group.subscriptions = group.subscriptions || [];
  group.subscriptions.push(copy);
  touch();
}

const editorPlan = computed(() => {
  const target = editorTarget.value;
  if (editorMode.value !== "edit" || !target || target.kind === "group") return undefined;
  const pid = target.kind === "item"
    ? workflow.snapshot.value.items[target.index]?.productId
    : workflow.snapshot.value.subscriptionGroups[target.gIndex]?.subscriptions?.[target.sIndex]?.productId;
  return pid ? planById.value[pid] : undefined;
});

async function pullOne(pid: string) {
  if (!pid) return;
  try {
    const data = await httpJson<{ snapshot: IapSnapshot }>("/api/iap/pull", {
      method: "POST",
      body: JSON.stringify({
        iapFile: workflow.iapFile.value,
        productIds: [pid],
        expected_mtime: workflow.mtime.value,
        write: false,
      }),
    });
    workflow.applySnapshot(data.snapshot, { dirty: true, storeDraft: true });
    await loadPlan(true);
  } catch (err) {
    const message = err instanceof ApiError ? apiErrorMessage(err) : String(err);
    MessagePlugin.error(message);
  }
}

function typeLabel(item: IapItem): string {
  if (item.inAppPurchaseType === "NON_CONSUMABLE") return t("iap.kind_non_consumable");
  if (item.inAppPurchaseType === "NON_RENEWING_SUBSCRIPTION") return t("iap.kind_non_renewing");
  return t("iap.kind_consumable");
}

function groupLevelLabel(level?: number | null): string {
  return typeof level === "number" && Number.isFinite(level) && level >= 1 ? String(level) : "—";
}

function currentPlan(pid: string): PlanItem | undefined {
  return planById.value[pid];
}
</script>

<template>
  <div class="edit-stack">
    <p v-if="!workflow.hasContent.value" class="empty-row card">
      {{ t("iap.empty_open") }}
      <t-button size="small" @click="openExistingJson">{{ t("iap.source.json") }}</t-button>
    </p>
    <div class="card toolbar">
      <t-input v-model="query" :placeholder="t('iap.search')" />
      <t-radio-group v-model="filter" variant="default-filled" size="small" class="filter-seg">
        <t-radio-button
          v-for="opt in filterOptions"
          :key="opt.value"
          :value="opt.value"
          :disabled="opt.disabled"
          :title="opt.disabled ? t('iap.filter.need_compare') : undefined"
        >
          {{ opt.label }}
          <span v-if="opt.count != null" class="filter-count">{{ opt.count }}</span>
        </t-radio-button>
      </t-radio-group>
      <div class="tree-actions">
        <t-button
          size="small"
          variant="outline"
          :disabled="workflow.emptyProfile.value || workflow.planLoading.value"
          @click="refreshStore"
        >
          {{ workflow.compared.value ? t("iap.compare.refresh") : t("iap.compare.button") }}
        </t-button>
        <t-dropdown
          :options="addTypeOptions"
          :min-column-width="220"
          trigger="click"
          :popup-props="{ attach: 'body' }"
          @click="onAddType"
        >
          <t-button size="small" theme="primary">
            <template #icon><AddIcon /></template>
            {{ t("iap.add") }}
          </t-button>
        </t-dropdown>
      </div>
      <p v-if="!workflow.planOk.value && !workflow.planLoading.value" class="muted">
        {{ workflow.planError.value || t("iap.plan_unchecked") }}
      </p>
      <p v-else-if="!workflow.compared.value && !workflow.planLoading.value" class="muted">
        {{ t("iap.filter.need_compare") }}
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
        <span class="muted">{{ t("iap.compare.elapsed", { s: compareElapsed }) }}</span>
      </div>
      <div class="meter" :class="{ live: true }">
        <i :style="{ width: `${comparePct}%` }" />
      </div>
    </div>

    <section v-for="row in visibleGroups" :key="`group:${row.gIndex}`" class="card group-card">
      <header class="group-head">
        <div>
          <h3>{{ row.group.referenceName || t("iap.untitled_group") }}</h3>
          <p class="muted">{{ locCount(row.group.localizations) }} {{ t("iap.col_locales") }}</p>
        </div>
        <div class="row-actions" @click.stop>
          <t-button size="small" @click="addSubscription(row.gIndex)">{{ t("iap.add_sub") }}</t-button>
          <t-button size="small" @click="editGroup(row.gIndex)">{{ t("common.edit") }}</t-button>
          <t-popconfirm :content="t('iap.confirm_delete_group')" @confirm="removeGroup(row.gIndex)">
            <t-button size="small" theme="danger" variant="outline">{{ t("common.delete") }}</t-button>
          </t-popconfirm>
        </div>
      </header>
      <div class="list-table">
        <div class="list-head list-head-sub">
          <span>{{ t("iap.col_product") }}</span>
          <span>{{ t("iap.col_name") }}</span>
          <span>{{ t("iap.period") }}</span>
          <span>{{ t("iap.col_group_level") }}</span>
          <span>{{ t("iap.col_price") }}</span>
          <span>{{ t("iap.col_locales") }}</span>
          <span>{{ t("iap.col_shot") }}</span>
          <span>{{ t("iap.col_status") }}</span>
          <span />
        </div>
        <div
          v-for="entry in row.subs"
          :key="`sub:${row.gIndex}:${entry.sIndex}`"
          class="list-row list-row-sub"
          role="button"
          tabindex="0"
          @click="editSub(row.gIndex, entry.sIndex)"
          @keydown.enter.prevent="editSub(row.gIndex, entry.sIndex)"
        >
          <span class="mono">{{ entry.sub.productId }}</span>
          <span>{{ entry.sub.name || "—" }}</span>
          <span>{{ entry.sub.subscriptionPeriod || "—" }}</span>
          <span>{{ groupLevelLabel(entry.sub.groupLevel) }}</span>
          <span>{{ priceLabel(entry.sub.price) }}</span>
          <span>{{ locCount(entry.sub.localizations) }}</span>
          <span class="shot-cell" @click.stop>
            <IapReviewThumb :path="shotPath(entry.sub.review?.screenshot)" />
          </span>
          <span class="badges">
            <span class="badge" :data-status="planStatus(entry.sub.productId)">
              {{ t(`iap.status.${planStatus(entry.sub.productId)}`) }}
            </span>
            <span v-if="isMissingShot(entry.sub.productId, shotPath(entry.sub.review?.screenshot))" class="badge" data-status="missing-shot">
              {{ t("iap.status.missing-shot") }}
            </span>
          </span>
          <span class="row-actions" @click.stop>
            <t-button size="small" @click="editSub(row.gIndex, entry.sIndex)">{{ t("common.edit") }}</t-button>
            <t-button size="small" variant="outline" @click="copySub(row.gIndex, entry.sIndex)">{{ t("iap.copy") }}</t-button>
            <t-button
              v-if="workflow.compared.value && currentPlan(entry.sub.productId)?.status === 'changed'"
              size="small"
              variant="outline"
              @click="pullOne(entry.sub.productId)"
            >{{ t("iap.overwrite_store") }}</t-button>
            <t-popconfirm :content="t('iap.confirm_delete')" @confirm="removeSub(row.gIndex, entry.sIndex)">
              <t-button size="small" theme="danger" variant="outline">{{ t("common.delete") }}</t-button>
            </t-popconfirm>
          </span>
        </div>
        <p v-if="!row.subs.length" class="muted nested-empty">{{ t("iap.tree_empty") }}</p>
      </div>
    </section>

    <section v-if="visibleItems.length" class="card group-card">
      <header class="group-head">
        <h3>{{ t("iap.section_items") }}</h3>
      </header>
      <div class="list-table">
        <div class="list-head list-head-item">
          <span>{{ t("iap.col_product") }}</span>
          <span>{{ t("iap.col_name") }}</span>
          <span>{{ t("iap.type") }}</span>
          <span>{{ t("iap.col_price") }}</span>
          <span>{{ t("iap.col_locales") }}</span>
          <span>{{ t("iap.col_shot") }}</span>
          <span>{{ t("iap.col_status") }}</span>
          <span />
        </div>
        <div
          v-for="entry in visibleItems"
          :key="`item:${entry.index}`"
          class="list-row list-row-item"
          role="button"
          tabindex="0"
          @click="editItem(entry.index)"
          @keydown.enter.prevent="editItem(entry.index)"
        >
          <span class="mono">{{ entry.item.productId }}</span>
          <span>{{ entry.item.name || "—" }}</span>
          <span>{{ typeLabel(entry.item) }}</span>
          <span>{{ priceLabel(entry.item.price) }}</span>
          <span>{{ locCount(entry.item.localizations) }}</span>
          <span class="shot-cell" @click.stop>
            <IapReviewThumb :path="shotPath(entry.item.review?.screenshot)" />
          </span>
          <span class="badges">
            <span class="badge" :data-status="planStatus(entry.item.productId)">
              {{ t(`iap.status.${planStatus(entry.item.productId)}`) }}
            </span>
            <span v-if="isMissingShot(entry.item.productId, shotPath(entry.item.review?.screenshot))" class="badge" data-status="missing-shot">
              {{ t("iap.status.missing-shot") }}
            </span>
          </span>
          <span class="row-actions" @click.stop>
            <t-button size="small" @click="editItem(entry.index)">{{ t("common.edit") }}</t-button>
            <t-button size="small" variant="outline" @click="copyItem(entry.index)">{{ t("iap.copy") }}</t-button>
            <t-button
              v-if="workflow.compared.value && currentPlan(entry.item.productId)?.status === 'changed'"
              size="small"
              variant="outline"
              @click="pullOne(entry.item.productId)"
            >{{ t("iap.overwrite_store") }}</t-button>
            <t-popconfirm :content="t('iap.confirm_delete')" @confirm="removeItem(entry.index)">
              <t-button size="small" theme="danger" variant="outline">{{ t("common.delete") }}</t-button>
            </t-popconfirm>
          </span>
        </div>
      </div>
    </section>

    <p v-if="!workflow.planLoading.value && listEmpty && workflow.hasContent.value" class="empty-row card">{{ emptyFilterText }}</p>

    <t-dialog
      :visible="groupPickerOpen"
      :header="t('iap.pick_group_title')"
      width="420px"
      placement="center"
      attach="body"
      :close-on-overlay-click="true"
      @update:visible="(open: boolean) => { if (!open) closeGroupPicker(); }"
    >
      <label class="field">
        {{ t("iap.pick_group") }}
        <t-select
          v-model="pendingGroupIndex"
          :placeholder="t('iap.pick_group')"
          :options="groupSelectOptions"
        />
      </label>
      <template #footer>
        <t-button variant="outline" @click="closeGroupPicker">{{ t("common.cancel") }}</t-button>
        <t-button theme="primary" :disabled="pendingGroupIndex === undefined" @click="confirmGroupAndAdd">
          {{ t("iap.dialog_ok") }}
        </t-button>
      </template>
    </t-dialog>

    <IapEditorDialog
      v-if="editorDraft"
      v-model:visible="editorOpen"
      :kind="editorKind"
      :title="editorTitle"
      :draft="editorDraft"
      :plan="editorPlan"
      @confirm="applyEditor"
      @cancel="closeEditor"
      @pulled="() => { closeEditor(); void loadPlan(true); }"
    />
  </div>
</template>

<style scoped>
.edit-stack { display: flex; flex-direction: column; gap: 12px; }
.empty-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 13px;
}
.compare-progress {
  flex-wrap: wrap;
  gap: 10px 12px;
}
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
.compare-progress .meter.live i {
  box-shadow: 0 0 12px var(--accent-glow-strong);
}
.toolbar { display: flex; flex-direction: column; gap: 10px; }
.filter-seg { flex-wrap: wrap; }
.filter-count {
  margin-left: 6px;
  font-size: 11px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.filter-seg :deep(.t-radio-button.t-is-checked) .filter-count {
  color: inherit;
  opacity: 0.72;
}
.tree-actions, .row-actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.field { display: flex; flex-direction: column; gap: 6px; }
.group-card { display: flex; flex-direction: column; gap: 10px; }
.group-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.group-head h3 { margin: 0; font-size: 15px; }
.group-head p { margin: 4px 0 0; }
.list-table { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.list-head, .list-row {
  display: grid;
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  text-align: left;
}
.list-head-sub, .list-row-sub {
  grid-template-columns: minmax(140px, 1.4fr) minmax(90px, 1fr) minmax(70px, 0.7fr) 72px minmax(70px, 0.6fr) 56px 44px minmax(80px, 0.7fr) minmax(180px, auto);
}
.list-head-item, .list-row-item {
  grid-template-columns: minmax(140px, 1.4fr) minmax(90px, 1fr) minmax(70px, 0.7fr) minmax(70px, 0.6fr) 56px 44px minmax(80px, 0.7fr) minmax(180px, auto);
}
.shot-cell {
  display: flex;
  align-items: center;
}
.list-head {
  font-size: 11px;
  color: var(--text-muted);
  background: var(--raised);
  border-bottom: 1px solid var(--border);
}
.list-row {
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--border);
  color: inherit;
  cursor: pointer;
  font: inherit;
}
.list-row:last-of-type { border-bottom: 0; }
.list-row:hover { background: var(--raised); }
.mono { font-family: "Fira Code", ui-monospace, monospace; font-size: 12px; word-break: break-all; }
.badges { display: flex; flex-wrap: wrap; gap: 4px; }
.badge { font-size: 11px; color: var(--text-muted); }
.badge[data-status="changed"] { color: var(--warn); }
.badge[data-status="local-only"] { color: var(--info); }
.badge[data-status="equal"] { color: var(--ok); }
.badge[data-status="missing-shot"] { color: var(--err); }
.muted { color: var(--text-muted); font-size: 12px; }
.nested-empty { margin: 0; padding: 10px; }
@media (max-width: 900px) {
  .list-head { display: none; }
  .list-row {
    grid-template-columns: 1fr;
    justify-items: start;
  }
}
</style>
