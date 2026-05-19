import { defineConfig } from "vite";
import { crx } from "@crxjs/vite-plugin";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import manifest from "./manifest.config";

export default defineConfig({
  plugins: [react(), crx({ manifest })],
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
    rollupOptions: {
      // Заодно подсчитываем размеры для контроля бандла.
      // MV3 ограничения: один файл .crx ≤ 100 MB, отдельные ассеты ≤ 25 MB.
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    hmr: {
      port: 5173,
    },
  },
});
