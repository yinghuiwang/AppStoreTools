import type { AIMessageContent, ChatMessagesData } from "@tdesign-vue-next/chat";

export type AgentPlan = {
  id: string;
  status: string;
  summary: string;
  mutations: Array<Record<string, unknown>>;
  manual_steps?: string[];
  rerun?: { task_id?: string; kind?: string };
  error?: string;
};

export type AgentChoiceOption = {
  id: string;
  label: string;
  description?: string;
};

export type AgentWorkflow = {
  phase: string;
  kind?: string;
  prompt?: string;
  options?: AgentChoiceOption[];
  selected_id?: string | null;
  updated_at?: string;
};

export type AgentToolStatus = "running" | "success" | "error";

export type StoreRow = {
  role?: string;
  content?: string;
  tool_name?: string;
  tool_call_id?: string;
};

const TOOL_CALLS_MARK = "_tool_calls";
const OPEN_TAGS = ["<think>", "<thinking>", "<reasoning>"];
const CLOSE_TAGS = ["</think>", "</thinking>", "</reasoning>"];

function parseObj(data: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(data) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function findTag(buf: string, tags: string[]): { index: number; length: number } | null {
  const lower = buf.toLowerCase();
  let best: { index: number; length: number } | null = null;
  for (const tag of tags) {
    const index = lower.indexOf(tag);
    if (index >= 0 && (!best || index < best.index)) best = { index, length: tag.length };
  }
  return best;
}

function suffixPrefixLen(buf: string, tags: string[]): number {
  const lower = buf.toLowerCase();
  let max = 0;
  for (const tag of tags) {
    const n = Math.min(tag.length - 1, lower.length);
    for (let k = n; k > 0; k -= 1) {
      if (lower.endsWith(tag.slice(0, k))) {
        max = Math.max(max, k);
        break;
      }
    }
  }
  return max;
}

/** One-shot split for persisted assistant text. Live thinking uses AG-UI events. */
export function splitStoredThink(text: string): { thinking: string; visible: string } {
  let buf = text;
  let thinking = "";
  let visible = "";
  let current: "text" | "think" = "text";
  while (buf) {
    const tags = current === "text" ? OPEN_TAGS : CLOSE_TAGS;
    const hit = findTag(buf, tags);
    if (!hit) {
      const keep = suffixPrefixLen(buf, tags);
      const ready = buf.slice(0, buf.length - keep);
      if (current === "think") thinking += ready;
      else visible += ready;
      buf = buf.slice(buf.length - keep);
      break;
    }
    const before = buf.slice(0, hit.index);
    if (current === "think") thinking += before;
    else visible += before;
    buf = buf.slice(hit.index + hit.length);
    current = current === "text" ? "think" : "text";
  }
  if (current === "think") thinking += buf;
  else visible += buf;
  return { thinking, visible };
}

function uid(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

function summaryFromStoredTool(content: string): { ok: boolean; summary: string } {
  const parsed = parseObj(content);
  if (Object.keys(parsed).length) {
    const ok = parsed.ok !== false;
    const summary = String(parsed.error || parsed.summary || "").trim();
    if (summary) return { ok, summary };
    return { ok, summary: content.slice(0, 200) };
  }
  return { ok: true, summary: content.slice(0, 200) };
}

function toolcallBlock(row: StoreRow): AIMessageContent {
  const parsed = summaryFromStoredTool(String(row.content || ""));
  return {
    type: "toolcall",
    status: "complete",
    data: {
      toolCallId: String(row.tool_call_id || uid("tool")),
      toolCallName: String(row.tool_name || "tool"),
      result: JSON.stringify({
        id: row.tool_call_id,
        name: row.tool_name,
        ok: parsed.ok,
        summary: parsed.summary,
      }),
    },
  };
}

function planActivity(plan: AgentPlan): AIMessageContent {
  return {
    type: "activity",
    status: "complete",
    data: {
      activityType: "propose_fix",
      content: plan,
    },
  };
}

function choiceActivity(workflow: AgentWorkflow): AIMessageContent {
  return {
    type: "activity",
    status: "complete",
    data: {
      activityType: "offer_choices",
      content: workflow,
    },
  };
}

function isPendingChoice(workflow?: AgentWorkflow | null): boolean {
  return Boolean(workflow && workflow.phase === "awaiting_choice" && !workflow.selected_id);
}

function attachPendingChoice(
  messages: ChatMessagesData[],
  workflow?: AgentWorkflow | null,
): ChatMessagesData[] {
  if (!isPendingChoice(workflow) || !workflow) return messages;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (msg.role !== "assistant") continue;
    if ((msg.content || []).some((block) => isChoiceActivity(block))) return messages;
    const content = [...(msg.content || []), choiceActivity(workflow)];
    return messages.map((item, idx) => (idx === i ? { ...msg, content } : item));
  }
  return [
    ...messages,
    {
      id: uid("assistant"),
      role: "assistant",
      status: "complete",
      content: [choiceActivity(workflow)],
    },
  ];
}

export function historyToChatMessages(
  rows: StoreRow[],
  plans: AgentPlan[] = [],
  workflow?: AgentWorkflow | null,
): ChatMessagesData[] {
  const out: ChatMessagesData[] = [];
  let assistant: AIMessageContent[] = [];

  const flushAssistant = () => {
    if (!assistant.length) return;
    out.push({
      id: uid("assistant"),
      role: "assistant",
      status: "complete",
      content: assistant,
    });
    assistant = [];
  };

  for (const row of rows) {
    if (row.role === "user") {
      flushAssistant();
      out.push({
        id: uid("user"),
        role: "user",
        status: "complete",
        content: [{ type: "text", data: String(row.content || "") }],
      });
      continue;
    }
    if (row.role === "assistant" && row.tool_name === TOOL_CALLS_MARK) {
      try {
        const payload = JSON.parse(String(row.content || "{}")) as { content?: string };
        const text = String(payload.content || "").trim();
        if (text) {
          const { thinking, visible } = splitStoredThink(text);
          if (thinking.trim()) {
            assistant.push({
              type: "thinking",
              status: "complete",
              data: { text: thinking },
            });
          }
          if (visible) assistant.push({ type: "markdown", status: "complete", data: visible });
        }
      } catch {
        /* skip unreadable tool-call envelope */
      }
      continue;
    }
    if (row.role === "tool") {
      if (!row.tool_call_id) continue;
      assistant.push(toolcallBlock(row));
      continue;
    }
    if (row.role === "assistant") {
      const { thinking, visible } = splitStoredThink(String(row.content || ""));
      if (thinking.trim()) {
        assistant.push({ type: "thinking", status: "complete", data: { text: thinking } });
      }
      if (visible) assistant.push({ type: "markdown", status: "complete", data: visible });
    }
  }
  for (const plan of plans) assistant.push(planActivity(plan));
  flushAssistant();
  return attachPendingChoice(out, workflow);
}

export function userTextOf(msg: ChatMessagesData): string {
  if (msg.role !== "user") return "";
  return msg.content
    .map((block) => (typeof block.data === "string" ? block.data : ""))
    .join("");
}

export function assistantTextOf(msg: ChatMessagesData): string {
  if (msg.role !== "assistant" || !msg.content) return "";
  return msg.content
    .filter((block) => block.type === "markdown" || block.type === "text")
    .map((block) => (typeof block.data === "string" ? block.data : ""))
    .join("");
}

export function isPlanActivity(block: AIMessageContent): block is AIMessageContent & {
  type: "activity";
  data: { activityType: string; content: AgentPlan };
} {
  return (
    block.type === "activity" &&
    Boolean(block.data) &&
    (block.data as { activityType?: string }).activityType === "propose_fix"
  );
}

export function planFromActivity(block: AIMessageContent): AgentPlan | null {
  if (!isPlanActivity(block)) return null;
  const content = (block.data as { content?: AgentPlan }).content;
  return content && content.id ? content : null;
}

export function isChoiceActivity(block: AIMessageContent): block is AIMessageContent & {
  type: "activity";
  data: { activityType: string; content: AgentWorkflow };
} {
  return (
    block.type === "activity" &&
    Boolean(block.data) &&
    (block.data as { activityType?: string }).activityType === "offer_choices"
  );
}

export function choiceFromActivity(block: AIMessageContent): AgentWorkflow | null {
  if (!isChoiceActivity(block)) return null;
  const content = (block.data as { content?: unknown }).content;
  if (!content || typeof content !== "object" || Array.isArray(content)) return null;
  const row = content as AgentWorkflow;
  if (row.phase || (Array.isArray(row.options) && row.options.length)) return row;
  return null;
}

export function toolStatusOf(block: AIMessageContent): AgentToolStatus {
  if (block.status === "pending" || block.status === "streaming") return "running";
  const raw = block.type === "toolcall" ? String(block.data?.result || "") : "";
  const parsed = parseObj(raw);
  return parsed.ok === false ? "error" : "success";
}

export function toolSummaryOf(block: AIMessageContent): string {
  if (block.type !== "toolcall") return "";
  const raw = String(block.data?.result || "");
  const parsed = parseObj(raw);
  return String(parsed.summary || parsed.error || "").trim();
}

export function patchPlanInMessages(
  messages: ChatMessagesData[],
  planId: string,
  patch: Partial<AgentPlan>,
): ChatMessagesData[] {
  return messages.map((msg) => {
    if (msg.role !== "assistant" || !msg.content) return msg;
    let changed = false;
    const content = msg.content.map((block) => {
      const plan = planFromActivity(block);
      if (!plan || plan.id !== planId) return block;
      changed = true;
      return {
        ...block,
        type: "activity",
        data: {
          activityType: "propose_fix",
          content: { ...plan, ...patch },
        },
      } as AIMessageContent;
    });
    return changed ? { ...msg, content } : msg;
  });
}

export function patchChoiceInMessages(
  messages: ChatMessagesData[],
  patch: Partial<AgentWorkflow>,
): ChatMessagesData[] {
  return messages.map((msg) => {
    if (msg.role !== "assistant" || !msg.content) return msg;
    let changed = false;
    const content = msg.content.map((block) => {
      const choice = choiceFromActivity(block);
      if (!choice) return block;
      if (choice.phase !== "awaiting_choice" || choice.selected_id) return block;
      changed = true;
      return {
        ...block,
        type: "activity",
        data: {
          activityType: "offer_choices",
          content: { ...choice, ...patch },
        },
      } as AIMessageContent;
    });
    return changed ? { ...msg, content } : msg;
  });
}
