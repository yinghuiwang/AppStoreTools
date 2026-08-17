<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { CircleCheck, CircleClose, Loading, Plus, Promotion, VideoPause } from "@element-plus/icons-vue";
import { useAgent, type AgentMessage, type AgentPlan } from "@/composables/useAgent";
import { useRightRail } from "@/composables/useRightRail";
import PageLoading from "@/components/PageLoading.vue";

const { t } = useI18n();
const {
  sessionId,
  boundTaskId,
  messages,
  generating,
  send,
  stop,
  bindTask,
  apply,
  reject,
  searchFailed,
  restoreMessages,
} = useAgent();
const rail = useRightRail();
const draft = ref("");
const attachOpen = ref(false);
const search = ref("");
const results = ref<Array<Record<string, unknown>>>([]);
const rerunByPlan = ref<Record<string, boolean>>({});
const scroller = ref<HTMLElement | null>(null);
const draftEl = ref<HTMLTextAreaElement | null>(null);
const attachWrap = ref<HTMLElement | null>(null);
const openTools = ref<string[]>([]);
const openThinks = ref<string[]>([]);
const COMPOSER_LINE = 20;
const COMPOSER_PAD_Y = 8;
const COMPOSER_MIN_ROWS = 2;
const COMPOSER_MAX_ROWS = 6;
const COMPOSER_MIN = COMPOSER_PAD_Y * 2 + COMPOSER_LINE * COMPOSER_MIN_ROWS;
const COMPOSER_MAX = COMPOSER_PAD_Y * 2 + COMPOSER_LINE * COMPOSER_MAX_ROWS;

function renderMd(text: string): string {
  const html = marked.parse(text || "", { async: false, gfm: true, breaks: true }) as string;
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}

function shortId(value: unknown): string {
  const text = String(value || "");
  return text.length <= 10 ? text : text.slice(0, 8);
}

function trunc(value: unknown, max: number): string {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? "");
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function mutationLine(mutation: Record<string, unknown>): string {
  const op = String(mutation.op || "");
  const path = String(mutation.path || "");
  const before = mutation.before != null ? trunc(mutation.before, 80) : "";
  let after = "";
  if (mutation.fields != null) after = trunc(mutation.fields, 80);
  else if (mutation.after != null) after = trunc(mutation.after, 80);
  else if (mutation.value != null) after = trunc(mutation.value, 80);
  else if (mutation.action) after = String(mutation.action);
  let line = `${op} ${path}`.trim();
  if (before || after) line += `  ${before} → ${after}`;
  return line;
}

function planStatusLabel(status: string): string {
  const key = `agent.${status}`;
  const label = t(key);
  return label === key ? status : label;
}

function canAct(plan: AgentPlan): boolean {
  return plan.status === "pending" || plan.status === "conflict";
}

function toolStatusLabel(status: string): string {
  if (status === "running") return t("agent.tool.running");
  if (status === "success") return t("agent.tool.success");
  return t("agent.tool.failed");
}

function isTool(msg: AgentMessage): msg is Extract<AgentMessage, { kind: "tool" }> {
  return msg.kind === "tool";
}

function toolOpenNames(id: string): string[] {
  return openTools.value.includes(id) ? [id] : [];
}

function onToolToggle(id: string, names: string[] | string) {
  const list = Array.isArray(names) ? names : [names];
  const open = list.map(String).includes(id);
  const next = openTools.value.filter((item) => item !== id);
  if (open) next.push(id);
  openTools.value = next;
}

function thinkName(idx: number): string {
  return `think-${idx}`;
}

function thinkOpenNames(idx: number): string[] {
  const name = thinkName(idx);
  return openThinks.value.includes(name) ? [name] : [];
}

function onThinkToggle(idx: number, names: string[] | string) {
  const name = thinkName(idx);
  const list = Array.isArray(names) ? names : [names];
  const open = list.map(String).includes(name);
  const next = openThinks.value.filter((item) => item !== name);
  if (open) next.push(name);
  openThinks.value = next;
}

function autosizeDraft() {
  const el = draftEl.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(Math.max(el.scrollHeight, COMPOSER_MIN), COMPOSER_MAX)}px`;
}

function closeAttach() {
  attachOpen.value = false;
}

function toggleAttach() {
  attachOpen.value = !attachOpen.value;
  if (attachOpen.value) void runSearch();
}

function onDocPointerDown(event: PointerEvent) {
  if (!attachOpen.value) return;
  const root = attachWrap.value;
  if (root && event.target instanceof Node && root.contains(event.target)) return;
  closeAttach();
}

function onDocKeydown(event: KeyboardEvent) {
  if (event.key === "Escape" && attachOpen.value) closeAttach();
}

const boundSummary = computed(() => {
  const bits: string[] = [];
  if (boundTaskId.value) bits.push(shortId(boundTaskId.value));
  if (sessionId.value) bits.push(shortId(sessionId.value));
  return bits.join(" · ");
});

const panelOpen = computed(() => rail.open.value && rail.tab.value === "agent");

async function onSubmit() {
  const text = draft.value.trim();
  if (!text || generating.value) return;
  draft.value = "";
  await nextTick();
  autosizeDraft();
  messages.value = [...messages.value, { kind: "user", text }];
  await send({ message: text });
}

function onComposerKeydown(event: KeyboardEvent) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  void onSubmit();
}

async function runSearch() {
  try {
    results.value = await searchFailed(search.value.trim());
  } catch {
    results.value = [];
  }
}

function onSearchInput() {
  void runSearch();
}

function pickTask(id: unknown) {
  closeAttach();
  if (id) void bindTask(String(id), { autoAnalyze: true });
}

function applyPlan(plan: AgentPlan) {
  const rerun = rerunByPlan.value[plan.id] !== false;
  void apply(plan.id, Boolean(plan.rerun) && rerun);
}

watch(
  () => messages.value.map((msg) => (isTool(msg) ? `${msg.id}:${msg.status}` : "")).join("|"),
  () => {
    const running = messages.value.filter(isTool).filter((msg) => msg.status === "running").map((msg) => msg.id);
    const seen = new Set(openTools.value);
    for (const id of running) {
      if (!seen.has(id)) openTools.value = [...openTools.value, id];
    }
  },
);

watch(
  () => messages.value.length,
  async () => {
    await nextTick();
    const el = scroller.value;
    if (el) el.scrollTop = el.scrollHeight;
  },
);

onMounted(() => {
  if (rail.sessionId.value) sessionId.value = rail.sessionId.value;
  if (rail.boundTaskId.value) boundTaskId.value = rail.boundTaskId.value;
  document.addEventListener("pointerdown", onDocPointerDown);
  document.addEventListener("keydown", onDocKeydown);
  void restoreMessages();
  void nextTick(autosizeDraft);
});

onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onDocPointerDown);
  document.removeEventListener("keydown", onDocKeydown);
});
</script>

<template>
  <div class="agent" data-agent-panel :class="{ 'is-open': panelOpen }">
    <header class="toolbar">
      <div class="lead">
        <span class="title mono" data-agent-title>{{ t("nav.agent") }}</span>
        <div v-if="boundSummary" class="bound mono" data-agent-bound>{{ boundSummary }}</div>
      </div>
      <button
        type="button"
        class="icon"
        data-agent-close
        :aria-label="t('agent.close')"
        @click="rail.collapse()"
      >
        ×
      </button>
    </header>
    <div ref="scroller" class="messages" data-agent-messages>
      <p v-if="!messages.length" class="empty agent-dock-empty">{{ t("agent.empty") }}</p>
      <template v-for="(msg, idx) in messages" :key="idx">
        <div v-if="msg.kind === 'user'" class="bubble user">{{ msg.text }}</div>
        <article
          v-else-if="msg.kind === 'thinking' && msg.text.trim()"
          class="thinking"
          data-agent-thinking
          :data-agent-thinking-open="thinkOpenNames(idx).length ? 'true' : 'false'"
        >
          <el-collapse
            :model-value="thinkOpenNames(idx)"
            @update:model-value="onThinkToggle(idx, $event)"
          >
            <el-collapse-item :name="thinkName(idx)">
              <template #title>
                <span class="thinking-title" data-agent-thinking-title>
                  {{ msg.streaming ? t("agent.thinking") : t("agent.thinking_done") }}
                </span>
              </template>
              <pre
                v-if="openThinks.includes(thinkName(idx))"
                class="thinking-body"
                data-agent-thinking-body
              >{{ msg.text }}</pre>
            </el-collapse-item>
          </el-collapse>
        </article>
        <article
          v-else-if="msg.kind === 'tool'"
          class="tool-card"
          :data-agent-tool="msg.id"
        >
          <el-collapse
            :model-value="toolOpenNames(msg.id)"
            @update:model-value="onToolToggle(msg.id, $event)"
          >
            <el-collapse-item :name="msg.id">
              <template #title>
                <span class="tool-head">
                  <el-icon v-if="msg.status === 'running'" class="is-loading" :size="14">
                    <Loading />
                  </el-icon>
                  <el-icon v-else-if="msg.status === 'success'" class="ok" :size="14">
                    <CircleCheck />
                  </el-icon>
                  <el-icon v-else class="err" :size="14">
                    <CircleClose />
                  </el-icon>
                  <span class="tool-name mono" data-agent-tool-name>{{ msg.name }}</span>
                  <span class="tool-status" :data-agent-tool-status="msg.status">
                    {{ toolStatusLabel(msg.status) }}
                  </span>
                </span>
              </template>
              <pre v-if="msg.summary" class="tool-summary" data-agent-tool-summary>{{ msg.summary }}</pre>
            </el-collapse-item>
          </el-collapse>
        </article>
        <div
          v-else-if="msg.kind === 'assistant'"
          class="bubble assistant"
          v-html="renderMd(msg.text)"
        />
        <div v-else-if="msg.kind === 'error'" class="bubble error">{{ msg.text }}</div>
        <article v-else-if="msg.kind === 'plan'" class="plan" :data-agent-plan="msg.plan.id">
          <p class="plan-summary">{{ msg.plan.summary }}</p>
          <div
            v-for="(mutation, mi) in msg.plan.mutations"
            :key="mi"
            class="mutation mono"
          >
            {{ mutationLine(mutation) }}
          </div>
          <div v-for="(step, si) in msg.plan.manual_steps || []" :key="'s' + si" class="mutation">
            {{ step }}
          </div>
          <p v-if="msg.plan.rerun?.task_id" class="mutation mono">
            {{ msg.plan.rerun.kind || "" }} · {{ shortId(msg.plan.rerun.task_id) }}
          </p>
          <p v-if="msg.plan.status && msg.plan.status !== 'pending'" data-agent-plan-status>
            {{ planStatusLabel(msg.plan.status) }}
            <template v-if="msg.plan.error"> — {{ msg.plan.error }}</template>
          </p>
          <div v-if="canAct(msg.plan)" class="plan-actions">
            <label v-if="msg.plan.rerun">
              <input
                type="checkbox"
                :checked="rerunByPlan[msg.plan.id] !== false"
                @change="rerunByPlan[msg.plan.id] = ($event.target as HTMLInputElement).checked"
              />
              {{ t("agent.rerun_after_apply") }}
            </label>
            <button
              v-if="msg.plan.mutations.length"
              type="button"
              @click="applyPlan(msg.plan)"
            >
              {{ t("agent.apply") }}
            </button>
            <button type="button" @click="reject(msg.plan.id)">{{ t("agent.ignore") }}</button>
          </div>
        </article>
      </template>
      <PageLoading v-if="generating" size="inline" :text="t('agent.generating')" />
    </div>
    <div class="composer">
      <div class="row">
        <div ref="attachWrap" class="attach" data-agent-attach-wrap>
          <button
            type="button"
            class="plus"
            data-agent-attach
            :aria-expanded="attachOpen ? 'true' : 'false'"
            :aria-label="t('agent.attach')"
            :title="t('agent.attach')"
            @click="toggleAttach"
          >
            <el-icon :size="16"><Plus /></el-icon>
          </button>
          <div v-show="attachOpen" class="menu" data-agent-attach-menu>
            <p>{{ t("agent.attach_task") }}</p>
            <input
              v-model="search"
              type="search"
              class="search"
              data-agent-task-search
              :placeholder="t('agent.search_placeholder')"
              autocomplete="off"
              @input="onSearchInput"
            />
            <div v-if="results.length" class="results" data-agent-search-results>
              <button
                v-for="task in results"
                :key="String(task.id)"
                type="button"
                @click="pickTask(task.id)"
              >
                {{ [task.title || task.kind, shortId(task.id), task.profile].filter(Boolean).join(" · ") }}
              </button>
            </div>
          </div>
        </div>
        <form data-agent-stream @submit.prevent="onSubmit">
          <textarea
            ref="draftEl"
            v-model="draft"
            name="message"
            rows="2"
            class="draft"
            data-agent-input
            :placeholder="t('agent.composer_placeholder')"
            autocomplete="off"
            @keydown="onComposerKeydown"
            @input="autosizeDraft"
          />
          <button
            v-if="generating"
            type="button"
            class="send"
            data-agent-stop
            :title="t('agent.stop')"
            :aria-label="t('agent.stop')"
            @click="stop()"
          >
            <el-icon :size="16"><VideoPause /></el-icon>
          </button>
          <button
            v-else
            type="submit"
            class="send"
            data-agent-send
            :title="t('agent.send')"
            :aria-label="t('agent.send')"
          >
            <el-icon :size="16"><Promotion /></el-icon>
          </button>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}

.lead {
  min-width: 0;
}

.title {
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.04em;
}

.bound {
  color: var(--text-faint);
  font-size: 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.icon {
  background: transparent;
  border: 0;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
}

.messages {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.empty {
  color: var(--text-muted);
  font-size: 13px;
}

.bubble {
  max-width: 100%;
  padding: 8px 10px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.5;
}

.bubble.user {
  align-self: flex-end;
  background: var(--raised);
  color: var(--text);
}

.bubble.assistant {
  background: #121218;
  border: 1px solid var(--border);
}

.bubble.error {
  color: var(--err);
  background: rgba(248, 113, 113, 0.08);
}

.bubble.assistant :deep(p) {
  margin: 0 0 8px;
}

.bubble.assistant :deep(p:last-child) {
  margin-bottom: 0;
}

.thinking,
.tool-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--overlay);
  overflow: hidden;
}

.thinking :deep(.el-collapse),
.tool-card :deep(.el-collapse) {
  border: 0;
  background: transparent;
}

.thinking :deep(.el-collapse-item__header),
.tool-card :deep(.el-collapse-item__header) {
  height: auto;
  min-height: 36px;
  line-height: 1.4;
  padding: 6px 10px;
  background: transparent;
  border: 0;
  color: var(--text);
  font-size: 12px;
}

.thinking :deep(.el-collapse-item__wrap),
.tool-card :deep(.el-collapse-item__wrap) {
  background: transparent;
  border: 0;
}

.thinking :deep(.el-collapse-item__content),
.tool-card :deep(.el-collapse-item__content) {
  padding: 0 10px 10px;
  color: var(--text-muted);
}

.tool-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.tool-name {
  font-size: 12px;
}

.tool-status {
  color: var(--text-faint);
  font-size: 11px;
}

.tool-head .ok {
  color: var(--ok);
}

.tool-head .err {
  color: var(--err);
}

.tool-summary,
.thinking-body {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 11px;
  font-family: "Fira Code", ui-monospace, monospace;
  color: var(--text-muted);
}

.thinking-title {
  font-size: 12px;
  color: var(--text-muted);
}

.plan {
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--overlay);
}

.plan-summary {
  margin: 0 0 8px;
  font-size: 13px;
}

.mutation {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}

.plan-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  align-items: center;
}

.plan-actions button {
  background: var(--raised);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 6px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 12px;
}

.composer {
  --composer-btn: 36px;
  --composer-min: 56px;
  --composer-max: 136px;
  --composer-gap: 8px;
  position: relative;
  flex: 0 0 auto;
  min-width: 0;
  box-sizing: border-box;
  border-top: 1px solid var(--border);
  padding: 10px;
}

.row {
  display: flex;
  align-items: flex-end;
  gap: var(--composer-gap);
  min-width: 0;
  width: 100%;
}

.attach {
  flex: 0 0 var(--composer-btn);
  width: var(--composer-btn);
}

.plus,
.send {
  box-sizing: border-box;
  flex: 0 0 var(--composer-btn);
  width: var(--composer-btn);
  min-width: var(--composer-btn);
  max-width: var(--composer-btn);
  height: var(--composer-btn);
  min-height: var(--composer-btn);
  max-height: var(--composer-btn);
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--raised);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 8px;
  cursor: pointer;
  line-height: 1;
  white-space: nowrap;
  overflow: hidden;
  font-size: 0;
}

.plus :deep(.el-icon),
.send :deep(.el-icon) {
  font-size: 16px;
}

.menu {
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: calc(100% + 8px);
  z-index: 6;
  width: auto;
  box-sizing: border-box;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #121218;
}

.menu p {
  margin: 0 0 8px;
  font-size: 10px;
  color: var(--text-faint);
}

.search,
.draft {
  background: var(--raised);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 8px;
  padding: 8px 10px;
  box-sizing: border-box;
}

.search {
  width: 100%;
}

.draft {
  flex: 1;
  min-width: 0;
  width: auto;
  display: block;
  margin: 0;
  min-height: var(--composer-min);
  height: var(--composer-min);
  max-height: var(--composer-max);
  line-height: 20px;
  resize: none;
  overflow-y: auto;
  font: inherit;
  field-sizing: fixed;
}

.results {
  margin-top: 8px;
  max-height: 180px;
  overflow: auto;
}

.results button {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--border);
  color: var(--text-muted);
  padding: 8px;
  cursor: pointer;
  font-size: 11px;
  font-family: "Fira Code", ui-monospace, monospace;
}

form[data-agent-stream] {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: flex-end;
  gap: var(--composer-gap);
}
</style>
