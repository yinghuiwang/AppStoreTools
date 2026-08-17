export type AgentPlan = {
  id: string;
  status: string;
  summary: string;
  mutations: Array<Record<string, unknown>>;
  manual_steps?: string[];
  rerun?: { task_id?: string; kind?: string };
  error?: string;
};

export type AgentToolStatus = "running" | "success" | "error";

export type AgentMessage =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "error"; text: string }
  | { kind: "thinking"; text: string; streaming?: boolean; hold?: string; mode?: ThinkMode }
  | {
      kind: "tool";
      id: string;
      name: string;
      status: AgentToolStatus;
      summary: string;
      ok?: boolean;
    }
  | { kind: "plan"; plan: AgentPlan };

export type StoreRow = {
  role?: string;
  content?: string;
  tool_name?: string;
  tool_call_id?: string;
};

const TOOL_CALLS_MARK = "_tool_calls";
const OPEN_TAGS = ["<think>", "<thinking>", "<reasoning>"];
const CLOSE_TAGS = ["</think>", "</thinking>", "</reasoning>"];

export type ThinkMode = "text" | "think";

export type ThinkSplit = {
  thinking: string;
  visible: string;
  mode: ThinkMode;
  hold: string;
};

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

export function splitThinkDelta(mode: ThinkMode, hold: string, chunk: string): ThinkSplit {
  let buf = hold + chunk;
  let thinking = "";
  let visible = "";
  let current = mode;
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
  return { thinking, visible, mode: current, hold: buf };
}

function toolIndexById(messages: AgentMessage[], id: string): number {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (msg.kind === "tool" && msg.id === id) return i;
  }
  return -1;
}

function upsertTool(messages: AgentMessage[], next: Extract<AgentMessage, { kind: "tool" }>): AgentMessage[] {
  const idx = toolIndexById(messages, next.id);
  if (idx >= 0) {
    const copy = messages.slice();
    copy[idx] = { ...(messages[idx] as Extract<AgentMessage, { kind: "tool" }>), ...next };
    return copy;
  }
  return [...messages, next];
}

function lastThinkIndex(messages: AgentMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (msg.kind === "plan") continue;
    if (msg.kind === "thinking") return i;
    if (msg.kind === "user" || msg.kind === "tool" || msg.kind === "error") return -1;
  }
  return -1;
}

function streamMeta(messages: AgentMessage[]): { mode: ThinkMode; hold: string } {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const msg = messages[i];
    if (msg.kind === "plan") continue;
    if (msg.kind === "thinking") {
      return {
        mode: msg.mode === "think" ? "think" : "text",
        hold: msg.hold || "",
      };
    }
    if (msg.kind === "user" || msg.kind === "tool" || msg.kind === "error") break;
  }
  return { mode: "text", hold: "" };
}

export function appendAssistantToken(messages: AgentMessage[], fragment: string): AgentMessage[] {
  const last = messages[messages.length - 1];
  if (last && last.kind === "assistant") {
    const copy = messages.slice();
    copy[copy.length - 1] = { kind: "assistant", text: last.text + fragment };
    return copy;
  }
  return [...messages, { kind: "assistant", text: fragment }];
}

export function applyToolStart(messages: AgentMessage[], data: string): AgentMessage[] {
  const payload = parseObj(data);
  const id = String(payload.id || "");
  if (!id) return messages;
  const prev = toolIndexById(messages, id);
  const existing = prev >= 0 ? (messages[prev] as Extract<AgentMessage, { kind: "tool" }>) : null;
  return upsertTool(messages, {
    kind: "tool",
    id,
    name: String(payload.name || existing?.name || "tool"),
    status: "running",
    summary: existing?.summary || "",
    ok: existing?.ok,
  });
}

export function applyToolResult(messages: AgentMessage[], data: string): AgentMessage[] {
  const payload = parseObj(data);
  const id = String(payload.id || "");
  if (!id) return messages;
  const ok = payload.ok !== false;
  const prev = toolIndexById(messages, id);
  const existing = prev >= 0 ? (messages[prev] as Extract<AgentMessage, { kind: "tool" }>) : null;
  return upsertTool(messages, {
    kind: "tool",
    id,
    name: String(payload.name || existing?.name || "tool"),
    status: ok ? "success" : "error",
    summary: String(payload.summary || existing?.summary || ""),
    ok,
  });
}

export function applyThinking(messages: AgentMessage[], text: string): AgentMessage[] {
  if (!text.trim()) return messages;
  const idx = lastThinkIndex(messages);
  if (idx >= 0) {
    const current = messages[idx] as Extract<AgentMessage, { kind: "thinking" }>;
    const copy = messages.slice();
    copy[idx] = { ...current, text: current.text + text, streaming: true };
    return copy;
  }
  return [...messages, { kind: "thinking", text, streaming: true, mode: "text" }];
}

function stampThinkState(messages: AgentMessage[], mode: ThinkMode, hold: string): AgentMessage[] {
  const idx = lastThinkIndex(messages);
  if (idx >= 0) {
    const current = messages[idx] as Extract<AgentMessage, { kind: "thinking" }>;
    const copy = messages.slice();
    copy[idx] = { ...current, mode, hold, streaming: current.streaming || mode === "think" };
    return copy;
  }
  if (mode === "think" || hold) {
    return [...messages, { kind: "thinking", text: "", streaming: mode === "think", mode, hold }];
  }
  return messages;
}

export function applyToken(messages: AgentMessage[], fragment: string): AgentMessage[] {
  const meta = streamMeta(messages);
  const split = splitThinkDelta(meta.mode, meta.hold, fragment);
  let next = messages;
  if (split.thinking) next = applyThinking(next, split.thinking);
  if (split.visible) next = appendAssistantToken(next, split.visible);
  return stampThinkState(next, split.mode, split.hold);
}

export function finishThinkStream(messages: AgentMessage[]): AgentMessage[] {
  const meta = streamMeta(messages);
  let next = messages;
  if (meta.hold) {
    if (meta.mode === "think") next = applyThinking(next, meta.hold);
    else next = appendAssistantToken(next, meta.hold);
  }
  return next
    .map((msg) =>
      msg.kind === "thinking" ? { ...msg, streaming: false, hold: "", mode: "text" as const } : msg,
    )
    .filter((msg) => msg.kind !== "thinking" || Boolean(msg.text.trim()));
}

export function applyAgentEvent(messages: AgentMessage[], event: string, data: string): AgentMessage[] {
  if (event === "token") return applyToken(messages, data);
  if (event === "tool_start") return applyToolStart(messages, data);
  if (event === "tool_result") return applyToolResult(messages, data);
  if (event === "thinking") return applyThinking(messages, data);
  return messages;
}

function splitStoredText(text: string): { thinking: string; visible: string } {
  const split = splitThinkDelta("text", "", text);
  const thinking = split.thinking + (split.mode === "think" ? split.hold : "");
  const visible = split.visible + (split.mode === "text" ? split.hold : "");
  return { thinking, visible };
}

function pushSplitAssistant(next: AgentMessage[], raw: string) {
  const { thinking, visible } = splitStoredText(raw);
  if (thinking.trim()) next.push({ kind: "thinking", text: thinking, streaming: false });
  if (visible) next.push({ kind: "assistant", text: visible });
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

export function historyToMessages(rows: StoreRow[], plans: AgentPlan[] = []): AgentMessage[] {
  const next: AgentMessage[] = [];
  for (const row of rows) {
    if (row.role === "user") {
      next.push({ kind: "user", text: String(row.content || "") });
      continue;
    }
    if (row.role === "assistant" && row.tool_name === TOOL_CALLS_MARK) {
      try {
        const payload = JSON.parse(String(row.content || "{}")) as { content?: string };
        const text = String(payload.content || "").trim();
        if (text) pushSplitAssistant(next, text);
      } catch {
        /* skip unreadable tool-call envelope */
      }
      continue;
    }
    if (row.role === "tool") {
      const id = String(row.tool_call_id || "");
      if (!id) continue;
      const parsed = summaryFromStoredTool(String(row.content || ""));
      next.push({
        kind: "tool",
        id,
        name: String(row.tool_name || "tool"),
        status: parsed.ok ? "success" : "error",
        summary: parsed.summary,
        ok: parsed.ok,
      });
      continue;
    }
    if (row.role === "assistant") {
      pushSplitAssistant(next, String(row.content || ""));
    }
  }
  for (const plan of plans) next.push({ kind: "plan", plan });
  return next;
}
