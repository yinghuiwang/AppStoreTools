import { ref, type Ref } from "vue";
import { ApiError, httpJson } from "@/api/http";
import { i18n } from "@/i18n";
import { useRightRail } from "@/composables/useRightRail";

export type AgentPlan = {
  id: string;
  status: string;
  summary: string;
  mutations: Array<Record<string, unknown>>;
  manual_steps?: string[];
  rerun?: { task_id?: string; kind?: string };
  error?: string;
};

export type AgentMessage =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "error"; text: string }
  | { kind: "tool"; text: string }
  | { kind: "plan"; plan: AgentPlan };

const sessionId = ref("");
const boundTaskId = ref("");
const messages: Ref<AgentMessage[]> = ref([]);
const generating = ref(false);

let abortController: AbortController | null = null;
let bindSeq = 0;

function t(key: string): string {
  return String(i18n.global.t(key));
}

function syncRail() {
  const rail = useRightRail();
  rail.sessionId.value = sessionId.value;
  rail.boundTaskId.value = boundTaskId.value;
  rail.persistChrome();
}

async function readAgentSse(
  response: Response,
  onEvent: (event: string, data: string) => void,
  signal: AbortSignal,
) {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (!signal.aborted) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const chunks = buf.split("\n\n");
    buf = chunks.pop() || "";
    for (const chunk of chunks) {
      let event = "message";
      const dataLines: string[] = [];
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      if (event) onEvent(event, dataLines.join("\n"));
    }
  }
}

function appendAssistantToken(fragment: string) {
  const list = messages.value;
  const last = list[list.length - 1];
  if (last && last.kind === "assistant") {
    last.text += fragment;
    messages.value = [...list];
    return;
  }
  messages.value = [...list, { kind: "assistant", text: fragment }];
}

async function loadPlanCards(planIds: string[]) {
  for (const id of planIds) {
    try {
      const plan = await httpJson<AgentPlan>(`/api/agent/plans/${encodeURIComponent(id)}`);
      messages.value = [...messages.value, { kind: "plan", plan }];
    } catch {
      /* skip missing plan */
    }
  }
}

function handleEvent(event: string, data: string) {
  if (event === "session") {
    try {
      const session = JSON.parse(data) as { session_id?: string; task_id?: string };
      if (session.session_id) sessionId.value = String(session.session_id);
      if (session.task_id) boundTaskId.value = String(session.task_id);
      syncRail();
    } catch {
      /* ignore */
    }
    return;
  }
  if (event === "token") {
    appendAssistantToken(data);
    return;
  }
  if (event === "tool_start") {
    messages.value = [...messages.value, { kind: "tool", text: t("agent.tool_running") }];
    return;
  }
  if (event === "tool_result") return;
  if (event === "error") {
    generating.value = false;
    let text = data;
    try {
      const err = JSON.parse(data) as { code?: string; message?: string };
      const key = err.code ? `agent.error.${err.code}` : "";
      const translated = key ? t(key) : "";
      text = translated && translated !== key ? translated : err.message || data;
    } catch {
      text = data;
    }
    messages.value = [...messages.value, { kind: "error", text }];
    return;
  }
  if (event === "stopped" || event === "done") {
    generating.value = false;
    if (event === "done") {
      try {
        const done = JSON.parse(data) as { session_id?: string; plan_ids?: string[] };
        if (done.session_id) {
          sessionId.value = String(done.session_id);
          syncRail();
        }
        if (done.plan_ids?.length) void loadPlanCards(done.plan_ids);
      } catch {
        /* done without cards */
      }
    }
  }
}

async function send(opts: { message: string; autoAnalyze?: boolean }): Promise<void> {
  abortController?.abort();
  abortController = new AbortController();
  const signal = abortController.signal;
  generating.value = true;
  const body: Record<string, unknown> = {
    message: opts.message || "",
    auto_analyze: opts.autoAnalyze === true,
  };
  if (sessionId.value) body.session_id = sessionId.value;
  if (boundTaskId.value) body.task_id = boundTaskId.value;
  try {
    const response = await fetch("/api/agent/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      credentials: "same-origin",
      signal,
    });
    if (!response.ok || !response.body) {
      generating.value = false;
      messages.value = [...messages.value, { kind: "error", text: t("agent.error.llm_unavailable") }];
      return;
    }
    await readAgentSse(response, handleEvent, signal);
  } catch (err) {
    if ((err as { name?: string }).name === "AbortError") return;
    generating.value = false;
    messages.value = [...messages.value, { kind: "error", text: t("agent.error.llm_unavailable") }];
  } finally {
    if (!signal.aborted) generating.value = false;
  }
}

async function stop(): Promise<void> {
  abortController?.abort();
  abortController = null;
  generating.value = false;
  if (!sessionId.value) return;
  try {
    await httpJson("/api/agent/stop", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({ session_id: sessionId.value }),
    });
  } catch {
    /* best-effort */
  }
}

function ingestSessionPayload(payload: {
  session?: { id?: string; task_id?: string };
  messages?: Array<{ role?: string; content?: string }>;
  plans?: AgentPlan[];
}) {
  const session = payload.session || {};
  if (session.id) sessionId.value = String(session.id);
  if (session.task_id) boundTaskId.value = String(session.task_id);
  syncRail();
  const next: AgentMessage[] = [];
  for (const msg of payload.messages || []) {
    if (msg.role === "user" || msg.role === "assistant") {
      next.push({ kind: msg.role, text: String(msg.content || "") });
    }
  }
  for (const plan of payload.plans || []) next.push({ kind: "plan", plan });
  messages.value = next;
}

async function restoreMessages(): Promise<void> {
  const rail = useRightRail();
  const sid = sessionId.value || rail.sessionId.value;
  const tid = boundTaskId.value || rail.boundTaskId.value;
  if (!sid && !tid) return;
  const qs = sid
    ? `session_id=${encodeURIComponent(sid)}`
    : `task_id=${encodeURIComponent(tid)}`;
  try {
    const payload = await httpJson<{
      session?: { id?: string; task_id?: string };
      messages?: Array<{ role?: string; content?: string }>;
      plans?: AgentPlan[];
    }>(`/api/agent/sessions?${qs}`, { skipNotify: true });
    ingestSessionPayload(payload);
  } catch {
    /* keep chrome without crashing */
  }
}

async function bindTask(taskId: string, opts?: { autoAnalyze?: boolean }): Promise<void> {
  const seq = ++bindSeq;
  boundTaskId.value = String(taskId);
  sessionId.value = "";
  messages.value = [];
  syncRail();
  try {
    const payload = await httpJson<{
      session?: { id?: string; task_id?: string };
      messages?: Array<{ role?: string; content?: string }>;
      plans?: AgentPlan[];
    }>(`/api/agent/sessions?task_id=${encodeURIComponent(taskId)}`, { skipNotify: true });
    if (seq !== bindSeq) return;
    ingestSessionPayload(payload);
    const history = payload.messages || [];
    if (opts?.autoAnalyze === true && history.length === 0) {
      const label = t("agent.auto_analyze_label");
      messages.value = [...messages.value, { kind: "user", text: label }];
      await send({ message: label, autoAnalyze: true });
    }
  } catch {
    if (seq !== bindSeq) return;
  }
}

async function apply(planId: string, rerun: boolean): Promise<void> {
  const rail = useRightRail();
  const card = messages.value.find((m) => m.kind === "plan" && m.plan.id === planId);
  if (!card || card.kind !== "plan") return;
  try {
    const payload = await httpJson<{
      ok?: boolean;
      status?: string;
      new_task_id?: string;
      error?: string;
      detail?: string;
      rerun_error?: string;
    }>("/api/agent/apply", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({ plan_id: planId, rerun }),
    });
    card.plan.status = String(payload.status || "applied");
    if (payload.rerun_error) card.plan.error = String(payload.rerun_error);
    messages.value = [...messages.value];
    if (payload.new_task_id) rail.openLogs(payload.new_task_id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      card.plan.status = "conflict";
      messages.value = [...messages.value];
      return;
    }
    card.plan.status = "apply_failed";
    card.plan.error = err instanceof Error ? err.message : String(err);
    messages.value = [...messages.value];
  }
}

async function reject(planId: string): Promise<void> {
  const card = messages.value.find((m) => m.kind === "plan" && m.plan.id === planId);
  try {
    await httpJson("/api/agent/reject", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({ plan_id: planId }),
    });
    if (card && card.kind === "plan") {
      card.plan.status = "rejected";
      messages.value = [...messages.value];
    }
  } catch (err) {
    if (err instanceof ApiError && err.status === 409 && card && card.kind === "plan") {
      card.plan.status = "conflict";
      messages.value = [...messages.value];
    }
  }
}

async function searchFailed(q: string): Promise<Array<Record<string, unknown>>> {
  const qs = q ? `?q=${encodeURIComponent(q)}` : "";
  const payload = await httpJson<{ tasks?: Array<Record<string, unknown>> }>(
    `/api/agent/failed-tasks${qs}`,
    { skipNotify: true },
  );
  return payload.tasks || [];
}

export function useAgent() {
  return {
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
  };
}
