import { ref } from "vue";
import { ApiError, httpJson } from "@/api/http";

type Entry = { name: string; path: string; is_dir: boolean };
type BrowseOk = {
  ok: true;
  current_path: string;
  mode: "dir" | "file";
  ext: string;
  entries: Entry[];
};

const open = ref(false);
const mode = ref<"dir" | "file">("dir");
const ext = ref("");
const currentPath = ref(".");
const entries = ref<Entry[]>([]);
const error = ref("");
const loading = ref(false);
let resolvePick: ((path: string | null) => void) | null = null;

async function load(path: string) {
  error.value = "";
  loading.value = true;
  try {
    const qs = new URLSearchParams({ path, mode: mode.value, ext: ext.value });
    const data = await httpJson<BrowseOk>(`/api/browse?${qs}`, { skipNotify: true });
    currentPath.value = data.current_path;
    entries.value = data.entries;
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      error.value = "Forbidden";
      return;
    }
    throw err;
  } finally {
    loading.value = false;
  }
}

export function useBrowse() {
  function pick(opts: { mode: "dir" | "file"; ext?: string; initialPath?: string }) {
    mode.value = opts.mode;
    ext.value = opts.ext || "";
    open.value = true;
    void load(opts.initialPath || ".");
    return new Promise<string | null>((resolve) => {
      resolvePick = resolve;
    });
  }
  function choose(path: string) {
    open.value = false;
    resolvePick?.(path);
    resolvePick = null;
  }
  function cancel() {
    open.value = false;
    resolvePick?.(null);
    resolvePick = null;
  }
  function enter(entry: Entry) {
    if (entry.is_dir) void load(entry.path);
    else if (mode.value === "file") choose(entry.path);
  }
  return { open, mode, ext, currentPath, entries, error, loading, pick, choose, cancel, enter, load };
}
