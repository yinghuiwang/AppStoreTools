import { ref } from "vue";

const pending = ref(false);

export function useAddProfile() {
  function requestOpen() {
    pending.value = true;
  }

  return { pending, requestOpen };
}
