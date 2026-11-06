import { afterEach, beforeEach, vi } from "vitest";

// 測試期間出現 console.error / console.warn（例如 React 的 act 警告）就讓測試失敗。
let spies: Array<ReturnType<typeof vi.spyOn>> = [];

beforeEach(() => {
  spies = (["error", "warn"] as const).map((level) =>
    vi.spyOn(console, level).mockImplementation((...args: unknown[]) => {
      throw new Error(`測試中出現 console.${level}：${args.map(String).join(" ")}`);
    }),
  );
});

afterEach(() => {
  spies.forEach((s) => s.mockRestore());
});
