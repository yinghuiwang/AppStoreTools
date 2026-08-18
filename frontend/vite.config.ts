import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import AutoImport from "unplugin-auto-import/vite";
import Components from "unplugin-vue-components/vite";
import { TDesignResolver } from "@tdesign-vue-next/auto-import-resolver";

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/spa/" : "/",
  plugins: [
    vue(),
    AutoImport({
      resolvers: [
        TDesignResolver({ library: "vue-next" }),
        TDesignResolver({ library: "chat" }),
      ],
      dts: "src/auto-imports.d.ts",
    }),
    Components({
      resolvers: [
        TDesignResolver({ library: "vue-next" }),
        TDesignResolver({ library: "chat" }),
      ],
      dts: "src/components.d.ts",
    }),
  ],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@locales": fileURLToPath(new URL("../src/asc/web/locales", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    fs: { allow: [".."] },
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: false },
      "/static": { target: "http://127.0.0.1:8080", changeOrigin: false },
    },
  },
  build: {
    outDir: "../src/asc/web/static/spa",
    emptyOutDir: true,
  },
}));
