// App 整合測試：選取。api/client 以 vi.mock 取代，共用工具見 test/appHarness.ts。
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { INTERVAL_MS, advance, detailRegion, lamp, mockTarget, resetMocks, serve, setHash } from "./test/appHarness";
import { apiTopology, edgeTopology, nodeView, targetDetail } from "./test/fixtures";

vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/client")>();
  return {
    ...actual,
    fetchConfig: vi.fn(),
    fetchTargets: vi.fn(),
    fetchTarget: vi.fn(),
    fetchTransitions: vi.fn(),
  };
});

// v1.7 起沒有預設目標：以服務網址進入服務畫面（只改進入方式）。
beforeEach(() => {
  resetMocks();
  setHash("#/targets/mock-edge-a");
});
afterEach(() => {
  vi.useRealTimers();
});

describe("App 選取", () => {
  it("shows the last update time from config and the target", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    expect(screen.getByText("最後更新 10:32:15（每 5 秒）")).toBeTruthy();
    expect(mockTarget).toHaveBeenCalledWith("mock-edge-a");
  });

  it("clicking a node shows state, reason, message, since and metrics", async () => {
    const nodes = Object.fromEntries(edgeTopology.nodes.map((n) => [n.id, nodeView()]));
    nodes["ingest-worker"] = nodeView({
      state: "unavailable",
      reason: "no_new_frame",
      message: "已 12 秒沒有成功紀錄",
      since: "2026-11-06T02:32:03Z",
      metrics: { fps: 0.5 },
      color: "red",
    });
    serve(targetDetail({ nodes }));
    render(<App />);
    await advance(0);
    expect(detailRegion()).toBeNull();

    fireEvent.click(lamp("ingest-worker"));
    const region = detailRegion();
    expect(region).not.toBeNull();
    const text = region!.textContent ?? "";
    for (const part of ["unavailable", "no_new_frame", "已 12 秒沒有成功紀錄", "10:32:03", "fps = 0.5"]) {
      expect(text).toContain(part);
    }
    expect(lamp("ingest-worker").getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(lamp("ingest-worker"));
    expect(detailRegion()).toBeNull();
    expect(lamp("ingest-worker").getAttribute("aria-pressed")).toBe("false");
  });

  it("selection survives refresh", async () => {
    const before = targetDetail();
    const after = targetDetail({
      nodes: { ...before.nodes, infer: nodeView({ state: "degraded", message: "第二輪", color: "yellow" }) },
    });
    serve(before, after);
    render(<App />);
    await advance(0);
    fireEvent.click(lamp("infer"));
    expect(within(detailRegion()!).getByText("ok")).toBeTruthy();

    await advance(INTERVAL_MS);
    expect(mockTarget).toHaveBeenCalledTimes(2);
    const region = detailRegion();
    expect(region).not.toBeNull();
    expect(within(region!).getByText("degraded")).toBeTruthy();
    expect(within(region!).getByText("第二輪")).toBeTruthy();
    expect(lamp("infer").getAttribute("aria-pressed")).toBe("true");
  });

  it("selection closes when node disappears", async () => {
    serve(targetDetail(), targetDetail({ topology: apiTopology }), targetDetail());
    render(<App />);
    await advance(0);
    fireEvent.click(lamp("infer"));
    expect(detailRegion()).not.toBeNull();

    await advance(INTERVAL_MS);
    expect(detailRegion()).toBeNull();

    // 節點回來時不會自動重新打開。
    await advance(INTERVAL_MS);
    expect(lamp("infer").getAttribute("aria-pressed")).toBe("false");
    expect(detailRegion()).toBeNull();
  });
});
