import { ref } from "vue";
import type { ChatMessagesData, ChatRequestParams, ChatServiceConfig, SSEChunkData } from "@tdesign-vue-next/chat";
import { ApiError, ensureSession, httpJson } from "@/api/http";
import { i18n } from "@/i18n";
import type { AgentAttachmentPayload } from "@/composables/agentAttachments";
import {
  clearAgentPageContext,
  currentAgentPageContext,
  type AgentPageContext,
} from "@/composables/useAgentContext";
import { collectedFormPaths } from "@/composables/useFormPaths";
import { useProfile } from "@/composables/useProfile";
import { useRightRail } from "@/composables/useRightRail";
import {
  historyToChatMessages,
  patchChoiceInMessages,
  patchPlanInMessages,
  type AgentPlan,
  type AgentWorkflow,
  type StoreRow,
} from "@/composables/agentStream";

export type { AgentPlan, AgentToolStatus, AgentWorkflow } from "@/composables/agentStream";

export type AgentSessionSummary = {
  id: string;
  task_id?: string | null;
  profile?: string;
  created_at?: string;
  updated_at?: string;
  title?: string;
};

type SessionPayload = {
  session?: { id?: string; task_id?: string | null; workflow?: AgentWorkflow };
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
const lastErrorText = ref("");
let engineApi: ChatEngineApi | null = null;
let bindSeq = 0;

function formatEngineError(err: unknown): string {
  if (err instanceof Response) {
    return `HTTP ${err.status} ${err.statusText || ""}`.trim();
  }
  if (err && typeof err === "object") {
    const rec = err as Record<string, unknown>;
    const message = String(rec.message || rec.error || "").trim();
    const where = String(rec.where || "").trim();
    const code = String(rec.code || rec.statusCode || "").trim();
    const lines = [message];
    if (where && !message.includes(where)) lines.push(where);
    else if (!message && (where || code)) lines.push([code, where].filter(Boolean).join(" "));
    return lines.filter(Boolean).join("\n");
  }
  return String(err || "").trim();
}

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

function compactPageContext(ctx: AgentPageContext): AgentPageContext {
  const out: AgentPageContext = {};
  const assign = (key: keyof AgentPageContext, value: unknown) => {
    if (key === "fields") {
      if (!value || typeof value !== "object" || Array.isArray(value)) return;
      const fields: Record<string, string> = {};
      for (const [name, text] of Object.entries(value as Record<string, unknown>)) {
        if (text == null) continue;
        const trimmed = String(text);
        if (trimmed) fields[name] = trimmed;
      }
      if (Object.keys(fields).length) out.fields = fields;
      return;
    }
    if (typeof value === "string" && value.trim()) {
      (out as Record<string, string>)[key] = value;
    }
  };
  for (const key of Object.keys(ctx) as Array<keyof AgentPageContext>) {
    assign(key, ctx[key]);
  }
  return out;
}

function pageContextForRequest(): AgentPageContext {
  const snap = useProfile().snapshot.value;
  const paths = snap?.paths;
  const overrides = currentAgentPageContext();
  return compactPageContext({
    ...overrides,
    route: typeof window !== "undefined" ? window.location.pathname : overrides.route,
    profile: snap?.current_profile || overrides.profile,
    csv_path: paths?.csv || overrides.csv_path,
    screenshots_path: paths?.screenshots || overrides.screenshots_path,
    iap_path: paths?.iap || overrides.iap_path,
  });
}

function aguiRequestInit(params: ChatRequestParams): RequestInit {
  return {
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
      page_context: pageContextForRequest(),
    }),
  };
}

async function prepareAguiRequest(params: ChatRequestParams): Promise<RequestInit> {
  const init = aguiRequestInit(params);
  await ensureSession();
  armAgui401Retry();
  return init;
}

function armAgui401Retry() {
  const nativeFetch = globalThis.fetch.bind(globalThis);
  const wrapped: typeof fetch = async (input, init) => {
    const url =
      typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
    if (!url.includes("/api/agent/agui")) return nativeFetch(input, init);
    if (globalThis.fetch === wrapped) globalThis.fetch = nativeFetch;
    const first = await nativeFetch(input, init);
    if (first.status !== 401) return first;
    try {
      await httpJson("/api/agent/sessions", { skipNotify: true });
    } catch {
      await ensureSession();
    }
    return nativeFetch(input, init);
  };
  globalThis.fetch = wrapped;
}

export const agentChatServiceConfig: ChatServiceConfig = {
  endpoint: "/api/agent/agui",
  protocol: "agui",
  stream: true,
  timeout: 0,
  onRequest: (params) => prepareAguiRequest(params),
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
    if (data.type === "RUN_ERROR") {
      lastErrorText.value = formatEngineError(data);
    }
    return null;
  },
  onError: (err) => {
    if (!lastErrorText.value) lastErrorText.value = formatEngineError(err);
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
  lastErrorText.value = "";
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
  replaceMessages(
    historyToChatMessages(payload.messages || [], payload.plans || [], session.workflow),
  );
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
  clearAgentPageContext();
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

function findLatestPendingPlan(): AgentPlan | null {
  const messages = engineApi?.getMessages() || [];
  let found: AgentPlan | null = null;
  for (const msg of messages) {
    if (msg.role !== "assistant" || !msg.content) continue;
    for (const block of msg.content) {
      if (block.type !== "activity") continue;
      const plan = (block.data as unknown as { content?: AgentPlan } | undefined)?.content;
      if (plan?.id && plan.status === "pending" && (plan.mutations || []).length) {
        found = plan;
      }
    }
  }
  return found;
}

function looksLikeWriteBackChoice(optionId: string): boolean {
  return /apply|write|writeback|write_back|commit/i.test(optionId);
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
        confirm: true,
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

function writeChoicePatch(patch: Partial<AgentWorkflow>) {
  const current = engineApi?.getMessages() || [];
  replaceMessages(patchChoiceInMessages(current, patch));
}

async function choose(optionId: string): Promise<void> {
  const sid = sessionId.value;
  const id = String(optionId || "").trim();
  if (!sid || !id) return;
  try {
    const payload = await httpJson<{ ok?: boolean; prompt?: string }>("/api/agent/choose", {
      method: "POST",
      skipNotify: true,
      body: JSON.stringify({
        session_id: sid,
        option_id: id,
        confirm: true,
      }),
    });
    writeChoicePatch({ phase: "confirmed", selected_id: id });
    const pending = looksLikeWriteBackChoice(id) ? findLatestPendingPlan() : null;
    if (pending) {
      await apply(pending.id, false);
      return;
    }
    const prompt = String(payload.prompt || "").trim();
    if (prompt) await send({ message: prompt });
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      writeChoicePatch({ phase: "confirmed", selected_id: id });
    }
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
    lastErrorText,
    sessions,
    send,
    stop,
    bindTask,
    apply,
    choose,
    reject,
    searchFailed,
    restoreMessages,
    listSessions,
    openSession,
    createSession,
    appliedTick,
  };
}
