import { ref, watch } from "vue";
import { httpJson } from "@/api/http";
import { useProfile } from "@/composables/useProfile";

export type AppLocaleCheck = {
  ok: boolean;
  level?: string;
  message: string;
  detail?: { version?: string; locales?: string[] };
};

export type AppLocaleSource = "whats-new" | "urls";

const ENDPOINTS: Record<AppLocaleSource, string> = {
  "whats-new": "/api/whats-new/check",
  urls: "/api/urls/check",
};

/** Session cache: one locale/env check per App profile, shared by What's New and URLs. */
const check = ref<AppLocaleCheck | null>(null);
const checking = ref(false);
let boundProfile: string | undefined;
let inflight: Promise<AppLocaleCheck> | null = null;

function profileOf(snapshot: { current_profile?: string } | null): string {
  return snapshot?.current_profile || "";
}

function syncProfile(profile: string): void {
  if (boundProfile === profile) return;
  boundProfile = profile;
  check.value = null;
  inflight = null;
}

async function fetchCheck(source: AppLocaleSource): Promise<AppLocaleCheck> {
  checking.value = true;
  const pending = httpJson<AppLocaleCheck>(ENDPOINTS[source])
    .then((result) => {
      check.value = result;
      return result;
    })
    .finally(() => {
      checking.value = false;
      if (inflight === pending) inflight = null;
    });
  inflight = pending;
  return pending;
}

/** Wipe the session cache (profile switch in tests, or explicit reset). */
export function resetAppLocales(): void {
  boundProfile = undefined;
  check.value = null;
  checking.value = false;
  inflight = null;
}

/**
 * App Store version locales for What's New / URLs.
 * Reuses the last check in this session for the current profile.
 * Refetches on profile change or refresh(); first visit is not blocked.
 */
export function useAppLocales(source: AppLocaleSource) {
  const { snapshot } = useProfile();

  function ensure() {
    syncProfile(profileOf(snapshot.value));
    if (check.value || inflight) return;
    void fetchCheck(source);
  }

  async function refresh() {
    syncProfile(profileOf(snapshot.value));
    return fetchCheck(source);
  }

  watch(
    () => profileOf(snapshot.value),
    (profile, prev) => {
      if (prev === undefined || profile === prev) return;
      syncProfile(profile);
      ensure();
    },
  );

  return { check, checking, ensure, refresh };
}
