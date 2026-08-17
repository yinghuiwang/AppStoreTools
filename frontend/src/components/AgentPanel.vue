<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { useAgent, type AgentPlan } from "@/composables/useAgent";
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

const boundSummary = computed(() => {
  const bits: string[] = [];
  if (boundTaskId.value) bits.push(shortId(boundTaskId.value));
  if (sessionId.value) bits.push(shortId(sessionId.value));
  return bits.join(" · ");
});

async function onSubmit() {
  const text = draft.value.trim();
  if (!text || generating.value) return;
  draft.value = "";
  messages.value = [...messages.value, { kind: "user", text }];
  await send({ message: text });
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
  attachOpen.value = false;
  if (id) void bindTask(String(id), { autoAnalyze: true });
}

function applyPlan(plan: AgentPlan) {
  const rerun = rerunByPlan.value[plan.id] !== false;
  void apply(plan.id, Boolean(plan.rerun) && rerun);
}

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
  void restoreMessages();
});
</script>

<template>
  <div class="agent" data-agent-panel>
    <header class="toolbar">
      <div class="lead">
        <span class="title mono">{{ t("nav.agent") }}</span>
        <div v-if="boundSummary" class="bound mono">{{ boundSummary }}</div>
      </div>
      <button type="button" class="icon" :aria-label="t('agent.close')" @click="rail.collapse()">×</button>
    </header>
    <div ref="scroller" class="messages" data-agent-messages>
      <p v-if="!messages.length" class="empty">{{ t("agent.empty") }}</p>
      <template v-for="(msg, idx) in messages" :key="idx">
        <div v-if="msg.kind === 'user'" class="bubble user">{{ msg.text }}</div>
        <div
          v-else-if="msg.kind === 'assistant'"
          class="bubble assistant"
          v-html="renderMd(msg.text)"
        />
        <div v-else-if="msg.kind === 'error'" class="bubble error">{{ msg.text }}</div>
        <div v-else-if="msg.kind === 'tool'" class="tool">{{ msg.text }}</div>
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
        <div class="attach" data-agent-attach-wrap>
          <button
            type="button"
            class="plus"
            data-agent-attach
            :aria-expanded="attachOpen ? 'true' : 'false'"
            :aria-label="t('agent.attach')"
            @click="attachOpen = !attachOpen; if (attachOpen) runSearch()"
          >
            +
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
          <input
            v-model="draft"
            type="text"
            name="message"
            :placeholder="t('agent.composer_placeholder')"
            autocomplete="off"
          />
          <button v-show="generating" type="button" data-agent-stop @click="stop()">
            {{ t("agent.stop") }}
          </button>
          <button type="submit">{{ t("agent.send") }}</button>
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

.tool {
  font-size: 11px;
  color: var(--text-faint);
  font-family: "Fira Code", ui-monospace, monospace;
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

.plan-actions button,
.composer button,
.plus {
  background: var(--raised);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 6px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 12px;
}

.composer {
  border-top: 1px solid var(--border);
  padding: 10px 12px;
}

.row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.attach {
  position: relative;
}

.plus {
  width: 32px;
  height: 32px;
  padding: 0;
  font-size: 18px;
}

.menu {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  z-index: 6;
  width: 260px;
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
.composer input {
  width: 100%;
  background: var(--raised);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 6px;
  padding: 7px 8px;
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
  display: flex;
  gap: 6px;
}
</style>
