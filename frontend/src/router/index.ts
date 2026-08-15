import { createRouter, createWebHistory, type RouteLocation } from "vue-router";
import DashboardView from "@/views/DashboardView.vue";
import ListingView from "@/views/ListingView.vue";
import WhatsNewView from "@/views/WhatsNewView.vue";
import UrlsView from "@/views/UrlsView.vue";
import BuildView from "@/views/BuildView.vue";
import IapView from "@/views/IapView.vue";
import ProfilesView from "@/views/ProfilesView.vue";
import GuardView from "@/views/GuardView.vue";
import SettingsView from "@/views/SettingsView.vue";
import UpdateView from "@/views/UpdateView.vue";

const SYSTEM_PAGES = new Set(["profiles", "guard", "settings", "update"]);

function systemPathFromTab(raw: unknown): string {
  const value = String(Array.isArray(raw) ? raw[0] : raw || "")
    .replace(/^#/, "")
    .replace(/^tab=/i, "")
    .trim()
    .toLowerCase();
  return SYSTEM_PAGES.has(value) ? `/${value}` : "/profiles";
}

function redirectSystemRoot(to: RouteLocation) {
  const { tab, ...query } = to.query;
  return { path: systemPathFromTab(tab ?? to.hash), query };
}

function redirectSystemTab(to: RouteLocation) {
  return { path: systemPathFromTab(to.params.tab), query: to.query };
}

export const router = createRouter({
  history: createWebHistory("/"),
  routes: [
    { path: "/", component: DashboardView },
    { path: "/listing", component: ListingView },
    { path: "/whats-new", component: WhatsNewView },
    { path: "/urls", component: UrlsView },
    { path: "/build", component: BuildView },
    { path: "/iap", component: IapView },
    { path: "/profiles", component: ProfilesView },
    { path: "/guard", component: GuardView },
    { path: "/settings", component: SettingsView },
    { path: "/update", component: UpdateView },
    { path: "/system", redirect: redirectSystemRoot },
    { path: "/system/:tab", redirect: redirectSystemTab },
    { path: "/metadata", redirect: (to) => ({ path: "/listing", query: to.query }) },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
