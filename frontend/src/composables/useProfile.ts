import { ref, type Ref } from "vue";
import { httpJson } from "@/api/http";
import type { Bootstrap } from "@/api/types";

const snapshot: Ref<Bootstrap | null> = ref(null);

export function useProfile() {
  async function refresh(): Promise<Bootstrap> {
    const data = await httpJson<Bootstrap>("/api/bootstrap");
    snapshot.value = data;
    return data;
  }

  async function switchProfile(name: string): Promise<void> {
    await httpJson(`/api/switch-profile?profile=${encodeURIComponent(name)}`);
    await refresh();
  }

  return { snapshot, refresh, switchProfile };
}
