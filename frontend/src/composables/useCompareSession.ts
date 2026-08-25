import { computed, ref } from "vue";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import { useTaskLog } from "@/composables/useTaskLog";

export type CompareTaskStart = { task_id: string };
export type CompareResultBase = { ok?: boolean; error?: string };

export type CompareSessionOptions<TResult extends CompareResultBase> = {
  cacheKey: () => string;
  hasProfile: () => boolean;
  start: () => Promise<CompareTaskStart>;
  applySuccess: (result: TResult, key: string) => void;
  applyFailure: () => void;
  onNoProfile?: () => void;
  onInvalidate?: () => void;
  isFresh?: (key: string) => boolean;
};

/**
 * Shared Listing/IAP compare runner. Domain files keep cache keys, payloads,
 * and markDirty/invalidate rules so preview/upload UX does not change.
 */
export function createCompareSession<TResult extends CompareResultBase>(
  opts: CompareSessionOptions<TResult>,
) {
  const planError = ref("");
  const planOk = ref(true);
  const planLoading = ref(false);
  const planLoadedKey = ref("");
  const compareTaskId = ref("");
  const compareStartedAt = ref(0);
  let compareInFlight: { key: string; promise: Promise<void> } | null = null;
  let compareGen = 0;

  function getInFlight() {
    return compareInFlight;
  }

  function invalidateCompare() {
    planLoadedKey.value = "";
    opts.onInvalidate?.();
  }

  const compared = computed(() => !!planLoadedKey.value && planLoadedKey.value === opts.cacheKey());

  async function runCompare(key: string) {
    const { subscribeIfNeeded, waitForTaskResult } = useTaskLog();
    const gen = ++compareGen;
    planLoading.value = true;
    planError.value = "";
    compareStartedAt.value = Date.now();
    try {
      const { task_id } = await opts.start();
      if (gen !== compareGen) return;
      compareTaskId.value = task_id;
      subscribeIfNeeded(task_id);
      const state = await waitForTaskResult<TResult>(task_id);
      if (gen !== compareGen) return;
      const result = (state.result || {}) as TResult;
      if (state.status !== "done") {
        planOk.value = false;
        planError.value = result.error || state.status;
        opts.applyFailure();
        planLoadedKey.value = "";
        return;
      }
      opts.applySuccess(result, key);
      planLoadedKey.value = key;
      planOk.value = result.ok !== false;
      planError.value = planOk.value ? "" : result.error || "";
    } catch (err) {
      if (gen !== compareGen) return;
      planOk.value = false;
      if (err instanceof ApiError) planError.value = apiErrorMessage(err);
      else planError.value = String(err);
      opts.applyFailure();
      planLoadedKey.value = "";
    } finally {
      if (gen === compareGen) {
        planLoading.value = false;
        compareTaskId.value = "";
        compareStartedAt.value = 0;
      }
    }
  }

  async function ensureCompare(forceOpts?: { force?: boolean }) {
    const force = !!forceOpts?.force;
    if (!opts.hasProfile()) {
      planError.value = "";
      planOk.value = true;
      planLoadedKey.value = "";
      opts.onNoProfile?.();
      return;
    }
    const key = opts.cacheKey();
    const extraFresh = opts.isFresh ? opts.isFresh(key) : true;
    if (!force && planLoadedKey.value === key && extraFresh && !planLoading.value) return;
    if (compareInFlight && compareInFlight.key === key && !force) {
      await compareInFlight.promise;
      return;
    }
    const promise = runCompare(key);
    compareInFlight = { key, promise };
    try {
      await promise;
    } finally {
      if (compareInFlight?.promise === promise) compareInFlight = null;
    }
  }

  return {
    planError,
    planOk,
    planLoading,
    planLoadedKey,
    compareTaskId,
    compareStartedAt,
    compared,
    ensureCompare,
    invalidateCompare,
    getInFlight,
  };
}

export async function postCompareTask(url: string, body: unknown): Promise<CompareTaskStart> {
  return httpJson<CompareTaskStart>(url, {
    method: "POST",
    skipNotify: true,
    body: JSON.stringify(body),
  });
}
