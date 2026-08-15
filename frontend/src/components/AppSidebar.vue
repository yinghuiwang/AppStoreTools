<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";

type NavItem = {
  to: string;
  labelKey: string;
  match: "exact" | "prefix";
  prefix?: string;
  icon: string;
};

type NavGroup = {
  labelKey: string;
  items: NavItem[];
};

const groups: NavGroup[] = [
  { labelKey: "nav.group.overview", items: [{ to: "/", labelKey: "nav.dashboard", match: "exact", icon: "dash" }] },
  {
    labelKey: "nav.group.listing",
    items: [
      { to: "/listing", labelKey: "nav.listing", match: "exact", icon: "listing" },
      { to: "/whats-new", labelKey: "nav.whats_new", match: "exact", icon: "notes" },
      { to: "/urls", labelKey: "nav.urls", match: "exact", icon: "link" },
    ],
  },
  { labelKey: "nav.group.build", items: [{ to: "/build", labelKey: "nav.build", match: "exact", icon: "build" }] },
  { labelKey: "nav.group.iap", items: [{ to: "/iap", labelKey: "nav.iap", match: "exact", icon: "iap" }] },
  { labelKey: "nav.group.system", items: [{ to: "/system/profiles", labelKey: "nav.system", match: "prefix", prefix: "/system", icon: "system" }] },
];

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const logoSrc = "/static/logo.svg";
const collapsed = ref(false);
const flyoutKey = ref("");
const flyoutTop = ref(0);

function isActive(item: NavItem): boolean {
  if (item.match === "prefix") {
    return route.path.startsWith(item.prefix || item.to);
  }
  return route.path === item.to;
}

function onResize() {
  collapsed.value = window.innerWidth < 1100;
  if (!collapsed.value) flyoutKey.value = "";
}

function onItemClick(event: MouseEvent, group: NavGroup, item: NavItem) {
  if (!collapsed.value) return;
  if (isActive(item)) {
    event.preventDefault();
    const target = event.currentTarget as HTMLElement;
    flyoutTop.value = target.getBoundingClientRect().top;
    flyoutKey.value = flyoutKey.value === group.labelKey ? "" : group.labelKey;
  } else {
    flyoutKey.value = "";
  }
}

function closeFlyout() {
  flyoutKey.value = "";
}

function go(to: string) {
  flyoutKey.value = "";
  void router.push(to);
}

const flyoutGroup = computed(() => groups.find((g) => g.labelKey === flyoutKey.value) || null);

onMounted(() => {
  onResize();
  window.addEventListener("resize", onResize);
  document.addEventListener("click", closeFlyout);
});
onBeforeUnmount(() => {
  window.removeEventListener("resize", onResize);
  document.removeEventListener("click", closeFlyout);
});
</script>

<template>
  <aside class="sidebar" :class="{ collapsed }" @click.stop>
    <router-link to="/" class="brand" @click="closeFlyout">
      <img class="brand-logo" :src="logoSrc" alt="" width="28" height="28" />
      <span class="brand-text">AppStore <i>Tools</i></span>
    </router-link>
    <nav class="nav">
      <section v-for="group in groups" :key="group.labelKey" class="group">
        <p class="group-label">{{ t(group.labelKey) }}</p>
        <router-link
          v-for="item in group.items"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          :class="{ active: isActive(item) }"
          :title="t(item.labelKey)"
          @click="onItemClick($event, group, item)"
        >
          <span class="nav-icon" :data-icon="item.icon" aria-hidden="true" />
          <span class="nav-label">{{ t(item.labelKey) }}</span>
        </router-link>
      </section>
    </nav>
    <div
      v-if="collapsed && flyoutGroup"
      class="flyout"
      :style="{ top: `${flyoutTop}px` }"
    >
      <p class="flyout-label">{{ t(flyoutGroup.labelKey) }}</p>
      <button
        v-for="item in flyoutGroup.items"
        :key="item.to"
        type="button"
        class="flyout-item"
        :class="{ active: isActive(item) }"
        @click="go(item.to)"
      >
        {{ t(item.labelKey) }}
      </button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  position: relative;
  width: var(--sidebar-width);
  flex: 0 0 var(--sidebar-width);
  height: 100vh;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  padding: 16px 10px 20px;
  transition: width 180ms ease, flex-basis 180ms ease;
}

.sidebar::after {
  content: "";
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 1px;
  background: linear-gradient(
    to bottom,
    transparent 0%,
    var(--accent-dim) 15%,
    var(--accent) 50%,
    var(--accent-dim) 85%,
    transparent 100%
  );
}

.sidebar.collapsed {
  width: var(--sidebar-collapsed);
  flex-basis: var(--sidebar-collapsed);
  padding-left: 6px;
  padding-right: 6px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 8px 18px;
  text-decoration: none;
  color: var(--text);
}

.brand:hover {
  text-decoration: none;
}

.brand-logo {
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
}

.brand-text {
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.02em;
  white-space: nowrap;
}

.brand-text i {
  font-style: italic;
  color: #8ff5d2;
  font-weight: 500;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: auto;
}

.group-label {
  margin: 0 8px 6px;
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-faint);
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 36px;
  padding: 6px 10px 6px 12px;
  border-radius: 8px;
  color: var(--text-muted);
  text-decoration: none;
}

.nav-item:hover {
  color: var(--text);
  background: var(--raised);
  text-decoration: none;
}

.nav-item.active {
  color: var(--accent);
  background: var(--accent-glow);
}

.nav-item.active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 2px;
  border-radius: 1px;
  background: var(--accent);
}

.nav-label {
  white-space: nowrap;
  font-size: 13px;
  font-weight: 550;
}

.nav-icon {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  background: currentColor;
  mask-size: contain;
  mask-repeat: no-repeat;
  mask-position: center;
  -webkit-mask-size: contain;
  -webkit-mask-repeat: no-repeat;
  -webkit-mask-position: center;
}

.nav-icon[data-icon="dash"] {
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Crect x='3' y='3' width='7' height='7' rx='1.5'/%3E%3Crect x='14' y='3' width='7' height='7' rx='1.5'/%3E%3Crect x='3' y='14' width='7' height='7' rx='1.5'/%3E%3Crect x='14' y='14' width='7' height='7' rx='1.5'/%3E%3C/svg%3E");
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Crect x='3' y='3' width='7' height='7' rx='1.5'/%3E%3Crect x='14' y='3' width='7' height='7' rx='1.5'/%3E%3Crect x='3' y='14' width='7' height='7' rx='1.5'/%3E%3Crect x='14' y='14' width='7' height='7' rx='1.5'/%3E%3C/svg%3E");
}

.nav-icon[data-icon="listing"] {
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Crect x='4' y='3' width='16' height='18' rx='2'/%3E%3Cpath d='M8 8h8M8 12h8M8 16h5'/%3E%3C/svg%3E");
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Crect x='4' y='3' width='16' height='18' rx='2'/%3E%3Cpath d='M8 8h8M8 12h8M8 16h5'/%3E%3C/svg%3E");
}

.nav-icon[data-icon="notes"] {
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Cpath d='M7 3h7l6 6v12a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z'/%3E%3Cpath d='M14 3v6h6'/%3E%3C/svg%3E");
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Cpath d='M7 3h7l6 6v12a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z'/%3E%3Cpath d='M14 3v6h6'/%3E%3C/svg%3E");
}

.nav-icon[data-icon="link"] {
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Cpath d='M10 13a5 5 0 0 0 7.07 0l1.41-1.41a5 5 0 0 0-7.07-7.07L10 5.93'/%3E%3Cpath d='M14 11a5 5 0 0 0-7.07 0L5.5 12.43a5 5 0 0 0 7.07 7.07L14 18.07'/%3E%3C/svg%3E");
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Cpath d='M10 13a5 5 0 0 0 7.07 0l1.41-1.41a5 5 0 0 0-7.07-7.07L10 5.93'/%3E%3Cpath d='M14 11a5 5 0 0 0-7.07 0L5.5 12.43a5 5 0 0 0 7.07 7.07L14 18.07'/%3E%3C/svg%3E");
}

.nav-icon[data-icon="build"] {
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Cpath d='M12 3v4M8 7h8l2 4H6l2-4z'/%3E%3Crect x='5' y='11' width='14' height='9' rx='1.5'/%3E%3C/svg%3E");
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Cpath d='M12 3v4M8 7h8l2 4H6l2-4z'/%3E%3Crect x='5' y='11' width='14' height='9' rx='1.5'/%3E%3C/svg%3E");
}

.nav-icon[data-icon="iap"] {
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='8'/%3E%3Cpath d='M12 8v8M9.5 10.5c.5-1 1.5-1.5 2.5-1.5s2 .6 2 1.7c0 2.3-4 1.4-4 3.8 0 1 .9 1.5 2 1.5s2-.5 2.5-1.5'/%3E%3C/svg%3E");
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='8'/%3E%3Cpath d='M12 8v8M9.5 10.5c.5-1 1.5-1.5 2.5-1.5s2 .6 2 1.7c0 2.3-4 1.4-4 3.8 0 1 .9 1.5 2 1.5s2-.5 2.5-1.5'/%3E%3C/svg%3E");
}

.nav-icon[data-icon="system"] {
  mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='3'/%3E%3Cpath d='M12 3v2M12 19v2M4.9 6.3l1.5 1.5M17.6 16.2l1.5 1.5M3 12h2M19 12h2M4.9 17.7l1.5-1.5M17.6 7.8l1.5-1.5'/%3E%3C/svg%3E");
  -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='black' stroke-width='1.8' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='3'/%3E%3Cpath d='M12 3v2M12 19v2M4.9 6.3l1.5 1.5M17.6 16.2l1.5 1.5M3 12h2M19 12h2M4.9 17.7l1.5-1.5M17.6 7.8l1.5-1.5'/%3E%3C/svg%3E");
}

.sidebar.collapsed .brand {
  justify-content: center;
  padding: 4px 0 16px;
}

.sidebar.collapsed .brand-text,
.sidebar.collapsed .group-label,
.sidebar.collapsed .nav-label {
  display: none;
}

.sidebar.collapsed .nav-item {
  justify-content: center;
  padding: 8px 0;
}

.sidebar.collapsed .nav-item.active::before {
  top: 6px;
  bottom: 6px;
}

.flyout {
  position: fixed;
  left: 56px;
  z-index: 40;
  min-width: 168px;
  padding: 10px;
  background: var(--overlay);
  border: 1px solid var(--border-strong);
  border-radius: 10px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
}

.flyout-label {
  margin: 0 6px 8px;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-faint);
}

.flyout-item {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 0;
  color: var(--text-muted);
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
}

.flyout-item:hover,
.flyout-item.active {
  color: var(--accent);
  background: var(--accent-glow);
}
</style>
