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
    { path: "/", name: "DashboardView", component: DashboardView },
    { path: "/listing", name: "ListingView", component: ListingView, meta: { keepAlive: true } },
    { path: "/whats-new", name: "WhatsNewView", component: WhatsNewView, meta: { keepAlive: true } },
    { path: "/urls", name: "UrlsView", component: UrlsView, meta: { keepAlive: true } },
    { path: "/build", name: "BuildView", component: BuildView, meta: { keepAlive: true } },
    { path: "/iap", name: "IapView", component: IapView, meta: { keepAlive: true } },
    { path: "/profiles", name: "ProfilesView", component: ProfilesView },
    { path: "/guard", name: "GuardView", component: GuardView },
    { path: "/settings", name: "SettingsView", component: SettingsView },
    { path: "/update", name: "UpdateView", component: UpdateView },
    { path: "/system", redirect: redirectSystemRoot },
    { path: "/system/:tab", redirect: redirectSystemTab },
    { path: "/metadata", redirect: (to) => ({ path: "/listing", query: to.query }) },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
