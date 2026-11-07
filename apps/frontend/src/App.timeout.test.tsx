// 後端掛住（請求永不回應）時：逾時後顯示錯誤、燈號轉灰，並繼續排下一輪。
// 這裡不 mock api/client，改 stub 全域 fetch，驗證真實的逾時路徑。
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { REQUEST_TIMEOUT_MS } from "./api/client";
import { INTERVAL_MS, advance } from "./test/appHarness";
import { summaryOf, targetDetail } from "./test/fixtures";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** hanging 為真時，/api/targets 與 /api/targets/{id} 都永不回應，收到 abort 才 reject。 */
function stubBackend() {
  const state = { hanging: false };
  const detail = targetDetail();
  const fn = vi.fn((url: string, init?: RequestInit) => {
    if (url === "/api/config") return Promise.resolve(json({ poll_interval_s: INTERVAL_MS / 1000 }));
    if (state.hanging) {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("The operation was aborted.", "AbortError")),
        );
      });
    }
    return Promise.resolve(json(url === "/api/targets" ? [summaryOf(detail)] : detail));
  });
  vi.stubGlobal("fetch", fn);
  return { fn, state };
}

function targetCalls(fn: ReturnType<typeof stubBackend>["fn"]): number {
  return fn.mock.calls.filter(([url]) => url === "/api/targets").length;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("App request timeout", () => {
  it("shows the backend error, grays lamps and schedules the next poll", async () => {
    const { fn, state } = stubBackend();
    render(<App />);
    await advance(0);
    const lamps = () => screen.getAllByRole("button");
    expect(lamps().every((b) => b.getAttribute("data-color") === "green")).toBe(true);

    state.hanging = true;
    await advance(INTERVAL_MS);
    const calls = targetCalls(fn);
    expect(screen.queryByRole("alert")).toBeNull();

    await advance(REQUEST_TIMEOUT_MS);
    expect(screen.getAllByRole("alert")[0].textContent).toContain("無法連線到後端，將自動重試");
    expect(lamps().every((b) => b.getAttribute("data-color") === "gray")).toBe(true);

    await advance(INTERVAL_MS);
    expect(targetCalls(fn)).toBeGreaterThan(calls); // 逾時後已排下一輪並發出請求

    state.hanging = false;
    await advance(REQUEST_TIMEOUT_MS + INTERVAL_MS);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(lamps().every((b) => b.getAttribute("data-color") === "green")).toBe(true);
  });
});
