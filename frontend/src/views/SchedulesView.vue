<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { MessagePlugin } from "tdesign-vue-next";
import { ApiError, apiErrorMessage, httpJson } from "@/api/http";
import { useProfile } from "@/composables/useProfile";

defineOptions({ name: "SchedulesView" });

const { t } = useI18n();

type ScheduleTask = {
  id: string;
  profile: string;
  enabled: boolean;
  kind: string;
  time: string;
  timezone: string;
  next_run_at: string;
  last_run_at: string;
  last_error: string;
  last_result: string;
  interval_hours?: number;
  weekdays?: number[];
};

type Heartbeat = { installed: boolean; path: string };
type Row = ScheduleTask & { cycle: string; nextText: string };

const weekdayOptions = [1, 2, 3, 4, 5, 6, 7];

function nextLabel(task: ScheduleTask): string {
  const stamp = task.next_run_at;
  return `${stamp.slice(0, 10)} ${stamp.slice(11, 16)} ${task.timezone}`;
}

function truncateTime(value: string): string {
  return value.slice(0, 5);
}

function cycleLabel(task: ScheduleTask): string {
  if (task.kind === "daily") return `daily ${task.time}`;
  if (task.kind === "interval") return `every ${task.interval_hours}h ${task.time}`;
  return `weekly ${(task.weekdays || []).join(",")} ${task.time}`;
}

function decorate(task: ScheduleTask): Row {
  return { ...task, cycle: cycleLabel(task), nextText: nextLabel(task) };
}

const { snapshot } = useProfile();

const rows = ref<Row[]>([]);
const heartbeat = ref<Heartbeat>({ installed: false, path: "" });
const profileNames = computed(() => snapshot.value?.profiles ?? []);
const timezoneNames = ref<string[]>([]);
const dialogOpen = ref(false);
const editingId = ref("");
const notice = ref("");
const runError = ref("");
const runSummary = ref("");
const runningIds = ref<string[]>([]);
const form = reactive({
  profile: "",
  kind: "daily",
  time: "09:30",
  intervalHours: 2,
  weekdays: [1] as number[],
  timezone: "",
  enabled: true,
});

const dialogTitle = computed(() => (editingId.value ? t("schedules.edit") : t("schedules.add")));
const canSave = computed(() => {
  if (!form.profile || !truncateTime(form.time)) return false;
  if (form.kind === "interval" && !(Number(form.intervalHours) >= 1)) return false;
  if (form.kind === "weekly" && form.weekdays.length === 0) return false;
  return true;
});

function report(err: unknown) {
  const message = err instanceof ApiError ? apiErrorMessage(err) : String(err);
  notice.value = message;
  MessagePlugin.error(message);
}

async function load() {
  const data = await httpJson<{ tasks: ScheduleTask[]; heartbeat: Heartbeat }>("/api/schedules");
  rows.value = (data.tasks || []).map(decorate);
  heartbeat.value = data.heartbeat || { installed: false, path: "" };
}

function profileForCreate(): string {
  const current = snapshot.value?.current_profile || "";
  return profileNames.value.includes(current) ? current : "";
}

async function loadTimezones() {
  const data = await httpJson<{ timezones: string[] }>("/api/schedules/timezones");
  timezoneNames.value = data.timezones || [];
}

function resetForm() {
  form.profile = profileForCreate();
  form.kind = "daily";
  form.time = "09:30";
  form.intervalHours = 2;
  form.weekdays = [1];
  form.timezone = "";
  form.enabled = true;
}

function openCreate() {
  editingId.value = "";
  notice.value = "";
  resetForm();
  dialogOpen.value = true;
}

function openEdit(task: ScheduleTask) {
  editingId.value = task.id;
  notice.value = "";
  form.profile = task.profile;
  form.kind = task.kind;
  form.time = task.time;
  form.intervalHours = task.interval_hours || 1;
  form.weekdays = [...(task.weekdays || [])];
  form.timezone = task.timezone;
  form.enabled = task.enabled;
  dialogOpen.value = true;
}

function encode(body: Record<string, unknown>): string {
  return JSON.stringify(body);
}

async function toggle(task: ScheduleTask, enabled: boolean) {
  const body: Record<string, unknown> = {
    profile: task.profile,
    kind: task.kind,
    time: task.time,
    enabled,
  };
  if (task.kind === "interval") body.interval_hours = task.interval_hours;
  if (task.kind === "weekly") body.weekdays = task.weekdays;
  try {
    await httpJson(`/api/schedules/${encodeURIComponent(task.id)}`, { method: "PUT", body: encode(body) });
    await load();
  } catch (err) {
    report(err);
  }
}

async function save() {
  if (!canSave.value) return;
  notice.value = "";
  const body: Record<string, unknown> = {
    profile: form.profile,
    kind: form.kind,
    time: truncateTime(form.time),
  };
  if (form.kind === "interval") body.interval_hours = Number(form.intervalHours);
  if (form.kind === "weekly") {
    body.weekdays = [...form.weekdays].map((day) => Number(day)).sort((left, right) => left - right);
  }
  try {
    if (editingId.value) {
      body.enabled = form.enabled;
      await httpJson(`/api/schedules/${encodeURIComponent(editingId.value)}`, {
        method: "PUT",
        body: encode(body),
      });
    } else {
      if (form.timezone) body.timezone = form.timezone;
      await httpJson("/api/schedules", { method: "POST", body: encode(body) });
    }
    dialogOpen.value = false;
    await load();
  } catch (err) {
    report(err);
  }
}

async function remove(task: ScheduleTask) {
  try {
    await httpJson(`/api/schedules/${encodeURIComponent(task.id)}`, { method: "DELETE" });
    await load();
  } catch (err) {
    report(err);
  }
}

function isRunning(id: string): boolean {
  return runningIds.value.includes(id);
}

async function run(task: ScheduleTask) {
  if (isRunning(task.id)) return;
  runningIds.value = [...runningIds.value, task.id];
  runError.value = "";
  runSummary.value = "";
  try {
    const updated = await httpJson<ScheduleTask>(`/api/schedules/${encodeURIComponent(task.id)}/run`, {
      method: "POST",
    });
    const index = rows.value.findIndex((row) => row.id === updated.id);
    if (index >= 0) rows.value[index] = decorate({ ...rows.value[index], ...updated });
    if (updated.last_error) runError.value = updated.last_error;
    else runSummary.value = updated.last_result;
    await load();
  } catch (err) {
    report(err);
  } finally {
    runningIds.value = runningIds.value.filter((id) => id !== task.id);
  }
}

async function installHeartbeat() {
  try {
    await httpJson("/api/schedules/heartbeat/install", { method: "POST" });
    await load();
  } catch (err) {
    report(err);
  }
}

async function uninstallHeartbeat() {
  try {
    await httpJson("/api/schedules/heartbeat/uninstall", { method: "POST" });
    await load();
  } catch (err) {
    report(err);
  }
}

onMounted(async () => {
  try {
    await Promise.all([load(), loadTimezones()]);
  } catch (err) {
    report(err);
  }
});
</script>

<template>
  <div class="page-stack">
    <section class="card heartbeat">
      <div>
        <strong>{{ heartbeat.installed ? t("schedules.heartbeat_installed") : t("schedules.heartbeat_absent") }}</strong>
        <code v-if="heartbeat.path">{{ heartbeat.path }}</code>
      </div>
      <div class="actions">
        <t-button theme="primary" @click="installHeartbeat">{{ t("schedules.install") }}</t-button>
        <t-button variant="outline" @click="uninstallHeartbeat">{{ t("schedules.uninstall") }}</t-button>
      </div>
    </section>

    <section class="card">
      <header class="section-head">
        <h2>{{ t("nav.schedules") }}</h2>
        <t-button theme="primary" @click="openCreate">{{ t("schedules.add") }}</t-button>
      </header>
      <p v-if="runSummary" class="row-ok">{{ runSummary }}</p>
      <p v-if="runError" class="row-error">{{ runError }}</p>
      <p v-if="!rows.length" class="empty">{{ t("schedules.empty") }}</p>
      <table v-else class="schedule-table">
        <thead>
          <tr>
            <th>{{ t("schedules.col_id") }}</th>
            <th>{{ t("schedules.col_app") }}</th>
            <th>{{ t("schedules.col_cycle") }}</th>
            <th>{{ t("schedules.col_next") }}</th>
            <th>{{ t("schedules.col_last") }}</th>
            <th>{{ t("schedules.col_enabled") }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id">
            <td class="mono">{{ row.id }}</td>
            <td>{{ row.profile }}</td>
            <td class="mono">{{ row.cycle }}</td>
            <td class="mono">{{ row.nextText }}</td>
            <td>{{ row.last_result || "-" }}</td>
            <td>
              <t-switch :value="row.enabled" @change="toggle(row, $event === true)" />
              <span>{{ row.enabled ? t("schedules.state_enabled") : t("schedules.state_disabled") }}</span>
              <p v-if="row.last_error" class="row-error">{{ row.last_error }}</p>
            </td>
            <td class="actions">
              <t-button size="small" variant="text" @click="openEdit(row)">{{ t("schedules.edit") }}</t-button>
              <t-button
                size="small"
                variant="text"
                :loading="isRunning(row.id)"
                :disabled="isRunning(row.id)"
                @click="run(row)"
              >{{ t("schedules.run") }}</t-button>
              <t-popconfirm :content="t('schedules.confirm_delete')" @confirm="remove(row)">
                <t-button size="small" theme="danger" variant="text">{{ t("schedules.delete") }}</t-button>
              </t-popconfirm>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <t-dialog v-model:visible="dialogOpen" :header="dialogTitle" :footer="false" width="480px" placement="center">
      <div class="dialog-form">
        <label class="field">
          <span>{{ t("schedules.profile") }}</span>
          <t-select v-model="form.profile" :placeholder="t('nav.select_app')">
            <t-option v-for="name in profileNames" :key="name" :value="name" :label="name" />
          </t-select>
        </label>
        <label class="field">
          <span>{{ t("schedules.col_cycle") }}</span>
          <t-radio-group v-model="form.kind">
            <t-radio value="daily">{{ t("schedules.kind_daily") }}</t-radio>
            <t-radio value="interval">{{ t("schedules.kind_interval") }}</t-radio>
            <t-radio value="weekly">{{ t("schedules.kind_weekly") }}</t-radio>
          </t-radio-group>
        </label>
        <label v-if="form.kind === 'interval'" class="field">
          <span>{{ t("schedules.every") }}</span>
          <input v-model.number="form.intervalHours" type="number" min="1" step="1" />
        </label>
        <label v-if="form.kind === 'weekly'" class="field">
          <span>{{ t("schedules.weekdays") }}</span>
          <t-select v-model="form.weekdays" multiple>
            <t-option v-for="day in weekdayOptions" :key="day" :value="day" :label="String(day)" />
          </t-select>
        </label>
        <label class="field">
          <span>{{ t("schedules.time") }}</span>
          <input v-model="form.time" type="time" step="1" />
        </label>
        <label class="field">
          <span>{{ t("schedules.timezone") }}</span>
          <t-select
            v-if="!editingId"
            v-model="form.timezone"
            filterable
            :placeholder="t('schedules.timezone_auto')"
            :popup-props="{ attach: 'body' }"
          >
            <t-option :value="''" :label="t('schedules.timezone_auto')" />
            <t-option v-for="zone in timezoneNames" :key="zone" :value="zone" :label="zone" />
          </t-select>
          <input v-else :value="form.timezone" type="text" readonly />
        </label>
        <p v-if="notice" class="row-error">{{ notice }}</p>
        <div class="actions">
          <t-button variant="outline" @click="dialogOpen = false">{{ t("schedules.cancel") }}</t-button>
          <t-button theme="primary" :disabled="!canSave" @click="save">{{ t("schedules.save") }}</t-button>
        </div>
      </div>
    </t-dialog>
  </div>
</template>

<style scoped>
.heartbeat,
.section-head,
.actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-head h2 {
  margin: 0;
  font-size: 16px;
}

.heartbeat code,
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.schedule-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 12px;
}

.schedule-table th,
.schedule-table td {
  text-align: left;
  padding: 8px 6px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}

.empty {
  color: var(--text-muted);
}

.row-error {
  color: var(--danger, #c4352d);
  margin: 6px 0 0;
}

.row-ok {
  color: var(--ok);
  margin: 6px 0 0;
}

.field input {
  width: 100%;
  box-sizing: border-box;
}
</style>
