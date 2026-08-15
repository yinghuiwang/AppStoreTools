import { computed, ref } from "vue";

export type TaskPagePhase = "form" | "run";

/** Page-local form/run switch. Deep links that only prefill stay on "form". */
export function useTaskPagePhase(initial: TaskPagePhase = "form") {
  const phase = ref<TaskPagePhase>(initial);
  const isForm = computed(() => phase.value === "form");
  const isRun = computed(() => phase.value === "run");

  function enterRun() {
    phase.value = "run";
  }

  function backToForm() {
    phase.value = "form";
  }

  return { phase, isForm, isRun, enterRun, backToForm };
}
