import { ref } from "vue";
import type { ChatMessagesData, ChatRequestParams, ChatServiceConfig, SSEChunkData } from "@tdesign-vue-next/chat";
import { ApiError, httpJson } from "@/api/http";
import { i18n } from "@/i18n";
import type { AgentAttachmentPayload } from "@/composables/agentAttachments";
import { collectedFormPaths } from "@/composables/useFormPaths";
import { useRightRail } from "@/composables/useRightRail";
import {
  historyToChatMessages,
  patchPlanInMessages,
  type AgentPlan,
  type StoreRow,
} from "@/composables/agentStream";

export type { AgentPlan, AgentToolStatus } from "@/composables/agentStream";

export type AgentSessionSummary = {
  id: string;
  task_id?: string | null;
  profile?: string;
  created_at?: string;
  updated_at?: string;
  title?: string;
};

type SessionPayload = {
  session?: { id?: string; task_id?: string | null };
  messages?: StoreRow[];
  plans?: AgentPlan[];
};

type ChatEngineApi = {
  sendUserMessage: (params: ChatRequestParams) => Promise<void>;
  abortChat: () => Promise<void>;
  setMessages: (messages: ChatMessagesData[], mode?: "replace" | "prepend" | "append") => void;
  getMessages: () => ChatMessagesData[];
};

const sessionId = ref("");
const boundTaskId = ref("");
const pendingAutoAnalyze = ref(false);
const pendingAttachments = ref<AgentAttachmentPayload[]>([]);
const appliedTick = ref(0);
const sessions = ref<AgentSessionSummary[]>([]);
let engineApi: ChatEngineApi | null = null;
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

function parseChunkData(chunk: SSEChunkData): Record<string, unknown> | null {
  const raw = chunk?.data;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) return raw as Record<string, unknown>;
  if (typeof raw !== "string" || !raw.trim()) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function applySessionValue(value: unknown) {
  if (!value || typeof value !== "object") return;
  const session = value as { session_id?: string; task_id?: string };
  if (session.session_id) sessionId.value = String(session.session_id);
  if (session.task_id) boundTaskId.value = String(session.task_id);
  syncRail();
}

async function listSessions(): Promise<void> {
  try {
    const payload = await httpJson<{ sessions?: AgentSessionSummary[] }>("/api/agent/sessions", {
      skipNotify: true,
    });
    sessions.value = payload.sessions || [];
  } catch {
    /* keep last list */
  }
}

export const agentChatServiceConfig: ChatServiceConfig = {
  endpoint: "/api/agent/agui",
  protocol: "agui",
  stream: true,
  timeout: 0,
  onRequest: (params) => ({
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({
      threadId: sessionId.value || undefined,
      runId: params.messageID,
      prompt: params.prompt,
      message: params.prompt,
      session_id: sessionId.value || undefined,
      task_id: boundTaskId.value || undefined,
      auto_analyze: pendingAutoAnalyze.value || Boolean(params.auto_analyze),
      form_paths: [
        ...collectedFormPaths(),
        ...pendingAttachments.value.map((item) => item.path || "").filter(Boolean),
      ],
      attachments: pendingAttachments.value,
    }),
  }),
  onMessage: (chunk) => {
    const data = parseChunkData(chunk);
    if (!data) return null;
    if (data.type === "CUSTOM" && data.name === "session") {
      applySessionValue(data.value);
      void listSessions();
    }
    if (data.type === "RUN_STARTED" && data.threadId) {
      sessionId.value = String(data.threadId);
      syncRail();
    }
    if (data.type === "CUSTOM" && data.name === "done") {
      applySessionValue(data.value);
      void listSessions();
    }
    return null;
  },
  onAbort: async () => {
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
  },
};

export function attachAgentChatEngine(api: ChatEngineApi) {
  engineApi = api;
}

export function detachAgentChatEngine() {
  engineApi = null;
}

function replaceMessages(next: ChatMessagesData[]) {
  engineApi?.setMessages(next, "replace");
}

async function send(opts: {
  message: string;
  autoAnalyze?: boolean;
  attachments?: AgentAttachmentPayload[];
}): Promise<void> {
  if (!engineApi) return;
  pendingAutoAnalyze.value = opts.autoAnalyze === true;
  pendingAttachments.value = opts.attachments || [];
  try {
    await engineApi.sendUserMessage({
      prompt: opts.message,
      auto_analyze: opts.autoAnalyze === true,
    });
  } finally {
    pendingAutoAnalyze.value = false;
    pendingAttachments.value = [];
  }
}

async function stop(): Promise<void> {
  await engineApi?.abortChat();
}

function ingestSessionPayload(payload: SessionPayload) {
  const session = payload.session || {};
  if (session.id) {
    sessionId.value = String(session.id);
    boundTaskId.value = session.task_id ? String(session.task_id) : "";
  }
  syncRail();
  replaceMessages(historyToChatMessages(payload.messages || [], payload.plans || []));
}

async function restoreMessages(): Promise<void> {
  const rail = useRightRail();
  const sid = sessionId.value || rail.sessionId.value;
  const tid = boundTaskId.value || rail.boundTaskId.value;
  const pending = listSessions();
  if (!sid && !tid) {
    await pending;
    return;
  }
  const qs = sid
    ? `session_id=${encodeURIComponent(sid)}`
    : `task_id=${encodeURIComponent(tid)}`;
  try {
    const payload = await httpJson<SessionPayload>(`/api/agent/sessions?${qs}`, {
      skipNotify: true,
    });
    ingestSessionPayload(payload);
  } catch {
    /* keep chrome without crashing */
  }
  await pending;
}

async function openSession(id: string): Promise<void> {
  const sid = String(id || "");
  if (!sid || sid === sessionId.value) return;
  const seq = ++bindSeq;
  await stop();
  if (seq !== bindSeq) return;
  try {
    const payload = await httpJson<SessionPayload>(
      `/api/agent/sessions?session_id=${encodeURIComponent(sid)}`,
      { skipNotify: true },
    );
    if (seq !== bindSeq) return;
    ingestSessionPayload(payload);
    await listSessions();
  } catch {
    if (seq !== bindSeq) return;
  }
}

async function createSession(): Promise<void> {
  const seq = ++bindSeq;
  await stop();
  if (seq !== bindSeq) return;
  try {
    const payload = await httpJson<SessionPayload>("/api/agent/sessions", {
      method: "POST",
      skipNotify: true,
      body: "{}",
    });
    if (seq !== bindSeq) return;
    ingestSessionPayload(payload);
    await listSessions();
  } catch {
    if (seq !== bindSeq) return;
  }
}

async function bindTask(taskId: string, opts?: { autoAnalyze?: boolean }): Promise<void> {
  const seq = ++bindSeq;
  boundTaskId.value = String(taskId);
  sessionId.value = "";
  replaceMessages([]);
  syncRail();
  try {
    const payload = await httpJson<SessionPayload>(
      `/api/agent/sessions?task_id=${encodeURIComponent(taskId)}`,
      { skipNotify: true },
    );
    if (seq !== bindSeq) return;
    ingestSessionPayload(payload);
    await listSessions();
    const history = payload.messages || [];
    if (opts?.autoAnalyze === true && history.length === 0) {
      await send({ message: t("agent.auto_analyze_label"), autoAnalyze: true });
    }
  } catch {
    if (seq !== bindSeq) return;
  }
}

function findPlan(planId: string): AgentPlan | null {
  const messages = engineApi?.getMessages() || [];
  for (const msg of messages) {
    if (msg.role !== "assistant" || !msg.content) continue;
    for (const block of msg.content) {
      if (block.type !== "activity") continue;
      const plan = (block.data as unknown as { content?: AgentPlan } | undefined)?.content;
      if (plan?.id === planId) return plan;
    }
  }
  return null;
}

function writePlanPatch(planId: string, patch: Partial<AgentPlan>) {
  const current = engineApi?.getMessages() || [];
  replaceMessages(patchPlanInMessages(current, planId, patch));
}

async function apply(planId: string, rerun: boolean): Promise<void> {
  const rail = useRightRail();
  const plan = findPlan(planId);
  if (!plan) return;
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
      body: JSON.stringify({
        plan_id: planId,
        rerun,
        form_paths: collectedFormPaths(),
      }),
    });
    writePlanPatch(planId, {
      status: String(payload.status || "applied"),
      error: payload.rerun_error ? String(payload.rerun_error) : undefined,
    });
    if (payload.new_task_id) rail.openLogs(payload.new_task_id);
    appliedTick.value += 1;
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      writePlanPatch(planId, { status: "conflict" });
      return;
    }
    writePlanPatch(planId, {
      status: "apply_failed",
      error: err instanceof Error ? err.message : String(err),
    });
  }
}

async function reject(planId: string): Promise<void> {
  try {
    await httpJson("/api/agent/reject", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({ plan_id: planId }),
    });
    writePlanPatch(planId, { status: "rejected" });
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      writePlanPatch(planId, { status: "conflict" });
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
    pendingAutoAnalyze,
    sessions,
    send,
    stop,
    bindTask,
    apply,
    reject,
    searchFailed,
    restoreMessages,
    listSessions,
    openSession,
    createSession,
    appliedTick,
  };
}
