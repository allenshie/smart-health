// App 整合測試的共用工具。使用的測試檔必須自行 vi.mock("./api/client")，
// 這裡取得的 fetchConfig 等函式才會是 mock。
import { act, screen } from "@testing-library/react";
import { vi } from "vitest";
import { fetchConfig, fetchTarget, fetchTargets } from "../api/client";
import type { TargetDetail } from "../api/types";
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
