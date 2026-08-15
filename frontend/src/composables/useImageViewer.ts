import { ref } from "vue";

type Item = { src: string; title: string };
type Transform = { scale: number; x: number; y: number; rotate: number; flipX: boolean; flipY: boolean };

const open = ref(false);
const items = ref<Item[]>([]);
const index = ref(0);
const transform = ref<Transform>({ scale: 1, x: 0, y: 0, rotate: 0, flipX: false, flipY: false });

function resetTransform() {
  transform.value = { scale: 1, x: 0, y: 0, rotate: 0, flipX: false, flipY: false };
}

export function useImageViewer() {
  function show(nextItems: Item[], start = 0) {
    const usable = nextItems.filter((it) => it.src);
    if (!usable.length) return;
    items.value = usable;
    index.value = Math.min(Math.max(0, start), usable.length - 1);
    resetTransform();
    open.value = true;
  }
  function close() { open.value = false; }
  function next() {
    if (index.value < items.value.length - 1) { index.value += 1; resetTransform(); }
  }
  function prev() {
    if (index.value > 0) { index.value -= 1; resetTransform(); }
  }
  return { open, items, index, transform, show, close, next, prev, resetTransform };
}
