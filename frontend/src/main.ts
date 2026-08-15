import { createApp } from "vue";
import "element-plus/theme-chalk/dark/css-vars.css";
import "@/styles/tokens.css";
import "@/styles/element-overrides.css";
import App from "./App.vue";
import { router } from "./router";
import { i18n } from "./i18n";
import { useProfile } from "@/composables/useProfile";

function applyFavicon() {
  const styles = getComputedStyle(document.documentElement);
  const dim = (styles.getPropertyValue("--accent-dim") || "#23c9a8").trim() || "#23c9a8";
  const bright = (styles.getPropertyValue("--accent-bright") || "#e4ffd0").trim() || "#e4ffd0";
  const svg = [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">',
    '<defs><linearGradient id="g" x1="5" y1="6" x2="27" y2="25" gradientUnits="userSpaceOnUse">',
    '<stop stop-color="' + bright + '"/><stop offset="1" stop-color="' + dim + '"/>',
    "</linearGradient></defs>",
    '<rect x="1" y="1" width="30" height="30" rx="8" fill="#101c20"/>',
    '<path d="M11.2 10.2h-2.1a4.1 4.1 0 0 0 0 8.2h2.1m9.6-8.2h2.1a4.1 4.1 0 0 1 0 8.2h-2.1M10.7 14.3h10.6" fill="none" stroke="url(#g)" stroke-width="2.65" stroke-linecap="round"/>',
    '<rect x="10.05" y="5.2" width="11.9" height="21.6" rx="3.25" fill="#14262a" stroke="#b9ef5b" stroke-width="1.35"/>',
    '<path d="m13.1 20.4 2.35-6.3h1.1l2.35 6.3m-4.7-2.05h3.6" fill="none" stroke="' + bright + '" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>',
    '<rect x="13.1" y="8.4" width="5.8" height="1.25" rx=".625" fill="' + dim + '"/><circle cx="16" cy="23.7" r=".9" fill="#b9ef5b"/></svg>',
  ].join("");
  let link = document.getElementById("asc-favicon") as HTMLLinkElement | null;
  if (!link) {
    link = document.createElement("link");
    link.id = "asc-favicon";
    link.rel = "icon";
    link.type = "image/svg+xml";
    document.head.appendChild(link);
  }
  link.href = "data:image/svg+xml," + encodeURIComponent(svg);
}

async function boot() {
  document.documentElement.classList.add("dark");
  const root = document.getElementById("app");
  if (!root) return;
  const { refresh, snapshot } = useProfile();
  try {
    await refresh();
  } catch {
    root.textContent = "";
    const p = document.createElement("p");
    p.textContent = String(i18n.global.t("spa.boot_failed"));
    const btn = document.createElement("button");
    btn.textContent = String(i18n.global.t("spa.retry"));
    btn.onclick = () => void boot();
    root.append(p, btn);
    return;
  }
  const lang = snapshot.value?.lang === "zh" ? "zh" : "en";
  i18n.global.locale.value = lang;
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  applyFavicon();
  const app = createApp(App);
  app.use(router);
  app.use(i18n);
  app.mount("#app");
}

void boot();
