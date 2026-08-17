import { ref } from "vue";
import { httpJson } from "@/api/http";

type TaskProgress = {
  pct: number;
  msg: string;
  phase: string;
  phase_label: string;
  phase_index: number;
  phase_total: number;
};

type LogLine = { seq: number; message: string };

const logTaskId = ref("");
const lines = ref<LogLine[]>([]);
const status = ref("");
const progress = ref<TaskProgress>({
  pct: 0, msg: "", phase: "", phase_label: "", phase_index: 0, phase_total: 0,
});
const connection = ref<"idle" | "connecting" | "live" | "reconnecting" | "closed">("idle");
const follow = ref(true);

let source: EventSource | null = null;
let retries = 0;
let lastSeq = 0;
let reconnectTimer: number | null = null;
let intentionalClose = false;

function closeSource() {
  intentionalClose = true;
  if (reconnectTimer != null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  source?.close();
  source = null;
}

function subscribeIfNeeded(taskId: string) {
  if (!taskId) return;
  if (logTaskId.value === taskId) return;
  subscribe(taskId);
}

function subscribe(taskId: string) {
  closeSource();
  logTaskId.value = taskId;
  lines.value = [];
  lastSeq = 0;
  retries = 0;
  status.value = "";
  progress.value = {
    pct: 0, msg: "", phase: "", phase_label: "", phase_index: 0, phase_total: 0,
  };
  connection.value = "connecting";
  openEventSource(taskId, 0);
}

function openEventSource(taskId: string, after: number) {
  closeSource();
  intentionalClose = false;
  const url = `/api/task/${encodeURIComponent(taskId)}/stream?after=${encodeURIComponent(String(after))}`;
  source = new EventSource(url);
  source.addEventListener("log", (event) => {
    retries = 0;
    connection.value = "live";
    const seq = Number((event as MessageEvent).lastEventId || lastSeq);
    lastSeq = Number.isFinite(seq) ? seq : lastSeq;
    lines.value = [...lines.value, { seq: lastSeq, message: (event as MessageEvent).data }];
  });
  source.addEventListener("progress", (event) => {
    try {
      const raw = JSON.parse((event as MessageEvent).data || "{}") as Partial<TaskProgress>;
      progress.value = {
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
    status.value = value;
    connection.value = "closed";
    closeSource();
  };
  source.addEventListener("done", () => finish("done"));
  source.addEventListener("canceled", () => finish("canceled"));
  source.addEventListener("error_event", (event) => {
    status.value = "error";
    lines.value = [...lines.value, { seq: lastSeq, message: (event as MessageEvent).data }];
    connection.value = "closed";
    closeSource();
  });
  source.onerror = () => {
    if (intentionalClose) return;
    void recover(taskId);
  };
}

async function recover(taskId: string) {
  closeSource();
  connection.value = "reconnecting";
  try {
    const state = await httpJson<{ status: string }>(
      `/api/task/${encodeURIComponent(taskId)}/status`,
    );
    const st = String(state.status || "");
    if (["done", "error", "canceled"].includes(st)) {
      status.value = st;
      connection.value = "closed";
      return;
    }
  } catch {
    /* fall through to reconnect */
  }
  if (retries >= 5) {
    connection.value = "closed";
    return;
  }
  retries += 1;
  reconnectTimer = window.setTimeout(() => {
    connection.value = "connecting";
    openEventSource(taskId, lastSeq);
  }, 1000);
}

function disconnect() {
  closeSource();
  connection.value = "closed";
}

async function cancel() {
  if (!logTaskId.value) return;
  await httpJson(`/api/task/${encodeURIComponent(logTaskId.value)}/cancel`, { method: "POST" });
}

function clearLocal() {
  lines.value = [];
}

export function useTaskLog() {
  return {
    logTaskId, lines, status, progress, connection, follow,
    subscribe, subscribeIfNeeded, disconnect, cancel, clearLocal,
  };
}
