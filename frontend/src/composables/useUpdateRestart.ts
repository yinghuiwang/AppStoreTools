import { ref } from "vue";

export type TaskStatusPayload = {
  status?: string;
  result?: {
    restarting?: boolean;
    pending_install?: boolean;
    restart_blocked?: boolean;
    restart_error?: string;
    success?: boolean;
  };
};

export type PostRestartPayload = {
  boot_id?: string;
  ready?: boolean;
  pending?: boolean;
  status?: string | null;
};

const UPDATE_WAIT_MS = 20 * 60 * 1000;
const DISCONNECT_WAIT_MS = 2 * 60 * 1000;

let lastBootId = "";
let activeMode: "idle" | "update" | "disconnect" = "idle";
let resumeGeneration = 0;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export function rememberBootId(id: string) {
  if (id) lastBootId = id;
}

async function runResumeLoop(generation: number, mode: "update" | "disconnect") {
  const deadline = Date.now() + (mode === "update" ? UPDATE_WAIT_MS : DISCONNECT_WAIT_MS);
  while (Date.now() < deadline && resumeGeneration === generation) {
    try {
      const res = await fetch("/api/update/post-restart", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (res.ok) {
        const data = (await res.json()) as PostRestartPayload;
        if (lastBootId && data.boot_id && data.boot_id !== lastBootId && data.ready) {
          window.location.reload();
          return;
        }
        if (mode === "disconnect") {
          if (resumeGeneration === generation) activeMode = "idle";
          return;
        }
      }
    } catch {
      /* server is down during stop → install → start */
    }
    await sleep(1500);
  }
  if (resumeGeneration === generation) activeMode = "idle";
}

export function startResumeWatch(mode: "update" | "disconnect" = "disconnect") {
  if (activeMode === "update" && mode === "disconnect") return;
  if (activeMode === mode) return;
  activeMode = mode;
  resumeGeneration += 1;
  void runResumeLoop(resumeGeneration, mode);
}

export async function watchAfterRun(
  taskId: string,
  bootId: string,
): Promise<"restarting" | "idle"> {
  rememberBootId(bootId);
  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`/api/task/${encodeURIComponent(taskId)}/status`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (res.ok) {
        const data = (await res.json()) as TaskStatusPayload;
        const result = data.result || {};
        if (result.restart_blocked || result.restart_error) return "idle";
        if (result.restarting || result.pending_install) {
          startResumeWatch("update");
          return "restarting";
        }
        const status = String(data.status || "");
        if (["error", "canceled", "done"].includes(status)) return "idle";
      }
    } catch {
      startResumeWatch("update");
      return "restarting";
    }
    await sleep(800);
  }
  return "idle";
}

export function useUpdateRestart() {
  const awaitingRestart = ref(false);
  return {
    awaitingRestart,
    rememberBootId,
    startResumeWatch,
    watchAfterRun,
  };
}
