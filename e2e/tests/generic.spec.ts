/**
 * 通用性（SPEC §7.1 要求 1、§8.3、§11.5）：mock-api 是非 Edge 命名、有巢狀 lane 的架構，
 * 前端不修改程式就要正確顯示。
 */
import { expect, test } from "@playwright/test";
import { expectConnection, lampOf, openTarget, screenshotPath, uniform, waitLamps } from "./support/ui";

const NODES = ["gateway", "handler", "response", "job-runner", "cache-warmer", "batch-export"];

test("mock-api 的巢狀 lane 正確顯示", async ({ page }) => {
  await openTarget(page, "mock-api");
  // 閒置的 api 節點沒有 stale_after_s，startup grace 過後為 ok
  await waitLamps(page, uniform(NODES, lampOf("ok")));
  await expectConnection(page, "online");

  // 頂層只有 main；workers 從 handler 分出，batch 再從 job-runner 分出
  const topology = page.locator(".topology");
  await expect(topology.locator(":scope > .lane")).toHaveCount(1);
  const main = topology.locator(':scope > .lane[data-lane-id="main"]');
  const workers = main.locator(':scope > .lane-children > .lane[data-lane-id="workers"]');
  const batch = workers.locator(':scope > .lane-children > .lane[data-lane-id="batch"]');
  await expect(main).toHaveCount(1);
  await expect(workers).toHaveCount(1);
  await expect(batch).toHaveCount(1);

  const ownLamps = (lane: typeof main) =>
    lane
      .locator(":scope > .lane-row > .lane-nodes > button.lamp")
      .evaluateAll((els) => els.map((el) => el.getAttribute("data-node-id")));
  expect(await ownLamps(main)).toEqual(["gateway", "handler", "response"]);
  expect(await ownLamps(workers)).toEqual(["job-runner", "cache-warmer"]);
  expect(await ownLamps(batch)).toEqual(["batch-export"]);

  await expect(main.locator(":scope > .lane-row .lane-name")).toHaveText("Request path");
  await expect(workers.locator(":scope > .lane-row .lane-name")).toHaveText("Background workers");
  await expect(workers.locator(":scope > .lane-row .lane-parent")).toHaveText("從 Handler 分出");
  await expect(batch.locator(":scope > .lane-row .lane-name")).toHaveText("Batch jobs");
  await expect(batch.locator(":scope > .lane-row .lane-parent")).toHaveText("從 Job runner 分出");
  // sequential 的 main 有箭頭，非 sequential 的 workers 沒有
  await expect(main.locator(":scope > .lane-row .lane-arrow")).toHaveCount(2);
  await expect(workers.locator(":scope > .lane-row .lane-arrow")).toHaveCount(0);

  await page.screenshot({ path: screenshotPath("mock-api"), fullPage: true, animations: "disabled" });
});
