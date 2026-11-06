import { defineConfig, devices } from "@playwright/test";

/**
 * 端對端測試設定：在 dev compose 網路內對真實後端（health-app）執行。
 * 測試會切換共用的 mock 狀態，所以只用 1 個 worker、不平行，也不重試。
 * 等待一律用 Playwright 的自動等待或 expect.poll，不用固定 sleep。
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.E2E_BASE_URL ?? "http://health-app:8000",
    locale: "zh-TW",
    timezoneId: "Asia/Taipei",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
