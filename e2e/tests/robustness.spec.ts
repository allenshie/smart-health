/**
 * 後端防護（SPEC §6.1、§8.3、§11.4）：用真實後端涵蓋 raw_mock 的 7 個模式，
 * 以及目標停止與恢復、hang 目標不影響其他目標。
 */
import { expect, test, type APIRequestContext } from "@playwright/test";
import { composeContainerId, startContainer, stopContainer } from "./support/mocks";
import {
  GRAY_UNKNOWN,
  detailField,
  expectConnection,
  lampIds,
  lampOf,
  lampSnapshot,
  openTarget,
  screenshotPath,
  targetCard,
  uniform,
  waitForUpdates,
  waitLamps,
} from "./support/ui";

type TargetSummary = { id: string; connection: string; summary_color: string; last_success_at: string | null };

async function summary(request: APIRequestContext, id: string): Promise<TargetSummary> {
  const resp = await request.get("/api/targets");
  expect(resp.status()).toBe(200);
  const found = ((await resp.json()) as TargetSummary[]).find((t) => t.id === id);
  if (found === undefined) throw new Error(`/api/targets 沒有 ${id}`);
  return found;
}

const RAW_NODES = ["ingest", "infer", "publish"];

// 不是 online 的模式：預期連線代碼，以及畫面上保留的架構（從未取得架構時為空）
const NOT_ONLINE: { target: string; mode: string; code: string; nodes: string[] }[] = [
  { target: "raw-hang", mode: "hang", code: "offline", nodes: [] },
  { target: "raw-http-500", mode: "http_500", code: "offline", nodes: [] },
  { target: "raw-invalid-json", mode: "invalid_json", code: "invalid_response", nodes: [] },
  { target: "raw-wrong-schema", mode: "wrong_schema", code: "incompatible", nodes: [] },
  { target: "raw-evaluation-stale", mode: "evaluation_stale", code: "stale", nodes: RAW_NODES },
];

test.describe("raw_mock：不是 online 時全灰", () => {
  for (const { target, mode, code, nodes } of NOT_ONLINE) {
    test(`${mode}：連線 ${code}，全灰`, async ({ page, request }) => {
      await openTarget(page, target);
      await expectConnection(page, code);
      // 畫面：每個燈號都是灰色、狀態「未知」；從未取得架構時顯示提示且沒有燈號
      await waitLamps(page, uniform(nodes, GRAY_UNKNOWN));
      if (nodes.length === 0) {
        await expect(page.getByText("尚未取得此服務的架構")).toBeVisible();
      }
      // 後端：summary_color 為 gray，所有節點 color 為 gray、reason 為連線代碼
      expect(await summary(request, target)).toMatchObject({ connection: code, summary_color: "gray" });
      const detail = await (await request.get(`/api/targets/${target}`)).json();
      for (const node of Object.values(detail.nodes) as { color: string; reason: string }[]) {
        expect(node).toMatchObject({ color: "gray", reason: code });
      }
      expect(Object.keys(detail.nodes).sort()).toEqual([...nodes].sort());
      // 總覽：卡片上的名稱與連線代碼（取代 v1.6 下拉選項文字「Raw ${mode}（${code}）」的檢查）
      await page.goto("/#/");
      const card = targetCard(page, target);
      await expect(card.locator(".card-name")).toHaveText(`Raw ${mode}`);
      await expect(card.locator(".card-connection")).toHaveText(code);
    });
  }
});

test("missing_nodes：online，只有缺少的節點變灰（status_missing）", async ({ page }) => {
  await openTarget(page, "raw-missing-nodes");
  const expected = { ingest: lampOf("ok"), infer: lampOf("ok"), publish: GRAY_UNKNOWN };
  await waitLamps(page, expected);
  await expectConnection(page, "online");
  await page.locator('button.lamp[data-node-id="publish"]').click();
  await expect(detailField(page, "原因")).toHaveText("status_missing");
  await expect(detailField(page, "狀態")).toHaveText("未知");
  await waitForUpdates(page);
  expect(await lampSnapshot(page)).toEqual(expected);
});

test("topology_change：online，畫面上的架構跟著更新", async ({ page }) => {
  const small = ["ingest", "infer", "publish"];
  const large = ["ingest", "infer", "stream", "publish"];
  await openTarget(page, "raw-topology-change");
  // 兩種架構輪流出現：依序看到 small -> large -> small，每次都是 online 且全綠
  for (const ids of [small, large, small]) {
    await expect.poll(() => lampIds(page), { timeout: 30_000 }).toEqual(ids);
    await expectConnection(page, "online");
    await waitLamps(page, uniform(ids, lampOf("ok")));
  }
});

// 平行拉取時 mock-edge-a 約每 poll_interval_s（1 秒）更新一次。若後端退化成循序拉取，
// 每一輪都要等 raw-hang 逾時（request_timeout_s = 3 秒），更新間隔會變成約 3 秒以上。
// 用後端 last_success_at 時間戳計算一段時間內的平均間隔與前進次數，不依賴單次差值。
const POLL_INTERVAL_S = 1; // 與 config/targets.dev.yaml 一致
const SAMPLE_WINDOW_MS = 10_000;
const MAX_MEAN_INTERVAL_S = 1.5 * POLL_INTERVAL_S;
const MIN_ADVANCES = 7;

test("hang 目標不影響其他目標更新", async ({ page, request }) => {
  expect(await summary(request, "raw-hang")).toMatchObject({ connection: "offline" });
  await openTarget(page, "mock-edge-a");
  await expectConnection(page, "online");
  // 畫面：mock-edge-a 的最後更新時間持續前進
  await waitForUpdates(page, 3);

  // 後端：取樣間隔遠小於拉取間隔，收集視窗內所有不同的 last_success_at
  const seen = new Set<string>();
  const started = Date.now();
  await expect
    .poll(
      async () => {
        const at = (await summary(request, "mock-edge-a")).last_success_at;
        if (at !== null) seen.add(at);
        return Date.now() - started >= SAMPLE_WINDOW_MS;
      },
      { intervals: [200], timeout: SAMPLE_WINDOW_MS + 10_000 },
    )
    .toBe(true);
  const times = [...seen].map((at) => Date.parse(at)).sort((a, b) => a - b);
  const advances = times.length - 1;
  const meanIntervalS = (times[times.length - 1] - times[0]) / advances / 1000;
  expect(advances, `視窗內前進次數（平均間隔 ${meanIntervalS.toFixed(2)} 秒）`).toBeGreaterThanOrEqual(MIN_ADVANCES);
  expect(meanIntervalS, "mock-edge-a 的平均更新間隔").toBeLessThanOrEqual(MAX_MEAN_INTERVAL_S);
  // 整段期間 raw-hang 仍掛住
  expect(await summary(request, "raw-hang")).toMatchObject({ connection: "offline", summary_color: "gray" });
});

test.describe("mock-edge-a 停止與恢復", () => {
  const NODES = ["ingest-worker", "ingest", "infer", "stream", "stream-output", "publish"];
  let containerId = "";

  test.beforeAll(async () => {
    containerId = await composeContainerId("mock-edge-a");
  });

  test.afterAll(async () => {
    // 不論測試結果，一律恢復容器
    if (containerId) await startContainer(containerId);
  });

  test("停止後轉灰並顯示橫幅，恢復後回綠", async ({ page }) => {
    await openTarget(page, "mock-edge-a");
    await waitLamps(page, uniform(NODES, lampOf("ok")));
    try {
      await stopContainer(containerId);
      const banner = page.locator('p.banner[role="status"][data-connection="offline"]');
      await expect(banner).toHaveText(/^無法連線到此服務（offline），最後更新 \d{2}:\d{2}:\d{2}$/);
      // 保留上一次的架構，所有燈號轉灰
      await waitLamps(page, uniform(NODES, GRAY_UNKNOWN));
      await page.screenshot({ path: screenshotPath("offline"), fullPage: true });
    } finally {
      await startContainer(containerId);
    }
    await waitLamps(page, uniform(NODES, lampOf("ok")));
    await expectConnection(page, "online");
  });
});
