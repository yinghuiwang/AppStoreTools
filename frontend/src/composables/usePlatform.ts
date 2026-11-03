import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useProfile } from "@/composables/useProfile";

const TOOLCHAIN = ["build", "deploy", "release"];

export function usePlatform() {
  const { snapshot } = useProfile();
  const { t } = useI18n();
  const unsupported = computed(() => new Set(snapshot.value?.platform?.unsupported ?? []));

  function blocked(feature: string): boolean {
    if (TOOLCHAIN.includes(feature)) {
      return TOOLCHAIN.some((name) => unsupported.value.has(name));
    }
    return unsupported.value.has(feature);
  }

  const unsupportedText = computed(() => t("platform.unsupported"));
  return { blocked, unsupportedText };
}
