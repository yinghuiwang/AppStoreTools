import { createApp } from "vue";
import "tdesign-vue-next/es/style/index.css";
import "@/styles/tokens.css";
import "@/styles/tdesign-overrides.css";
import App from "./App.vue";
import { router } from "./router";
import { i18n } from "./i18n";
import { useProfile } from "@/composables/useProfile";

let spaMounted = false;

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

function clearBootChrome(root: HTMLElement) {
  root.classList.remove("spa-boot");
}

function renderBootLoading(root: HTMLElement) {
  if (spaMounted) return;
  root.textContent = "";
  root.className = "spa-boot";
  const wrap = document.createElement("div");
  wrap.className = "spa-boot__row";
  wrap.setAttribute("role", "status");
  wrap.setAttribute("aria-busy", "true");
  const icon = document.createElement("span");
  icon.className = "spa-boot__spinner";
  icon.setAttribute("aria-hidden", "true");
  const label = document.createElement("span");
  label.textContent = String(i18n.global.t("spa.booting"));
  wrap.append(icon, label);
  root.append(wrap);
}

function renderBootFailed(root: HTMLElement, retry: () => void) {
  if (spaMounted) return;
  root.textContent = "";
  root.className = "spa-boot";
  const p = document.createElement("p");
  p.className = "spa-boot__msg";
  p.textContent = String(i18n.global.t("spa.boot_failed"));
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "spa-boot__retry";
  btn.textContent = String(i18n.global.t("spa.retry"));
  btn.onclick = () => void retry();
  root.append(p, btn);
}

async function boot() {
  document.documentElement.classList.add("dark");
  document.documentElement.setAttribute("theme-mode", "dark");
  const root = document.getElementById("app");
  if (!root) return;
  if (!spaMounted) renderBootLoading(root);
  const { refresh, snapshot } = useProfile();
  try {
    await refresh();
  } catch {
    renderBootFailed(root, boot);
    return;
  }
  if (spaMounted) {
    clearBootChrome(root);
    return;
  }
  const lang = snapshot.value?.lang === "zh" ? "zh" : "en";
  i18n.global.locale.value = lang;
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  applyFavicon();
  // Drop boot chrome before mount — Vue keeps #app attributes; spa-boot's
  // flex centering would otherwise shrink .shell to content width.
  clearBootChrome(root);
  root.replaceChildren();
  const app = createApp(App);
  app.use(router);
  app.use(i18n);
  app.mount(root);
  spaMounted = true;
  clearBootChrome(root);
}

void boot();
