import { computed, reactive, ref, toValue, type MaybeRefOrGetter } from "vue";
import { httpJson } from "@/api/http";
import { parseLogEventData } from "@/utils/logLevel";

type TaskProgress = {
  pct: number;
  msg: string;
  phase: string;
  phase_label: string;
  phase_index: number;
  phase_total: number;
};

type LogLine = { seq: number; message: string; level?: string };
type Connection = "idle" | "connecting" | "live" | "reconnecting" | "closed";

type Channel = {
  lines: LogLine[];
  status: string;
  progress: TaskProgress;
  connection: Connection;
  lastSeq: number;
  retries: number;
};

type Runtime = {
  source: EventSource | null;
  reconnectTimer: number | null;
  intentionalClose: boolean;
};

const EMPTY_LINES: LogLine[] = [];
const EMPTY_PROGRESS: TaskProgress = {
  pct: 0, msg: "", phase: "", phase_label: "", phase_index: 0, phase_total: 0,
};

const MAX_CHANNEL_LINES = 2000;
const MAX_CHANNELS = 20;
const TERMINAL_STATUS = new Set(["done", "error", "canceled"]);

const channels = reactive<Record<string, Channel>>({});
const runtime = new Map<string, Runtime>();
const activeTaskId = ref("");
const logTaskId = activeTaskId;
const follow = ref(true);

const lines = computed(() => channels[activeTaskId.value]?.lines ?? EMPTY_LINES);
const status = computed(() => channels[activeTaskId.value]?.status ?? "");
const progress = computed(() => channels[activeTaskId.value]?.progress ?? EMPTY_PROGRESS);
const connection = computed(() => channels[activeTaskId.value]?.connection ?? "idle");

function emptyProgress(): TaskProgress {
  return { pct: 0, msg: "", phase: "", phase_label: "", phase_index: 0, phase_total: 0 };
}

function appendLine(ch: Channel, line: LogLine) {
  ch.lines.push(line);
  if (ch.lines.length > MAX_CHANNEL_LINES) {
    ch.lines.splice(0, ch.lines.length - MAX_CHANNEL_LINES);
  }
}

function pruneChannels(keepId?: string) {
  const ids = Object.keys(channels);
  if (ids.length <= MAX_CHANNELS) return;
  const drop = ids.filter((id) => (
    id !== keepId
    && id !== activeTaskId.value
    && TERMINAL_STATUS.has(channels[id]?.status || "")
  ));
  while (Object.keys(channels).length > MAX_CHANNELS && drop.length) {
    const id = drop.shift();
    if (!id) break;
    closeSource(id);
    delete channels[id];
    runtime.delete(id);
  }
}

function ensureChannel(taskId: string): Channel {
  if (!channels[taskId]) {
    channels[taskId] = {
      lines: [],
      status: "",
      progress: emptyProgress(),
      connection: "idle",
      lastSeq: 0,
      retries: 0,
    };
    pruneChannels(taskId);
  }
  if (!runtime.has(taskId)) {
    runtime.set(taskId, { source: null, reconnectTimer: null, intentionalClose: false });
  }
  return channels[taskId];
}

function closeSource(taskId: string) {
  const rt = runtime.get(taskId);
  if (!rt) return;
  rt.intentionalClose = true;
  if (rt.reconnectTimer != null) {
    window.clearTimeout(rt.reconnectTimer);
    rt.reconnectTimer = null;
  }
  rt.source?.close();
  rt.source = null;
}

function subscribeIfNeeded(taskId: string) {
  if (!taskId) return;
  const ch = ensureChannel(taskId);
  const rt = runtime.get(taskId);
  if (rt?.source) return;
  if (rt?.reconnectTimer != null) return;
  if (ch.connection === "connecting" || ch.connection === "live" || ch.connection === "reconnecting") return;
  if (["done", "error", "canceled"].includes(ch.status) && (ch.lines.length > 0 || ch.lastSeq > 0)) {
    return;
  }
  openEventSource(taskId, ch.lastSeq);
}

function setActiveTask(taskId: string) {
  if (!taskId) return;
  if (activeTaskId.value !== taskId) {
    activeTaskId.value = taskId;
    void import("@/composables/useRightRail").then(({ useRightRail }) => {
      const rail = useRightRail();
      if (rail.logTaskId.value === taskId) return;
      rail.logTaskId.value = taskId;
      rail.persistChrome();
    });
  }
  subscribeIfNeeded(taskId);
}

function subscribe(taskId: string) {
  setActiveTask(taskId);
}

function openEventSource(taskId: string, after: number) {
  const ch = ensureChannel(taskId);
  const rt = runtime.get(taskId);
  if (!rt) return;
  closeSource(taskId);
  rt.intentionalClose = false;
  ch.connection = "connecting";
  const url = `/api/task/${encodeURIComponent(taskId)}/stream?after=${encodeURIComponent(String(after))}`;
  const source = new EventSource(url);
  rt.source = source;
  source.addEventListener("log", (event) => {
    if (runtime.get(taskId)?.source !== source) return;
    ch.retries = 0;
    ch.connection = "live";
    const seq = Number((event as MessageEvent).lastEventId || ch.lastSeq);
    ch.lastSeq = Number.isFinite(seq) ? seq : ch.lastSeq;
    const parsed = parseLogEventData((event as MessageEvent).data);
    appendLine(ch, { seq: ch.lastSeq, message: parsed.message, level: parsed.level });
  });
  source.addEventListener("progress", (event) => {
    if (runtime.get(taskId)?.source !== source) return;
    try {
      const raw = JSON.parse((event as MessageEvent).data || "{}") as Partial<TaskProgress>;
      ch.progress = {
        pct: Number(raw.pct || 0),
        msg: String(raw.msg || ""),
        phase: String(raw.phase || ""),
        phase_label: String(raw.phase_label || ""),
        phase_index: Number(raw.phase_index || 0),
        phase_total: Number(raw.phase_total || 0),
      };
    } catch {
      /* ignore invalid progress */
    }
  });
  const finish = (value: string) => {
    if (runtime.get(taskId)?.source !== source) return;
    ch.status = value;
    ch.connection = "closed";
    closeSource(taskId);
    pruneChannels();
  };
  source.addEventListener("done", () => finish("done"));
  source.addEventListener("canceled", () => finish("canceled"));
  source.addEventListener("error_event", (event) => {
    if (runtime.get(taskId)?.source !== source) return;
    ch.status = "error";
    appendLine(ch, {
      seq: ch.lastSeq,
      message: (event as MessageEvent).data,
      level: "error",
    });
    ch.connection = "closed";
    closeSource(taskId);
    pruneChannels();
  });
  source.onerror = () => {
    if (runtime.get(taskId)?.source !== source) return;
    if (runtime.get(taskId)?.intentionalClose) return;
    void recover(taskId);
  };
}

async function recover(taskId: string) {
  const ch = channels[taskId];
  const rt = runtime.get(taskId);
  if (!ch || !rt) return;
  closeSource(taskId);
  ch.connection = "reconnecting";
  try {
    const state = await httpJson<{ status: string }>(
      `/api/task/${encodeURIComponent(taskId)}/status`,
    );
    const st = String(state.status || "");
    if (["done", "error", "canceled"].includes(st)) {
      ch.status = st;
      ch.connection = "closed";
      pruneChannels();
      return;
    }
  } catch {
    /* fall through to reconnect */
  }
  if (ch.retries >= 5) {
    ch.connection = "closed";
    return;
  }
  ch.retries += 1;
  rt.intentionalClose = false;
  rt.reconnectTimer = window.setTimeout(() => {
    rt.reconnectTimer = null;
    ch.connection = "connecting";
    openEventSource(taskId, ch.lastSeq);
  }, 1000);
}

function waitUntilTerminal(taskId: string, opts?: { timeoutMs?: number }): Promise<string> {
  const timeoutMs = opts?.timeoutMs ?? 15 * 60 * 1000;
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = () => {
      const status = channels[taskId]?.status || "";
      if (TERMINAL_STATUS.has(status)) {
        resolve(status);
        return;
      }
      if (Date.now() - started > timeoutMs) {
        reject(new Error("task wait timeout"));
        return;
      }
      window.setTimeout(tick, 200);
    };
    tick();
  });
}

async function waitForTaskResult<T = unknown>(
  taskId: string,
): Promise<{ status: string; result?: T }> {
  subscribeIfNeeded(taskId);
  try {
    await waitUntilTerminal(taskId);
  } catch {
    /* still fetch the latest status after timeout */
  }
  return httpJson<{ status: string; result?: T }>(
    `/api/task/${encodeURIComponent(taskId)}/status`,
    { skipNotify: true },
  );
}

function disconnect(taskId?: string) {
  const ids = taskId ? [taskId] : Object.keys(channels);
  for (const id of ids) {
    closeSource(id);
    const ch = channels[id];
    if (ch) ch.connection = "closed";
  }
}

async function cancel(taskId?: string) {
  const id = taskId || activeTaskId.value;
  if (!id) return;
  await httpJson(`/api/task/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

function clearLocal() {
  const ch = channels[activeTaskId.value];
  if (ch) ch.lines = [];
}

function channelOf(taskId: MaybeRefOrGetter<string>) {
  return {
    status: computed(() => {
      const id = toValue(taskId);
      return id && channels[id] ? channels[id].status : "";
    }),
    progress: computed(() => {
      const id = toValue(taskId);
      return id && channels[id] ? channels[id].progress : EMPTY_PROGRESS;
    }),
    lines: computed(() => {
      const id = toValue(taskId);
      return id && channels[id] ? channels[id].lines : EMPTY_LINES;
    }),
    connection: computed(() => {
      const id = toValue(taskId);
      return id && channels[id] ? channels[id].connection : "idle";
    }),
  };
}

export function useTaskLog() {
  return {
    activeTaskId,
    logTaskId,
    channels,
    lines,
    status,
    progress,
    connection,
    follow,
    channelOf,
    setActiveTask,
    subscribe,
    subscribeIfNeeded,
    waitUntilTerminal,
    waitForTaskResult,
    disconnect,
    cancel,
    clearLocal,
  };
}
