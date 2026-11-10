/**
 * SPEC §8.2 情境表：以 mock-edge-b 的控制接口切換每個情境，
 * 驗證畫面上每個節點的狀態文字與顏色。mock-edge-a 留給停止與恢復的測試。
 */
import { expect, test } from "@playwright/test";
import { setScenario } from "./support/mocks";
import {
  detailField,
  expectConnection,
  expectLampsHold,
  lampOf,
  openTarget,
  screenshotPath,
  uniform,
  waitLamps,
  type LampSnapshot,
} from "./support/ui";

const TARGET = "mock-edge-b";
const NODES = ["ingest-worker", "ingest", "infer", "stream", "stream-output", "publish"] as const;
const CODE: Record<string, string> = { G: "ok", Y: "degraded", R: "unavailable", 灰: "waiting", D: "disabled" };

// SPEC §8.2 情境表逐字轉成資料（順序同 NODES；D = disabled）
const TABLE: [string, string][] = [
  ["normal", "G G G G G G"],
  ["starting", "灰 灰 灰 灰 灰 灰"],
  ["camera_down", "R 灰 灰 灰 灰 灰"],
  ["messaging_down", "G G G G G R"],
  ["stream_sink_down", "G G G G R G"],
  ["infer_stuck", "G 灰 R 灰 灰 灰"],
  ["infer_exception", "G G R 灰 灰 灰"],
  ["camera_and_messaging_down", "R 灰 灰 灰 灰 R"],
  ["read_errors", "Y G G G G G"],
  ["publish_errors", "G G G G G Y"],
  ["worker_fatal", "R 灰 灰 灰 灰 灰"],
  ["stream_disabled", "G G G D D G"],
  ["loading", "灰 灰 灰 灰 灰 灰"],
  ["loading_fatal", "R 灰 灰 灰 灰 灰"],
];

function expectedLamps(row: string): LampSnapshot {
  const codes = row.split(" ");
  return Object.fromEntries(NODES.map((id, i) => [id, lampOf(CODE[codes[i]])]));
}

const ALL_OK = uniform(NODES, lampOf("ok"));
// mock-edge-b 的 /status（compose 網路內）：用來確認後端不轉傳的 ready_at
const TARGET_STATUS_URL = "http://mock-edge-b:18081/status";

test.describe("SPEC §8.2 情境（mock-edge-b）", () => {
  test.beforeEach(async ({ page, request }) => {
    await setScenario(request, TARGET, "normal");
    await openTarget(page, TARGET);
    await waitLamps(page, ALL_OK);
    await expectConnection(page, "online");
  });

  test.afterEach(async ({ request }) => {
    await setScenario(request, TARGET, "normal");
  });

  test("情境表共 14 列", () => {
    expect(TABLE).toHaveLength(14);
  });

  for (const [name, row] of TABLE) {
    test(`${name}：${row}`, async ({ page, request }) => {
      const expected = expectedLamps(row);
      await setScenario(request, TARGET, name);
      // starting 會重建 monitor 與 server：等過短暫的 offline 與 status_missing，直到全部 waiting
      await waitLamps(page, expected);
      await expectConnection(page, "online");
      await expectLampsHold(page, expected);

      if (name === "normal") {
        await page.screenshot({ path: screenshotPath("normal"), fullPage: true });
      }
      if (name === "starting") {
        await page.locator('button.lamp[data-node-id="ingest"]').click();
        await expect(detailField(page, "原因")).toHaveText("starting");
      }
      if (name === "loading" || name === "loading_fatal") {
        // wait_for_ready=True 且尚未 mark_ready()：灰色節點為 starting，說明是就緒前的固定文字
        await page.locator('button.lamp[data-node-id="ingest"]').click();
        await expect(detailField(page, "原因")).toHaveText("starting");
        await expect(detailField(page, "說明")).toHaveText("服務啟動中，尚未就緒");
        const status = await (await request.get(TARGET_STATUS_URL)).json();
        expect(status.ready_at).toBeNull();
      }
      if (name === "loading_fatal") {
        await page.locator('button.lamp[data-node-id="ingest-worker"]').click();
        await expect(detailField(page, "狀態")).toHaveText("unavailable");
        await expect(detailField(page, "原因")).toHaveText("worker_crashed");
      }
      if (name === "camera_down") {
        await page.locator('button.lamp[data-node-id="ingest-worker"]').click();
        await expect(page.locator('button.lamp[data-node-id="ingest-worker"]')).toHaveAttribute("aria-pressed", "true");
        await expect(detailField(page, "狀態")).toHaveText("unavailable");
        await expect(detailField(page, "原因")).toHaveText("no_new_frame");
        await expect(detailField(page, "說明")).toHaveText(/^已 \d+ 秒沒有成功紀錄$/);
        await page.screenshot({ path: screenshotPath("camera_down"), fullPage: true });
      }
    });
  }
});
