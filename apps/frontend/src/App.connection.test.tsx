// App 整合測試：連線、錯誤。api/client 以 vi.mock 取代，共用工具見 test/appHarness.ts。
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { INTERVAL_MS, advance, detailRegion, lamp, mockConfig, mockTarget, mockTargets, resetMocks, serve } from "./test/appHarness";
import { edgeTopology, nodeView, targetDetail } from "./test/fixtures";

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

beforeEach(resetMocks);
afterEach(() => {
  vi.useRealTimers();
});

describe("App 連線、錯誤", () => {
  it("not online shows banner and gray lamps", async () => {
    // 後端照規格會回 gray；這裡故意給 green，確認前端仍轉灰。
    const nodes = Object.fromEntries(
      edgeTopology.nodes.map((n) => [n.id, nodeView({ state: null, reason: "offline", color: "green" })]),
    );
    serve(targetDetail({ connection: "offline", summary_color: "gray", nodes }));
    render(<App />);
    await advance(0);
    expect(screen.getByRole("status").textContent).toBe(
      "無法連線到此服務（offline），最後更新 10:32:15",
    );
    const lamps = screen.getAllByRole("button");
    expect(lamps.length).toBe(edgeTopology.nodes.length);
    for (const b of lamps) {
      expect(b.getAttribute("data-color")).toBe("gray");
      expect(b.textContent).toContain("未知");
    }
  });

  it("shows error and retries when backend is unreachable", async () => {
    vi.setSystemTime(new Date("2026-11-06T02:32:15Z"));
    serve(targetDetail());
    render(<App />);
    await advance(0);
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(lamp("infer"));

    mockTargets.mockRejectedValue(new TypeError("Failed to fetch"));
    mockTarget.mockRejectedValue(new TypeError("Failed to fetch"));
    await advance(INTERVAL_MS);
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toContain("無法連線到後端，將自動重試");
    expect(alerts[0].textContent).toContain("最後成功 10:32:15");
    // 保留架構與詳細面板，但燈號轉灰：沒有人知道最後的顏色是否仍成立。
    expect(lamp("ingest").getAttribute("data-color")).toBe("gray");
    expect(screen.getAllByRole("button").every((b) => b.getAttribute("data-color") === "gray")).toBe(true);
    expect(detailRegion()).not.toBeNull();

    const calls = mockTarget.mock.calls.length;
    await advance(INTERVAL_MS);
    expect(mockTarget.mock.calls.length).toBeGreaterThan(calls);
    expect(screen.getByRole("alert")).toBeTruthy();

    serve(targetDetail());
    await advance(INTERVAL_MS);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(lamp("ingest").getAttribute("data-color")).toBe("green");
  });

  it("shows the detail error when only the target detail fails", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    mockTarget.mockRejectedValue(new TypeError("Failed to fetch"));
    await advance(INTERVAL_MS);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(lamp("ingest").getAttribute("data-color")).toBe("gray");
  });

  it("retries config every 3 seconds and waits for it before polling targets", async () => {
    mockConfig.mockReset().mockRejectedValueOnce(new TypeError("Failed to fetch"));
    mockConfig.mockResolvedValue({ poll_interval_s: 5 });
    serve(targetDetail());
    render(<App />);
    await advance(0);
    expect(screen.getByText("載入中…")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("無法連線到後端，將自動重試");
    expect(mockTargets).not.toHaveBeenCalled();

    await advance(2999);
    expect(mockConfig).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(mockConfig).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(mockTargets).toHaveBeenCalled();

    await advance(60000);
    expect(mockConfig).toHaveBeenCalledTimes(2);
  });

  it("shows 尚未取得 when the target was never fetched successfully", async () => {
    serve(targetDetail({ connection: "unknown", last_success_at: null, topology: null, nodes: {} }));
    render(<App />);
    await advance(0);
    expect(screen.getByText("最後更新 尚未取得（每 5 秒）")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe(
      "尚未取得此服務的狀態（unknown），尚未成功取得",
    );
  });

  it("grays lamps when only the target list fails", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    mockTargets.mockRejectedValue(new TypeError("Failed to fetch"));
    await advance(INTERVAL_MS);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getAllByRole("button").every((b) => b.getAttribute("data-color") === "gray")).toBe(true);
    expect(mockTarget.mock.calls.length).toBeGreaterThan(1); // 詳細資料仍成功更新
  });
});
