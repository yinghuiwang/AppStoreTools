<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

type CheckboxGroupValue = Array<string | number | boolean>;
type CheckboxGroupChangeContext = {
  current?: string | number | boolean;
  type?: "check" | "uncheck";
};

const props = withDefaults(
  defineProps<{
    locales: string[];
    selected: string[];
    modelValue?: string;
    selectable?: boolean;
    showSelectAll?: boolean;
    showToolbar?: boolean;
    hint?: string;
  }>(),
  {
    modelValue: "",
    selectable: true,
    showSelectAll: true,
    showToolbar: true,
    hint: "",
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
  "update:selected": [value: string[]];
}>();

const { t } = useI18n();

const active = computed({
  get() {
    if (props.modelValue && props.locales.includes(props.modelValue)) return props.modelValue;
    return props.locales[0] || "";
  },
  set(value: string) {
    emit("update:modelValue", value);
  },
});

const groupValue = computed<CheckboxGroupValue>(() =>
  props.selectable ? props.selected : props.locales,
);

const localeOptions = computed(() =>
  props.locales.map((code) => ({
    label: code,
    value: code,
    title: props.selectable ? t("locales.include_upload") : code,
  })),
);

const resolvedHint = computed(() => {
  if (props.hint) return props.hint;
  if (props.selectable && props.locales.length) return t("urls.locales_hint");
  return "";
});

function included(code: string) {
  return props.selected.includes(code);
}

function toggle(code: string, on: boolean) {
  const next = on
    ? Array.from(new Set([...props.selected, code]))
    : props.selected.filter((item) => item !== code);
  emit("update:selected", next);
}

function selectAll() {
  emit("update:selected", [...props.locales]);
}

function deselectAll() {
  emit("update:selected", []);
}

function toLocaleList(value: CheckboxGroupValue) {
  return value.map((item) => String(item)).filter((code) => props.locales.includes(code));
}

function onGroupChange(value: CheckboxGroupValue, context: CheckboxGroupChangeContext) {
  if (!props.selectable) return;
  emit("update:selected", toLocaleList(value));
  const code = context.current == null ? "" : String(context.current);
  if (context.type === "check" && code && props.locales.includes(code)) {
    active.value = code;
  }
}

function onShowClick(code: string) {
  active.value = code;
}
</script>

<template>
  <div class="locale-select">
    <div v-if="showToolbar" class="toolbar">
      <span class="lbl">{{ t("urls.locales") }}</span>
      <span v-if="selectable && locales.length" class="muted">
        {{ t("urls.locales_selected", { selected: selected.length, total: locales.length }) }}
      </span>
      <div v-if="selectable && showSelectAll && locales.length" class="field-row">
        <t-button size="small" @click="selectAll">{{ t("urls.select_all") }}</t-button>
        <t-button size="small" @click="deselectAll">{{ t("urls.deselect_all") }}</t-button>
      </div>
    </div>
    <p v-if="resolvedHint" class="muted">{{ resolvedHint }}</p>
    <p v-if="!locales.length" class="muted">{{ t("urls.locales_load_hint") }}</p>
    <t-checkbox-group
      v-else
      class="locale-group"
      :value="groupValue"
      :readonly="!selectable"
      @change="onGroupChange"
    >
      <t-checkbox v-if="selectable && showSelectAll" check-all>
        {{ t("urls.select_all") }}
      </t-checkbox>
      <t-checkbox
        v-for="opt in localeOptions"
        :key="String(opt.value)"
        :value="opt.value"
        :title="opt.title"
        :class="{ 'is-current': active === opt.value }"
      >
        <span class="locale-code" @click.stop.prevent="onShowClick(String(opt.value))">{{ opt.label }}</span>
      </t-checkbox>
    </t-checkbox-group>
    <div v-if="locales.length && active" class="panel">
      <slot :locale="active" :included="included(active)" :toggle="toggle" />
    </div>
  </div>
</template>

<style scoped>
.locale-select {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.lbl {
  font-size: 12px;
  color: var(--text-muted);
}
.muted { color: var(--text-muted); font-size: 13px; }
.field-row { display: flex; gap: 8px; align-items: center; }
.locale-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  width: 100%;
  gap: 8px 16px;
}
.locale-group :deep(.t-checkbox) {
  margin: 0;
  padding: 4px 8px 4px 4px;
  border-radius: 8px;
}
.locale-code {
  color: inherit;
  cursor: pointer;
}
.panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 8px;
}
</style>
