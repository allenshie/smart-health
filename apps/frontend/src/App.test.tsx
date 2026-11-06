import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { fetchConfig, fetchTarget, fetchTargets } from "./api/client";
import type { TargetDetail } from "./api/types";
import { apiTopology, edgeTopology, nodeView, summaryOf, targetDetail } from "./test/fixtures";

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

const mockConfig = vi.mocked(fetchConfig);
const mockTargets = vi.mocked(fetchTargets);
const mockTarget = vi.mocked(fetchTarget);

const INTERVAL_MS = 5000;

/** 讓計時器前進並把連鎖的 promise 與 React 更新都處理完。 */
async function advance(ms: number) {
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
function serve(...details: TargetDetail[]) {
  let index = 0;
  const current = () => details[Math.min(index, details.length - 1)];
  mockTargets.mockImplementation(async () => [summaryOf(current())]);
  mockTarget.mockImplementation(async () => {
    const d = current();
    index += 1;
    return d;
  });
}

function lamp(id: string): HTMLElement {
  const found = screen
    .getAllByRole("button")
    .filter((b) => b.getAttribute("data-node-id") === id);
  if (found.length === 0) throw new Error(`找不到節點 ${id} 的燈號`);
  return found[0];
}

function detailRegion() {
  return screen.queryByRole("region", { name: "節點詳細資料" });
}

beforeEach(() => {
  vi.useFakeTimers();
  mockConfig.mockReset().mockResolvedValue({ poll_interval_s: 5 });
  mockTargets.mockReset();
  mockTarget.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("App", () => {
  it("shows the selector and last update time from config and targets", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    expect(screen.getByRole("combobox", { name: "服務：" })).toBeTruthy();
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
    // 保留最後的畫面。
    expect(lamp("ingest")).toBeTruthy();
    expect(detailRegion()).not.toBeNull();

    const calls = mockTarget.mock.calls.length;
    await advance(INTERVAL_MS);
    expect(mockTarget.mock.calls.length).toBeGreaterThan(calls);
    expect(screen.getByRole("alert")).toBeTruthy();

    serve(targetDetail());
    await advance(INTERVAL_MS);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(lamp("ingest")).toBeTruthy();
  });

  it("shows the detail error when only the target detail fails", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    mockTarget.mockRejectedValue(new TypeError("Failed to fetch"));
    await advance(INTERVAL_MS);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(lamp("ingest")).toBeTruthy();
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

  it("keeps the chosen target, clears node selection on switch, and falls back to the first", async () => {
    const a = targetDetail();
    const b = targetDetail({ id: "mock-api", name: "Mock API", topology: apiTopology });
    mockTargets.mockResolvedValue([summaryOf(a), summaryOf(b)]);
    mockTarget.mockImplementation(async (id) => (id === b.id ? b : a));
    render(<App />);
    await advance(0);
    fireEvent.click(lamp("infer"));

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "mock-api" } });
    await advance(0);
    expect(lamp("gateway")).toBeTruthy();
    expect(detailRegion()).toBeNull();

    await advance(INTERVAL_MS);
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("mock-api");

    mockTargets.mockResolvedValue([summaryOf(a)]);
    await advance(INTERVAL_MS);
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("mock-edge-a");
    expect(lamp("infer")).toBeTruthy();
  });

  it("stays on the fallback target when the chosen one comes back", async () => {
    const a = targetDetail();
    const b = targetDetail({ id: "mock-api", name: "Mock API", topology: apiTopology });
    mockTargets.mockResolvedValue([summaryOf(a), summaryOf(b)]);
    mockTarget.mockImplementation(async (id) => (id === b.id ? b : a));
    render(<App />);
    await advance(0);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "mock-api" } });
    await advance(0);

    mockTargets.mockResolvedValue([summaryOf(a)]);
    await advance(INTERVAL_MS);
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("mock-edge-a");

    mockTargets.mockResolvedValue([summaryOf(a), summaryOf(b)]);
    await advance(INTERVAL_MS);
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("mock-edge-a");
    expect(lamp("infer")).toBeTruthy();
  });

  it("keeps the initially shown target when the list order changes", async () => {
    const a = targetDetail();
    const b = targetDetail({ id: "mock-api", name: "Mock API", topology: apiTopology });
    mockTargets.mockResolvedValue([summaryOf(a), summaryOf(b)]);
    mockTarget.mockImplementation(async (id) => (id === b.id ? b : a));
    render(<App />);
    await advance(0);
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("mock-edge-a");

    mockTargets.mockResolvedValue([summaryOf(b), summaryOf(a)]);
    await advance(INTERVAL_MS);
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("mock-edge-a");
    expect(lamp("infer")).toBeTruthy();
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
});
