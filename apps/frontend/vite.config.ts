/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// dev server 只供本機開發；正式環境同源，由後端提供靜態檔。
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/healthz": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // 固定時區，讓 HH:MM:SS 的斷言可預期（UTC+8，無日光節約）。
    env: { TZ: "Asia/Taipei" },
  },
});
