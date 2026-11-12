/** 手機寬度（SPEC §7.1 要求 7）：寬度 360px 時總覽與服務畫面都不能水平捲動。 */
import { expect, test } from "@playwright/test";
import { lampOf, openTarget, screenshotPath, uniform, waitLamps } from "./support/ui";

const EDGE_NODES = ["ingest-worker", "ingest", "infer", "stream", "stream-output", "publish"];
const API_NODES = ["gateway", "handler", "response", "job-runner", "cache-warmer", "batch-export"];

test.use({ viewport: { width: 360, height: 740 } });

for (const [target, nodes] of [
  ["mock-edge-b", EDGE_NODES],
  ["mock-api", API_NODES],
] as const) {
  test(`${target}：寬度 360px 不水平捲動`, async ({ page }) => {
    await openTarget(page, target);
    await waitLamps(page, uniform(nodes, lampOf("ok")));
    const scrollWidth = () => page.evaluate(() => document.documentElement.scrollWidth);
    expect(await scrollWidth()).toBeLessThanOrEqual(360);
    if (target === "mock-edge-b") {
      await page.screenshot({ path: screenshotPath("mobile"), fullPage: true, animations: "disabled" });
    }
    // 開啟詳細面板後也不能水平捲動
    await page.locator(`button.lamp[data-node-id="${nodes[0]}"]`).click();
    await expect(page.locator("section.node-detail")).toBeVisible();
    expect(await scrollWidth()).toBeLessThanOrEqual(360);
  });
}

test("總覽：寬度 360px 不水平捲動", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "服務總覽" })).toBeVisible();
  await expect(page.locator("a.target-card").first()).toBeVisible();
  const scrollWidth = () => page.evaluate(() => document.documentElement.scrollWidth);
  expect(await scrollWidth()).toBeLessThanOrEqual(360);
  await page.screenshot({ path: screenshotPath("mobile_overview"), fullPage: true, animations: "disabled" });
});
