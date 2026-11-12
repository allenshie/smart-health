// App 整合測試的共用工具。使用的測試檔必須自行 vi.mock("./api/client")，
// 這裡取得的 fetchConfig 等函式才會是 mock。
import { act, fireEvent, screen } from "@testing-library/react";
import { vi } from "vitest";
import { fetchConfig, fetchTarget, fetchTargets } from "../api/client";
import type { Color, Connection, TargetDetail, TargetSummary } from "../api/types";
import { summaryOf } from "./fixtures";

export const mockConfig = vi.mocked(fetchConfig);
export const mockTargets = vi.mocked(fetchTargets);
export const mockTarget = vi.mocked(fetchTarget);

export const INTERVAL_MS = 5000;

/** 讓計時器前進並把連鎖的 promise 與 React 更新都處理完。 */
export async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  for (let i = 0; i < 5; i += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  }
}

/** 依序回傳 details；最後一筆會一直重複。目標清單由當下的 detail 推出。 */
export function serve(...details: TargetDetail[]) {
  let index = 0;
  const current = () => details[Math.min(index, details.length - 1)];
  mockTargets.mockImplementation(async () => [summaryOf(current())]);
  mockTarget.mockImplementation(async () => {
    const d = current();
    index += 1;
    return d;
  });
}

export function lamp(id: string): HTMLElement {
  const found = screen
    .getAllByRole("button")
    .filter((b) => b.getAttribute("data-node-id") === id);
  if (found.length === 0) throw new Error(`找不到節點 ${id} 的燈號`);
  return found[0];
}

export function detailRegion() {
  return screen.queryByRole("region", { name: "節點詳細資料" });
}

/** 每個測試前：使用 fake timers，config 回傳 5 秒間隔，其他 mock 清空。 */
export function resetMocks() {
  vi.useFakeTimers();
  mockConfig.mockReset().mockResolvedValue({ poll_interval_s: 5 });
  mockTargets.mockReset();
  mockTarget.mockReset();
}

/** render 之前設定網址的 hash（replace，不新增瀏覽紀錄，也不觸發 hashchange）。 */
export function setHash(hash: string) {
  window.history.replaceState(null, "", hash === "" ? window.location.pathname : hash);
}

/** 像使用者一樣改變 hash（新增瀏覽紀錄並觸發 hashchange），再處理完後續更新。 */
export async function navigate(hash: string) {
  window.location.hash = hash;
  await advance(0);
}

/** 點擊連結並處理導覽：jsdom 的連結 fragment 導覽要再過一個計時器 tick（1 ms）才觸發 hashchange。 */
export async function follow(link: HTMLElement) {
  fireEvent.click(link);
  await advance(1);
}

/** 瀏覽器的上一頁、下一頁：jsdom 同樣在下一個計時器 tick 才完成。 */
export async function goBack() {
  window.history.back();
  await advance(1);
}

export async function goForward() {
  window.history.forward();
  await advance(1);
}

/** n 個 online、green 的目標：svc-01、svc-02…，名稱 Service 01…。 */
export function summaries(n: number, connection: Connection = "online", color: Color = "green"): TargetSummary[] {
  return Array.from({ length: n }, (_v, i) => {
    const no = String(i + 1).padStart(2, "0");
    return {
      id: `svc-${no}`,
      name: `Service ${no}`,
      connection,
      summary_color: color,
      last_success_at: "2026-11-06T02:32:15Z",
    };
  });
}

/** 總覽上的卡片連結，依畫面順序。 */
export function cards(): HTMLAnchorElement[] {
  return Array.from(document.querySelectorAll<HTMLAnchorElement>("a.target-card"));
}

export function card(id: string): HTMLAnchorElement {
  const found = cards().find((c) => c.getAttribute("data-target-id") === id);
  if (found === undefined) throw new Error(`找不到目標 ${id} 的卡片`);
  return found;
}

/** 總覽統計列的文字，例如 ["正常 6", "注意 1", "異常 0", "離線或等待 2"]。 */
export function statsText(): string[] {
  const list = screen.getByRole("list", { name: "統計" });
  return Array.from(list.querySelectorAll("li")).map((li) => li.textContent ?? "");
}

export function pager() {
  return screen.queryByRole("navigation", { name: "分頁" });
}
