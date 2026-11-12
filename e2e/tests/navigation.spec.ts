/**
 * 兩層畫面（SPEC §7.1）：總覽 → 卡片 → 服務 → 回到總覽，以及直接開啟服務網址。
 * 目標與名稱來自 config/targets.dev.yaml。
 */
import { expect, test, type Page } from "@playwright/test";
import { expectConnection, lampOf, openTarget, screenshotPath, targetCard, uniform, waitLamps } from "./support/ui";

const API_NODES = ["gateway", "handler", "response", "job-runner", "cache-warmer", "batch-export"];
const EDGE_NODES = ["ingest-worker", "ingest", "infer", "stream", "stream-output", "publish"];
// config/targets.dev.yaml 的順序
const TARGET_IDS = [
  "mock-edge-a",
  "mock-edge-b",
  "mock-api",
  "raw-hang",
  "raw-http-500",
  "raw-invalid-json",
  "raw-wrong-schema",
  "raw-missing-nodes",
  "raw-topology-change",
  "raw-evaluation-stale",
];

const overviewTitle = (page: Page) => page.getByRole("heading", { name: "服務總覽" });
const backLink = (page: Page) => page.getByRole("link", { name: "← 回到總覽" });

async function expectOverview(page: Page): Promise<void> {
  await expect(overviewTitle(page)).toBeVisible();
  await expect(page.locator("a.target-card")).toHaveCount(TARGET_IDS.length);
}

test("總覽 → 卡片 → 服務 → 回到總覽", async ({ page }) => {
  await page.goto("/");
  await expectOverview(page);
  // 卡片依設定順序；統計列 4 類；10 個目標不分頁
  const ids = await page.locator("a.target-card").evaluateAll((els) => els.map((el) => el.getAttribute("data-target-id")));
  expect(ids).toEqual(TARGET_IDS);
  await expect(page.getByRole("list", { name: "統計" }).locator("li")).toHaveCount(4);
  await expect(page.getByRole("navigation", { name: "分頁" })).toHaveCount(0);
  // 總覽只有卡片，沒有節點燈號
  await expect(page.locator("button.lamp")).toHaveCount(0);

  const card = targetCard(page, "mock-api");
  await expect(card.locator(".card-name")).toHaveText("Mock API");
  await expect(card.locator(".card-state")).toHaveText("正常");
  await expect(card).toHaveAttribute("data-color", "green");
  await expect(targetCard(page, "raw-hang").locator(".card-state")).toHaveText("無法連線");
  await page.screenshot({ path: screenshotPath("overview"), fullPage: true });

  await card.click();
  await expect(page).toHaveURL(/#\/targets\/mock-api$/);
  await expect(page.getByRole("heading", { name: "Mock API" })).toBeVisible();
  await waitLamps(page, uniform(API_NODES, lampOf("ok")));
  await expectConnection(page, "online");
  await expect(page.locator(".target-header .summary-lamp")).toHaveText("正常");

  await backLink(page).click();
  await expect(page).toHaveURL(/#\/$/);
  await expectOverview(page);

  // 瀏覽器的上一頁、下一頁
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Mock API" })).toBeVisible();
  await page.goBack();
  await expectOverview(page);
  await page.goForward();
  await expect(page.getByRole("heading", { name: "Mock API" })).toBeVisible();
  await waitLamps(page, uniform(API_NODES, lampOf("ok")));
});

test("直接開啟服務網址", async ({ page }) => {
  await openTarget(page, "mock-edge-b");
  await expect(page.getByRole("heading", { name: "Mock Edge B" })).toBeVisible();
  await waitLamps(page, uniform(EDGE_NODES, lampOf("ok")));
  await expectConnection(page, "online");

  // 重新整理後停在同一個服務畫面
  await page.reload();
  await expect(page.getByRole("heading", { name: "Mock Edge B" })).toBeVisible();
  await waitLamps(page, uniform(EDGE_NODES, lampOf("ok")));

  // 直接開啟時回到總覽第 1 頁
  await expect(backLink(page)).toHaveAttribute("href", "#/");
  await backLink(page).click();
  await expectOverview(page);
});

test("找不到服務：顯示訊息與回到總覽", async ({ page }) => {
  await page.goto("/#/targets/no-such-target");
  await expect(page.locator(".not-found")).toHaveText("找不到服務 no-such-target");
  await expect(page.locator("button.lamp")).toHaveCount(0);
  await backLink(page).click();
  await expectOverview(page);
});
