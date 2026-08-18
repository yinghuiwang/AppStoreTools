/// <reference types="vite/client" />
/// <reference types="@tdesign-vue-next/chat/global" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<object, object, unknown>;
  export default component;
}

declare module "@locales/*.json" {
  const messages: Record<string, string>;
  export default messages;
}
