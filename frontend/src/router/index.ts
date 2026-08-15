import { createRouter, createWebHistory } from "vue-router";
import DashboardView from "@/views/DashboardView.vue";
import ListingView from "@/views/ListingView.vue";
import WhatsNewView from "@/views/WhatsNewView.vue";
import UrlsView from "@/views/UrlsView.vue";
import BuildView from "@/views/BuildView.vue";
import IapView from "@/views/IapView.vue";
import SystemView from "@/views/SystemView.vue";

const SYSTEM_TABS = new Set(["profiles", "guard", "settings", "update"]);

export const router = createRouter({
  history: createWebHistory("/"),
  routes: [
    { path: "/", component: DashboardView },
    { path: "/listing", component: ListingView },
    { path: "/whats-new", component: WhatsNewView },
    { path: "/urls", component: UrlsView },
    { path: "/build", component: BuildView },
    { path: "/iap", component: IapView },
    { path: "/system", redirect: "/system/profiles" },
    {
      path: "/system/:tab",
      component: SystemView,
      beforeEnter: (to) => {
        if (!SYSTEM_TABS.has(String(to.params.tab))) return "/system/profiles";
      },
    },
    { path: "/metadata", redirect: (to) => ({ path: "/listing", query: to.query }) },
    { path: "/profiles", redirect: "/system/profiles" },
    { path: "/guard", redirect: "/system/guard" },
    { path: "/settings", redirect: "/system/settings" },
    { path: "/update", redirect: "/system/update" },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
