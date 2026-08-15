import { createApp } from "vue";
import "element-plus/theme-chalk/dark/css-vars.css";
import "@/styles/tokens.css";
import "@/styles/element-overrides.css";
import App from "./App.vue";
import { router } from "./router";
import { i18n } from "./i18n";

document.documentElement.classList.add("dark");
createApp(App).use(router).use(i18n).mount("#app");
