import { afterEach, beforeEach, expect, vi } from "vitest";

// 測試期間出現 console.error / console.warn（例如 React 的 act 警告）就讓測試失敗。
// 先收集呼叫內容，在 afterEach 斷言，非同步回呼或被 try/catch 吞掉的呼叫也會歸屬到該測試。
let calls: string[] = [];
let spies: Array<ReturnType<typeof vi.spyOn>> = [];

beforeEach(() => {
  calls = [];
  spies = (["error", "warn"] as const).map((level) =>
    vi.spyOn(console, level).mockImplementation((...args: unknown[]) => {
      calls.push(`console.${level}：${args.map(String).join(" ")}`);
    }),
  );
});

afterEach(() => {
  spies.forEach((s) => s.mockRestore());
  expect(calls, `測試中出現 console 輸出：\n${calls.join("\n")}`).toEqual([]);
});
