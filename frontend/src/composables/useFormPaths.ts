import { ref } from "vue";
import { useProfile } from "@/composables/useProfile";

const remembered = ref<Record<string, string>>({});

export function rememberFormPath(key: string, value: string) {
  const text = String(value || "").trim();
  if (!text) {
    if (!(key in remembered.value)) return;
    const next = { ...remembered.value };
    delete next[key];
    remembered.value = next;
    return;
  }
  if (remembered.value[key] === text) return;
  remembered.value = { ...remembered.value, [key]: text };
}

export function collectedFormPaths(): string[] {
  const snap = useProfile().snapshot.value;
  const paths = snap?.paths;
  const out = [
    paths?.csv,
    paths?.screenshots,
    paths?.iap,
    ...Object.values(remembered.value),
  ].filter((item): item is string => Boolean(item && String(item).trim()));
  return [...new Set(out.map((item) => String(item).trim()))];
}
