import { ref } from "vue";

const WIDTH_KEY = "asc.rightRail.width";
const LEGACY_WIDTH_KEY = "asc.agentPanel.width";
const CHROME_KEY = "asc.rightRail.chrome";

function clampWidth(n: number): number {
  const max = Math.min(720, Math.floor(window.innerWidth * 0.5) || 720);
  return Math.min(max, Math.max(280, n));
}

function readWidth(): number {
  const raw = localStorage.getItem(WIDTH_KEY);
  if (raw != null) {
    const n = Number(raw);
    return Number.isFinite(n) ? clampWidth(n) : 390;
  }
  const legacy = localStorage.getItem(LEGACY_WIDTH_KEY);
  if (legacy != null) {
    const n = Number(legacy);
    if (Number.isFinite(n)) {
      const w = clampWidth(n);
      localStorage.setItem(WIDTH_KEY, String(w));
      return w;
    }
  }
  return 390;
}

const open = ref(false);
const tab = ref<"agent" | "logs">("agent");
const width = ref(390);
const sessionId = ref("");
const boundTaskId = ref("");
const logTaskId = ref("");
let hydrated = false;

function persistChrome() {
  sessionStorage.setItem(
    CHROME_KEY,
    JSON.stringify({
      open: open.value,
      tab: tab.value,
      sessionId: sessionId.value,
      boundTaskId: boundTaskId.value,
      logTaskId: logTaskId.value,
    }),
  );
}

function hydrate() {
  if (hydrated) return;
  hydrated = true;
  width.value = readWidth();
  const raw = sessionStorage.getItem(CHROME_KEY);
  if (!raw) return;
  try {
    const c = JSON.parse(raw) as Partial<{
      open: boolean;
      tab: "agent" | "logs";
      sessionId: string;
      boundTaskId: string;
      logTaskId: string;
    }>;
    open.value = Boolean(c.open);
    if (c.tab === "agent" || c.tab === "logs") tab.value = c.tab;
    sessionId.value = String(c.sessionId || "");
    boundTaskId.value = String(c.boundTaskId || "");
    logTaskId.value = String(c.logTaskId || "");
  } catch {
    /* ignore */
  }
}

export function useRightRail() {
  hydrate();

  function openLogs(taskId: string) {
    logTaskId.value = taskId;
    tab.value = "logs";
    open.value = true;
    persistChrome();
    void import("@/composables/useTaskLog").then(({ useTaskLog }) => {
      useTaskLog().subscribe(taskId);
    });
  }

  function openAgent(opts?: { taskId?: string; autoAnalyze?: boolean }) {
    tab.value = "agent";
    open.value = true;
    persistChrome();
    if (opts?.taskId) {
      void import("@/composables/useAgent").then(({ useAgent }) => {
        useAgent().bindTask(opts.taskId!, { autoAnalyze: opts.autoAnalyze === true });
      });
    }
  }

  function collapse() {
    open.value = false;
    persistChrome();
  }

  function setWidth(px: number) {
    width.value = clampWidth(px);
    localStorage.setItem(WIDTH_KEY, String(width.value));
  }

  return {
    open,
    tab,
    width,
    sessionId,
    boundTaskId,
    logTaskId,
    openLogs,
    openAgent,
    collapse,
    setWidth,
    persistChrome,
  };
}
