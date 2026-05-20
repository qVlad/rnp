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
    // MV3 CSP запрещает динамически инжектированные <link rel="modulepreload">.
    // Vite/preload-helper делает `document.head.appendChild(link)` с путём
    // вида "/chunk.js" → CSP блокирует и в консоли валится спам ошибок
    // "Refused to load... violates the following Content Security Policy".
    // Полностью отключаем preload — для расширения он бесполезен (всё
    // локально, грузится за ~0мс).
    modulePreload: false,
    rollupOptions: {
      // Заодно подсчитываем размеры для контроля бандла.
      // MV3 ограничения: один файл .crx ≤ 100 MB, отдельные ассеты ≤ 25 MB.
      output: {
        // Не плодим transitive `<link rel="modulepreload">` hint'ы в HTML
        // (popup/options) — те же CSP-ошибки на загрузке UI.
        hoistTransitiveImports: false,
      },
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
