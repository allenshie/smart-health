/**
 * 視覺（SPEC §7.1「視覺」，v1.8）：發光燈號、總覽卡片淡色底、回到總覽圖示、主迴圈的光點流動。
 * 外觀以 getComputedStyle 確認；流動的燈號 box-shadow 一直在變，光暈改在沒有動畫的總覽卡片上檢查。
 * mock-edge-b 切換情境後一律恢復 normal；mock-edge-a 只讀不改。
 */
import { expect, test, type Locator, type Page } from "@playwright/test";
import { setScenario } from "./support/mocks";
import { lampOf, openTarget, targetCard, uniform, waitLamps } from "./support/ui";

const EDGE_NODES = ["ingest-worker", "ingest", "infer", "stream", "stream-output", "publish"];
const API_NODES = ["gateway", "handler", "response", "job-runner", "cache-warmer", "batch-export"];
const MAIN = '[data-lane-id="main"]';
// lane 自己的燈號、圓點與箭頭光點（不含子 lane）
const OWN_LAMPS = `${MAIN} > .lane-row > .lane-nodes > .lamp`;
const OWN_DOTS = `${OWN_LAMPS} > .lamp-dot`;
const OWN_LIGHTS = `${MAIN} > .lane-row > .lane-nodes > .lane-arrow > .lane-flow-dot`;

function style(loc: Locator, prop: string, pseudo?: string): Promise<string> {
  return loc.evaluate((el, [p, ps]) => getComputedStyle(el, ps ?? null).getPropertyValue(p as string), [prop, pseudo] as const);
}

function styles(page: Page, selector: string, prop: string): Promise<string[]> {
  return page.locator(selector).evaluateAll((els, p) => els.map((el) => getComputedStyle(el).getPropertyValue(p)), prop);
}

async function openEdgeB(page: Page): Promise<void> {
  await openTarget(page, "mock-edge-b");
  await waitLamps(page, uniform(EDGE_NODES, lampOf("ok")));
}

test.describe("發光燈號與卡片底色", () => {
  test.afterEach(async ({ request }) => {
    await setScenario(request, "mock-edge-b", "normal");
  });

  test("總覽卡片：綠燈有光暈、灰燈只有內陰影，尺寸 14px", async ({ page }) => {
    await page.goto("/");
    const green = targetCard(page, "mock-edge-a");
    const gray = targetCard(page, "raw-hang");
    await expect(green).toHaveAttribute("data-color", "green");
    await expect(gray).toHaveAttribute("data-color", "gray");

    const greenDot = green.locator(".lamp-dot");
    const grayDot = gray.locator(".lamp-dot");
    expect(await style(greenDot, "box-shadow")).toBe("rgba(52, 199, 89, 0.42) 0px 0px 5px 1px");
    expect(await style(grayDot, "box-shadow")).toBe("rgba(0, 0, 0, 0.22) 0px 1px 2px 0px inset");
    expect(await style(greenDot, "background-image")).toContain("radial-gradient");
    expect(await style(grayDot, "background-image")).toContain("radial-gradient");
    for (const dot of [greenDot, grayDot]) {
      expect(await style(dot, "width")).toBe("14px");
      expect(await style(dot, "border-top-color")).toBe("rgba(0, 0, 0, 0.18)");
      expect(await style(dot, "border-top-width")).toBe("1px");
    }
  });

  test("總覽卡片：四種 summary_color 的淡色底，沒有左側色邊", async ({ page, request }) => {
    await page.goto("/");
    const cases: [string, string, string, string][] = [];
    const record = async (id: string, color: string) => {
      const card = targetCard(page, id);
      await expect(card).toHaveAttribute("data-color", color);
      cases.push([color, await style(card, "background-color"), await style(card, "border-top-color"), await style(card, "border-left-width")]);
      expect(await style(card, "border-left-color")).toBe(await style(card, "border-top-color"));
    };
    await record("mock-edge-a", "green");
    await record("raw-hang", "gray");
    await setScenario(request, "mock-edge-b", "read_errors");
    await record("mock-edge-b", "yellow");
    await setScenario(request, "mock-edge-b", "camera_down");
    await record("mock-edge-b", "red");

    expect(cases).toEqual([
      ["green", "rgb(255, 255, 255)", "rgb(201, 208, 217)", "1px"],
      ["gray", "rgb(248, 249, 250)", "rgb(225, 228, 232)", "1px"],
      ["yellow", "rgb(255, 252, 242)", "rgb(241, 226, 184)", "1px"],
      ["red", "rgb(254, 247, 246)", "rgb(243, 210, 206)", "1px"],
    ]);
  });

  test("統計列 12px、服務畫面頂端 18px、節點燈號 14px", async ({ page }) => {
    await page.goto("/");
    const stat = page.locator('.overview-stats li[data-color="green"]');
    expect(await style(stat, "width", "::before")).toBe("12px");
    expect(await style(stat, "box-shadow", "::before")).toBe("rgba(52, 199, 89, 0.42) 0px 0px 5px 1px");
    const grayStat = page.locator('.overview-stats li[data-color="gray"]');
    expect(await style(grayStat, "box-shadow", "::before")).toBe("rgba(0, 0, 0, 0.22) 0px 1px 2px 0px inset");

    await openEdgeB(page);
    const summary = page.locator(".target-header .summary-lamp .lamp-dot");
    expect(await style(summary, "width")).toBe("18px");
    expect(await style(summary, "box-shadow")).toBe("rgba(52, 199, 89, 0.42) 0px 0px 5px 1px");
    expect(await styles(page, "button.lamp .lamp-dot", "width")).toEqual(EDGE_NODES.map(() => "14px"));
  });
});

test("回到總覽：44px 圓形圖示，在服務名稱左側的同一行", async ({ page }) => {
  await openEdgeB(page);
  const back = page.getByRole("link", { name: "回到總覽" });
  await expect(back).toHaveAttribute("title", "回到總覽");
  await expect(back).toHaveText("");
  const box = (await back.boundingBox())!;
  expect([box.width, box.height]).toEqual([44, 44]);
  expect(await style(back, "border-top-left-radius")).toBe("50%");
  expect(await style(back, "background-color")).toBe("rgb(255, 255, 255)");
  const name = (await page.locator(".target-name").boundingBox())!;
  expect(box.x + box.width).toBeLessThanOrEqual(name.x);
  expect(Math.abs(box.y + box.height / 2 - (name.y + name.height / 2))).toBeLessThan(box.height / 2);
});

test.describe("主迴圈的光點流動", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test.afterEach(async ({ request }) => {
    await setScenario(request, "mock-edge-b", "normal");
  });

  test("正常情境：主迴圈流動，子 lane 不流動，光點實際移動", async ({ page }) => {
    await openEdgeB(page);
    await expect(page.locator(MAIN)).toHaveAttribute("data-flowing", "true");
    await expect(page.locator('[data-lane-id="ingest-bg"]')).toHaveAttribute("data-flowing", "false");
    await expect(page.locator('[data-lane-id="stream-bg"]')).toHaveAttribute("data-flowing", "false");
    expect(await styles(page, OWN_LAMPS, "animation-name")).toEqual(Array(4).fill("flow-node-n4"));
    expect(await styles(page, OWN_DOTS, "animation-name")).toEqual(Array(4).fill("flow-dot-n4"));
    expect(await styles(page, OWN_LIGHTS, "animation-name")).toEqual(Array(3).fill("flow-arrow-n4"));
    expect(await styles(page, OWN_LAMPS, "animation-duration")).toEqual(Array(4).fill("3.2s"));
    expect(await styles(page, OWN_LAMPS, "animation-delay")).toEqual(["0s", "0.64s", "1.28s", "1.92s"]);
    expect(await styles(page, OWN_LIGHTS, "animation-delay")).toEqual(["0.32s", "0.96s", "1.6s"]);
    // 子 lane 的燈號不動
    expect(await styles(page, '[data-lane-id="ingest-bg"] .lamp', "animation-name")).toEqual(["none"]);
    // 光點真的在動：取樣到某個箭頭光點的不透明度超過 0.5
    await expect
      .poll(async () => Math.max(...(await styles(page, OWN_LIGHTS, "opacity")).map(Number)), { intervals: [50] })
      .toBeGreaterThan(0.5);
  });

  test("輪詢更新兩次後，燈號元素與動畫都是同一個，沒有重新開始", async ({ page }) => {
    await openEdgeB(page);
    await expect(page.locator(MAIN)).toHaveAttribute("data-flowing", "true");
    const keep = () =>
      page.evaluate((sel) => {
        const w = window as unknown as { kept: { el: Element; anim: Animation }[] };
        w.kept = [...document.querySelectorAll(sel)].map((el) => ({ el, anim: el.getAnimations()[0] }));
        return w.kept.length;
      }, `${OWN_LAMPS}, ${OWN_LIGHTS}`);
    expect(await keep()).toBe(7);
    // 前端每秒輪詢一次（config/targets.dev.yaml）：等最後更新時間變了兩次
    const lastUpdate = page.locator(".target-header .last-update");
    for (let i = 0; i < 2; i += 1) {
      const before = await lastUpdate.textContent();
      await expect(lastUpdate).not.toHaveText(before ?? "");
    }
    const same = await page.evaluate((sel) => {
      const w = window as unknown as { kept: { el: Element; anim: Animation }[] };
      const now = [...document.querySelectorAll(sel)];
      return w.kept.map(({ el, anim }, i) => [
        now[i] === el,
        el.getAnimations()[0] === anim,
        anim.playState,
        (anim.currentTime as number) > 1000,
      ]);
    }, `${OWN_LAMPS}, ${OWN_LIGHTS}`);
    expect(same).toEqual(Array(7).fill([true, true, "running", true]));
  });

  test("選取中的燈號用保留選取框的 keyframes", async ({ page }) => {
    await openEdgeB(page);
    await page.locator('button.lamp[data-node-id="infer"]').click();
    await expect(page.locator('button.lamp[data-node-id="infer"]')).toHaveAttribute("aria-pressed", "true");
    expect(await style(page.locator('button.lamp[data-node-id="infer"]'), "animation-name")).toBe("flow-node-pressed-n4");
    expect(await style(page.locator('button.lamp[data-node-id="ingest"]'), "animation-name")).toBe("flow-node-n4");
  });

  test("斷相機情境：不流動", async ({ page, request }) => {
    await openEdgeB(page);
    await setScenario(request, "mock-edge-b", "camera_down");
    // camera_down：ingest-worker 紅、其他灰（SPEC §8.2）
    await expect(page.locator('button.lamp[data-node-id="ingest-worker"]')).toHaveAttribute("data-color", "red");
    await expect(page.locator(MAIN)).toHaveAttribute("data-flowing", "false");
    expect(await styles(page, OWN_LAMPS, "animation-name")).toEqual(Array(4).fill("none"));
    expect(await styles(page, OWN_LIGHTS, "animation-name")).toEqual(Array(3).fill("none"));
    expect(await styles(page, OWN_LIGHTS, "opacity")).toEqual(Array(3).fill("0"));
  });

  test("不同架構：mock-api 的 3 個節點主迴圈依節點數流動", async ({ page }) => {
    await openTarget(page, "mock-api");
    await waitLamps(page, uniform(API_NODES, lampOf("ok")));
    await expect(page.locator(MAIN)).toHaveAttribute("data-flowing", "true");
    await expect(page.locator('[data-lane-id="workers"]')).toHaveAttribute("data-flowing", "false");
    expect(await styles(page, OWN_LAMPS, "animation-name")).toEqual(Array(3).fill("flow-node-n3"));
    expect(await styles(page, OWN_LAMPS, "animation-duration")).toEqual(Array(3).fill("2.56s"));
  });

  test("reduced motion：data-flowing 照資料判斷，動畫關掉", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await openEdgeB(page);
    await expect(page.locator(MAIN)).toHaveAttribute("data-flowing", "true");
    expect(await styles(page, OWN_LAMPS, "animation-name")).toEqual(Array(4).fill("none"));
    expect(await styles(page, OWN_DOTS, "animation-name")).toEqual(Array(4).fill("none"));
    expect(await styles(page, OWN_LIGHTS, "animation-name")).toEqual(Array(3).fill("none"));
    // 靜態的發光樣式照常
    expect(await styles(page, OWN_DOTS, "box-shadow")).toEqual(Array(4).fill("rgba(52, 199, 89, 0.42) 0px 0px 5px 1px"));
  });

  for (const [width, name] of [
    [360, "none"],
    [640, "none"],
    [641, "flow-node-n4"],
  ] as const) {
    test(`寬度 ${width}px：燈號動畫為 ${name}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 740 });
      await openEdgeB(page);
      await expect(page.locator(MAIN)).toHaveAttribute("data-flowing", "true");
      expect(await styles(page, OWN_LAMPS, "animation-name")).toEqual(Array(4).fill(name));
      if (name === "none") {
        expect(await styles(page, OWN_DOTS, "animation-name")).toEqual(Array(4).fill("none"));
        expect(await styles(page, OWN_LIGHTS, "animation-name")).toEqual(Array(3).fill("none"));
      }
    });
  }
});
