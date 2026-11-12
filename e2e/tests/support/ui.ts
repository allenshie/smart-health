/** 畫面操作與斷言：只用 Task 9 畫面上既有的屬性當選擇器。 */
import * as path from "node:path";
import { expect, type Page } from "@playwright/test";

/** 燈號快照：節點 id -> 顏色（data-color）與狀態文字（.lamp-state）。 */
export type Lamp = { color: string | null; state: string };
export type LampSnapshot = Record<string, Lamp>;

/** state 為 null（連線異常、status_missing）時畫面顯示的文字。 */
export const UNKNOWN = "未知";

export const STATE_COLOR: Record<string, string> = {
  ok: "green",
  degraded: "yellow",
  unavailable: "red",
  waiting: "gray",
  disabled: "gray",
};

/** 依狀態碼組出預期燈號；顏色由狀態推得（SPEC §2.2）。 */
export function lampOf(state: string): Lamp {
  return { color: STATE_COLOR[state], state };
}

export const GRAY_UNKNOWN: Lamp = { color: "gray", state: UNKNOWN };

export function uniform(ids: readonly string[], lamp: Lamp): LampSnapshot {
  return Object.fromEntries(ids.map((id) => [id, lamp]));
}

// e2e/run.sh 以 E2E_SCREENSHOT_DIR 傳入掛載的截圖目錄；未設定時（直接在 repo 內執行）寫到 docs/acceptance/screenshots
const SCREENSHOT_DIR =
  process.env.E2E_SCREENSHOT_DIR ?? path.resolve(__dirname, "../../../docs/acceptance/screenshots");

export function screenshotPath(name: string): string {
  return path.join(SCREENSHOT_DIR, `${name}.png`);
}

/** 以服務網址開啟指定目標的服務畫面（SPEC §7.1），等到取得目標資料、顯示服務名稱。 */
export async function openTarget(page: Page, targetId: string): Promise<void> {
  await page.goto(`/#/targets/${targetId}`);
  await expect(page.locator(`.target-screen[data-target-id="${targetId}"] .target-name`)).toBeVisible();
}

/** 總覽上指定目標的卡片連結。 */
export function targetCard(page: Page, targetId: string) {
  return page.locator(`a.target-card[data-target-id="${targetId}"]`);
}

export async function lampSnapshot(page: Page): Promise<LampSnapshot> {
  return page.locator("button.lamp").evaluateAll((els) =>
    Object.fromEntries(
      els.map((el) => [
        el.getAttribute("data-node-id") ?? "",
        {
          color: el.getAttribute("data-color"),
          state: el.querySelector(".lamp-state")?.textContent ?? "",
        },
      ]),
    ),
  );
}

/** 畫面上燈號的節點 id，依 DOM 順序。 */
export async function lampIds(page: Page): Promise<string[]> {
  return page.locator("button.lamp").evaluateAll((els) => els.map((el) => el.getAttribute("data-node-id") ?? ""));
}

/** 等到畫面上所有燈號（含節點集合）與預期完全相同。 */
export async function waitLamps(page: Page, expected: LampSnapshot, timeout = 30_000): Promise<void> {
  await expect.poll(() => lampSnapshot(page), { timeout, message: "燈號與預期不同" }).toEqual(expected);
}

/** online 時不顯示橫幅；其他連線狀態顯示帶連線代碼的橫幅。 */
export async function expectConnection(page: Page, code: string): Promise<void> {
  if (code === "online") {
    await expect(page.locator("p.banner")).toHaveCount(0);
  } else {
    await expect(page.locator(`p.banner[role="status"][data-connection="${code}"]`)).toBeVisible();
  }
}

/** 等「最後更新」時間前進 times 次（每次都是新的後端拉取結果）。 */
export async function waitForUpdates(page: Page, times = 2): Promise<void> {
  const lastUpdate = page.locator(".last-update");
  for (let i = 0; i < times; i++) {
    const before = (await lastUpdate.textContent()) ?? "";
    await expect(lastUpdate).not.toHaveText(before);
  }
}

/** 已符合的燈號在後續數次更新後仍維持，避免只是短暫符合。 */
export async function expectLampsHold(page: Page, expected: LampSnapshot): Promise<void> {
  await waitForUpdates(page);
  expect(await lampSnapshot(page)).toEqual(expected);
}

/** 詳細面板中指定欄位（dt）對應的值（dd）。 */
export function detailField(page: Page, label: string) {
  return page.locator("section.node-detail dt", { hasText: label }).locator("xpath=following-sibling::dd[1]");
}
