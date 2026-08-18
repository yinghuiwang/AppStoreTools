<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import {
  ChatActionbar as TChatActionbar,
  ChatContent as TChatContent,
  ChatList as TChatList,
  ChatLoading as TChatLoading,
  ChatMessage as TChatMessage,
  ChatSender as TChatSender,
  ChatThinking as TChatThinking,
  useChat,
  type AIMessageContent,
  type ChatMessagesData,
} from "@tdesign-vue-next/chat";
import { AddIcon, CheckCircleFilledIcon, CloseCircleFilledIcon, LoadingIcon } from "tdesign-icons-vue-next";
import enUS from "tdesign-vue-next/es/locale/en_US";
import zhCN from "tdesign-vue-next/es/locale/zh_CN";
import {
  agentChatServiceConfig,
  attachAgentChatEngine,
  detachAgentChatEngine,
  useAgent,
  type AgentPlan,
} from "@/composables/useAgent";
import {
  assistantTextOf,
  planFromActivity,
  toolStatusOf,
  toolSummaryOf,
  userTextOf,
} from "@/composables/agentStream";
import { useRightRail } from "@/composables/useRightRail";

const { t, locale } = useI18n();
const { chatEngine, messages, status } = useChat({
  defaultMessages: [],
  chatServiceConfig: agentChatServiceConfig,
});
const generating = computed(() => status.value === "pending" || status.value === "streaming");
const { sessionId, boundTaskId, send, stop, bindTask, apply, reject, searchFailed, restoreMessages } = useAgent();
const rail = useRightRail();
const draft = ref("");
const attachOpen = ref(false);
const search = ref("");
const results = ref<Array<Record<string, unknown>>>([]);
const rerunByPlan = ref<Record<string, boolean>>({});
const composerEl = ref<HTMLElement | null>(null);
const attachWrap = ref<HTMLElement | null>(null);
const openTools = ref<string[]>([]);
const openThinks = ref<string[]>([]);
const thinkTouched = ref<string[]>([]);

const senderTextareaProps = {
  name: "message",
  autosize: { minRows: 2, maxRows: 6 },
};

const markdownProps = { engine: "marked" as const, options: {} };

const tdLocale = computed(() => {
  const chat = (locale.value === "zh" ? zhCN : enUS).chat;
  return {
    chat: {
      ...chat,
      placeholder: t("agent.composer_placeholder"),
      stopBtnText: t("agent.stop"),
      loadingText: t("agent.thinking"),
      loadingEndText: t("agent.thinking_done"),
    },
  };
});

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
  else if (mutation.content != null) after = trunc(mutation.content, 80);
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

function toolDisplayName(name: string): string {
  const key = `agent.tool.name.${name}`;
  const label = t(key);
  return label === key ? name : label;
}

type ThinkMsg = { text: string; streaming?: boolean };
type ToolMsg = { id: string; name: string; status: "running" | "success" | "error"; summary: string };
type AssistantMsg = { text: string };

type AssistantTurn = {
  key: string;
  kind: "assistant";
  idx: number;
  status: ChatMessagesData["status"];
  thinks: Array<{ idx: number; msg: ThinkMsg }>;
  tools: Array<{ idx: number; msg: ToolMsg }>;
  assistant?: { idx: number; msg: AssistantMsg };
  plans: AgentPlan[];
};

type ChatTurn =
  | { key: string; kind: "user"; idx: number; text: string }
  | { key: string; kind: "error"; idx: number; text: string }
  | { key: string; kind: "plan"; idx: number; plan: AgentPlan }
  | AssistantTurn;

function thinkText(block: AIMessageContent): string {
  const data = block.data as { text?: string } | string | unknown[] | undefined;
  if (typeof data === "string") return data;
  if (Array.isArray(data)) {
    return data
      .map((item) => {
        if (typeof item === "string") return item;
        if (!item || typeof item !== "object") return "";
        const row = item as { data?: unknown; text?: unknown };
        if (typeof row.data === "string") return row.data;
        if (typeof row.text === "string") return row.text;
        return "";
      })
      .join("");
  }
  return String(data?.text || "");
}

function isStreamingStatus(status: string | undefined): boolean {
  return status === "pending" || status === "streaming";
}

function blockToThink(block: AIMessageContent, idx: number): { idx: number; msg: ThinkMsg } {
  return {
    idx,
    msg: { text: thinkText(block), streaming: isStreamingStatus(block.status) },
  };
}

function blockToTool(block: AIMessageContent, idx: number): { idx: number; msg: ToolMsg } {
  const data = (block.data || {}) as { toolCallId?: string; toolCallName?: string };
  return {
    idx,
    msg: {
      id: String(data.toolCallId || `tool-${idx}`),
      name: String(data.toolCallName || "tool"),
      status: toolStatusOf(block),
      summary: toolSummaryOf(block),
    },
  };
}

const chatTurns = computed((): ChatTurn[] => {
  const turns: ChatTurn[] = [];
  messages.value.forEach((msg, idx) => {
    if (msg.role === "user") {
      turns.push({ key: msg.id || `user-${idx}`, kind: "user", idx, text: userTextOf(msg) });
      return;
    }
    if (msg.role === "system") {
      const text = userTextOf(msg) || assistantTextOf(msg);
      if (text) turns.push({ key: msg.id || `sys-${idx}`, kind: "error", idx, text });
      return;
    }
    const content = msg.content || [];
    const thinks: AssistantTurn["thinks"] = [];
    const tools: AssistantTurn["tools"] = [];
    const plans: AgentPlan[] = [];
    let assistantText = "";
    content.forEach((block, bi) => {
      if (block.type === "thinking" || block.type === "reasoning") {
        thinks.push(blockToThink(block, bi));
        return;
      }
      if (block.type === "toolcall") {
        tools.push(blockToTool(block, bi));
        return;
      }
      const plan = planFromActivity(block);
      if (plan) {
        plans.push(plan);
        return;
      }
      if (block.type === "markdown" || block.type === "text") {
        assistantText += typeof block.data === "string" ? block.data : "";
      }
    });
    if (msg.status === "error" && assistantText) {
      turns.push({ key: msg.id || `error-${idx}`, kind: "error", idx, text: assistantText });
      return;
    }
    if (!thinks.length && !tools.length && !assistantText && !plans.length) return;
    turns.push({
      key: msg.id || `assistant-${idx}`,
      kind: "assistant",
      idx,
      status: msg.status,
      thinks,
      tools,
      plans,
      assistant: assistantText ? { idx, msg: { text: assistantText } } : undefined,
    });
    for (const plan of plans) {
      turns.push({ key: `plan-${plan.id}`, kind: "plan", idx, plan });
    }
  });
  return turns;
});

function assistantStatus(turn: AssistantTurn): "streaming" | "complete" | "error" {
  // Official t-chat-item hides the content slot when status is pending, or
  // streaming with empty content. Never pass pending; always pass content.
  if (turn.status === "error") return "error";
  const last = chatTurns.value[chatTurns.value.length - 1];
  if (generating.value && last?.key === turn.key) return "streaming";
  return "complete";
}

function assistantContent(turn: AssistantTurn): AIMessageContent[] {
  const msg = messages.value[turn.idx];
  if (msg?.role === "assistant" && msg.content?.length) return msg.content;
  return [{ type: "markdown", data: turn.assistant?.msg.text || " " }];
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

function thinkTitle(msg: ThinkMsg): string {
  return msg.streaming ? t("agent.thinking") : t("agent.thinking_done");
}

function thinkPayload(msg: ThinkMsg) {
  return { title: thinkTitle(msg), text: msg.text };
}

function thinkStatus(msg: ThinkMsg) {
  return msg.streaming ? "pending" : "complete";
}

function thinkCollapsed(msg: ThinkMsg, idx: number): boolean {
  const name = thinkName(idx);
  if (thinkTouched.value.includes(name)) {
    return !openThinks.value.includes(name);
  }
  // Official ChatThinking demo: expand while pending, collapse when complete.
  return !msg.streaming;
}

function onThinkCollapsed(idx: number, value: unknown, msg?: ThinkMsg) {
  const name = thinkName(idx);
  let collapsed = msg ? thinkCollapsed(msg, idx) : !openThinks.value.includes(name);
  if (typeof value === "boolean") collapsed = value;
  else if (value && typeof value === "object" && "detail" in value) {
    const detail = (value as CustomEvent).detail;
    if (typeof detail === "boolean") collapsed = detail;
  }
  if (!thinkTouched.value.includes(name)) {
    thinkTouched.value = [...thinkTouched.value, name];
  }
  const next = openThinks.value.filter((item) => item !== name);
  if (!collapsed) next.push(name);
  openThinks.value = next;
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

function stampComposerField() {
  const root = composerEl.value;
  if (!root) return;
  const ta = root.querySelector("textarea");
  if (!ta) return;
  ta.setAttribute("name", "message");
  ta.setAttribute("data-agent-input", "");
  ta.setAttribute("rows", "2");
}

const boundSummary = computed(() => {
  const bits: string[] = [];
  if (boundTaskId.value) bits.push(shortId(boundTaskId.value));
  if (sessionId.value) bits.push(shortId(sessionId.value));
  return bits.join(" · ");
});

const panelOpen = computed(() => rail.open.value && rail.tab.value === "agent");

async function onSubmit(text?: string) {
  const value = (typeof text === "string" ? text : draft.value).trim();
  if (!value || generating.value) return;
  draft.value = "";
  await nextTick();
  stampComposerField();
  await send({ message: value });
}

function onSenderSend(value: string) {
  void onSubmit(value);
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
  () =>
    chatTurns.value
      .filter((turn): turn is AssistantTurn => turn.kind === "assistant")
      .flatMap((turn) => turn.tools.map((item) => `${item.msg.id}:${item.msg.status}`))
      .join("|"),
  () => {
    const running = chatTurns.value
      .filter((turn): turn is AssistantTurn => turn.kind === "assistant")
      .flatMap((turn) => turn.tools)
      .filter((item) => item.msg.status === "running")
      .map((item) => item.msg.id);
    const seen = new Set(openTools.value);
    for (const id of running) {
      if (!seen.has(id)) openTools.value = [...openTools.value, id];
    }
  },
);

watch(generating, async () => {
  await nextTick();
  stampComposerField();
});

watch(
  chatEngine,
  (engine) => {
    if (!engine) return;
    attachAgentChatEngine({
      sendUserMessage: (params) => engine.sendUserMessage(params),
      abortChat: () => engine.abortChat(),
      setMessages: (next, mode) => engine.setMessages(next, mode),
      getMessages: () => engine.messages || messages.value,
    });
  },
  { immediate: true },
);

onMounted(() => {
  if (rail.sessionId.value) sessionId.value = rail.sessionId.value;
  if (rail.boundTaskId.value) boundTaskId.value = rail.boundTaskId.value;
  document.addEventListener("pointerdown", onDocPointerDown);
  document.addEventListener("keydown", onDocKeydown);
  void restoreMessages();
  void nextTick(stampComposerField);
});

onBeforeUnmount(() => {
  detachAgentChatEngine();
  document.removeEventListener("pointerdown", onDocPointerDown);
  document.removeEventListener("keydown", onDocKeydown);
});
</script>

<template>
  <t-config-provider :global-config="tdLocale">
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
      <t-chat-list
        class="messages"
        data-agent-messages
        layout="both"
        animation="moving"
        default-scroll-to="bottom"
        :reverse="false"
        :clear-history="false"
        :auto-scroll="true"
        :show-scroll-button="true"
        :is-stream-load="generating"
      >
        <p v-if="!messages.length" class="empty agent-dock-empty">{{ t("agent.empty") }}</p>
        <template v-for="turn in chatTurns" :key="turn.key">
          <t-chat-message
            v-if="turn.kind === 'user'"
            class="agent-msg agent-msg--user"
            role="user"
            placement="right"
            variant="base"
          >
            <t-chat-content role="user" :content="{ type: 'text', data: turn.text }" />
          </t-chat-message>
          <t-chat-message
            v-else-if="turn.kind === 'assistant'"
            role="assistant"
            placement="left"
            variant="text"
            :status="assistantStatus(turn)"
            :content="assistantContent(turn)"
            animation="moving"
          >
            <div class="agent-turn-body">
              <div
                v-for="item in turn.thinks"
                v-show="item.msg.streaming || item.msg.text.trim()"
                :key="item.idx"
                class="thinking"
                data-agent-thinking
                :data-agent-thinking-open="thinkCollapsed(item.msg, item.idx) ? 'false' : 'true'"
              >
                <span class="thinking-title" data-agent-thinking-title>{{ thinkTitle(item.msg) }}</span>
                <t-chat-thinking
                  :content="thinkPayload(item.msg)"
                  :status="thinkStatus(item.msg)"
                  :collapsed="thinkCollapsed(item.msg, item.idx)"
                  layout="block"
                  animation="moving"
                  @collapsed-change="onThinkCollapsed(item.idx, $event, item.msg)"
                >
                  <pre
                    v-if="!thinkCollapsed(item.msg, item.idx)"
                    class="thinking-body"
                    data-agent-thinking-body
                  >{{ item.msg.text }}</pre>
                </t-chat-thinking>
              </div>
              <article
                v-for="item in turn.tools"
                :key="item.msg.id"
                class="tool-card"
                :data-agent-tool="item.msg.id"
              >
                <t-collapse
                  borderless
                  :model-value="toolOpenNames(item.msg.id)"
                  @update:model-value="onToolToggle(item.msg.id, $event)"
                >
                  <t-collapse-panel :value="item.msg.id">
                    <template #header>
                      <span class="tool-head">
                        <LoadingIcon v-if="item.msg.status === 'running'" class="is-loading" size="14px" />
                        <CheckCircleFilledIcon v-else-if="item.msg.status === 'success'" class="ok" size="14px" />
                        <CloseCircleFilledIcon v-else class="err" size="14px" />
                        <span class="tool-name mono" data-agent-tool-name>{{ toolDisplayName(item.msg.name) }}</span>
                        <span class="tool-status" :data-agent-tool-status="item.msg.status">
                          {{ toolStatusLabel(item.msg.status) }}
                        </span>
                      </span>
                    </template>
                    <pre v-if="item.msg.summary" class="tool-summary" data-agent-tool-summary>{{ item.msg.summary }}</pre>
                  </t-collapse-panel>
                </t-collapse>
              </article>
              <div
                v-if="turn.assistant"
                class="agent-msg agent-msg--assistant agent-msg--md"
              >
                <t-chat-content
                  role="assistant"
                  :content="{ type: 'markdown', data: turn.assistant.msg.text }"
                  :markdown-props="markdownProps"
                />
              </div>
            </div>
            <template #actionbar>
              <t-chat-actionbar
                v-if="turn.assistant?.msg.text.trim() && !generating"
                :content="turn.assistant.msg.text"
                :action-bar="['copy']"
              />
            </template>
          </t-chat-message>
          <t-chat-message
            v-else-if="turn.kind === 'error'"
            class="agent-msg agent-msg--error"
            role="assistant"
            placement="left"
            variant="text"
            status="error"
          >
            <t-chat-content role="assistant" status="error" :content="turn.text" />
          </t-chat-message>
          <t-chat-message
            v-else-if="turn.kind === 'plan'"
            role="assistant"
            placement="left"
            variant="text"
          >
            <article class="plan" :data-agent-plan="turn.plan.id">
              <p class="plan-summary">{{ turn.plan.summary }}</p>
              <div
                v-for="(mutation, mi) in turn.plan.mutations"
                :key="mi"
                class="mutation mono"
              >
                {{ mutationLine(mutation) }}
              </div>
              <div v-for="(step, si) in turn.plan.manual_steps || []" :key="'s' + si" class="mutation">
                {{ step }}
              </div>
              <p v-if="turn.plan.rerun?.task_id" class="mutation mono">
                {{ turn.plan.rerun.kind || "" }} · {{ shortId(turn.plan.rerun.task_id) }}
              </p>
              <p v-if="turn.plan.status && turn.plan.status !== 'pending'" data-agent-plan-status>
                {{ planStatusLabel(turn.plan.status) }}
                <template v-if="turn.plan.error"> — {{ turn.plan.error }}</template>
              </p>
              <div v-if="canAct(turn.plan)" class="plan-actions">
                <label v-if="turn.plan.rerun">
                  <input
                    type="checkbox"
                    :checked="rerunByPlan[turn.plan.id] !== false"
                    @change="rerunByPlan[turn.plan.id] = ($event.target as HTMLInputElement).checked"
                  />
                  {{ t("agent.rerun_after_apply") }}
                </label>
                <button
                  v-if="turn.plan.mutations.length"
                  type="button"
                  @click="applyPlan(turn.plan)"
                >
                  {{ t("agent.apply") }}
                </button>
                <button type="button" @click="reject(turn.plan.id)">{{ t("agent.ignore") }}</button>
              </div>
            </article>
          </t-chat-message>
        </template>
        <t-chat-message
          v-if="generating && !chatTurns.some((turn) => turn.kind === 'assistant' && (turn.thinks.length || turn.tools.length || turn.assistant))"
          role="assistant"
          placement="left"
          variant="text"
          status="pending"
          animation="moving"
        >
          <t-chat-loading animation="moving" :text="t('agent.generating')" />
        </t-chat-message>
      </t-chat-list>
      <form
        ref="composerEl"
        class="composer"
        data-agent-stream
        @submit.prevent="onSubmit()"
      >
        <t-chat-sender
          v-model="draft"
          :placeholder="t('agent.composer_placeholder')"
          :loading="generating"
          :textarea-props="senderTextareaProps"
          @send="onSenderSend"
          @stop="stop()"
        >
          <template #footer-prefix>
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
                <AddIcon size="16px" />
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
          </template>
        </t-chat-sender>
        <button
          type="submit"
          hidden
          data-agent-send
          :title="t('agent.send')"
          :aria-label="t('agent.send')"
        />
        <button
          type="button"
          hidden
          data-agent-stop
          :title="t('agent.stop')"
          :aria-label="t('agent.stop')"
          @click="stop()"
        />
      </form>
    </div>
  </t-config-provider>
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
}

.agent :deep(.t-chat) {
  flex: 1;
  min-height: 0;
  height: 100%;
}

.agent :deep(.t-chat__list) {
  overflow: auto;
  padding: var(--td-comp-paddingTB-l, 16px) var(--td-comp-paddingLR-l, 16px);
}

.empty {
  color: var(--text-muted);
  font-size: 13px;
}

.agent-turn-body {
  display: flex;
  flex-direction: column;
  gap: var(--td-chat-item-content-gap, var(--td-comp-margin-s, 8px));
  width: 100%;
}

.agent-msg {
  max-width: 100%;
}

.agent-msg--user :deep(.t-chat__text) {
  max-width: 100%;
}

.thinking {
  position: relative;
}

.tool-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--overlay);
  overflow: hidden;
}

.tool-card :deep(.t-collapse) {
  border: 0;
  background: transparent;
}

.tool-card :deep(.t-collapse-panel__header) {
  height: auto;
  min-height: 36px;
  line-height: 1.4;
  padding: 6px 10px;
  background: transparent;
  border: 0;
  color: var(--text);
  font-size: 12px;
}

.tool-card :deep(.t-collapse-panel__body) {
  background: transparent;
  border: 0;
}

.tool-card :deep(.t-collapse-panel__content) {
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

.tool-head .is-loading {
  color: var(--accent-dim);
  animation: agent-spin 0.85s linear infinite;
}

.tool-head .ok {
  color: var(--ok);
}

.tool-head .err {
  color: var(--err);
}

.tool-summary {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 11px;
  font-family: "Fira Code", ui-monospace, monospace;
  color: var(--text-muted);
}

.thinking-title {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

.thinking-body {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted);
  font-family: inherit;
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

.attach {
  flex: 0 0 var(--composer-btn);
  width: var(--composer-btn);
}

.plus {
  box-sizing: border-box;
  width: var(--composer-btn);
  min-width: var(--composer-btn);
  height: var(--composer-btn);
  min-height: var(--composer-btn);
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

.plus :deep(svg) {
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

.search {
  background: var(--raised);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 8px;
  padding: 8px 10px;
  box-sizing: border-box;
  width: 100%;
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

@keyframes agent-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
