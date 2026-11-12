// App 整合測試：服務畫面（SPEC §7.1）。api/client 以 vi.mock 取代，共用工具見 test/appHarness.ts。
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { ApiError } from "./api/client";
import {
  INTERVAL_MS,
  advance,
  follow,
  card,
  cards,
  detailRegion,
  lamp,
  mockTarget,
  mockTargets,
  navigate,
  resetMocks,
  serve,
  setHash,
  summaries,
} from "./test/appHarness";
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

beforeEach(() => {
  resetMocks();
  setHash("#/targets/mock-edge-a");
});
afterEach(() => {
  vi.useRealTimers();
});

const backLink = () => screen.getByRole("link", { name: "回到總覽" });
const header = () => document.querySelector(".target-header")!;
const summaryLamp = () => header().querySelector(".summary-lamp")!;
const notFound = () => document.querySelector(".not-found");

describe("服務畫面：頂端", () => {
  it("shows the back link, name, overall lamp with status text and last update", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    expect(backLink().getAttribute("href")).toBe("#/");
    expect(screen.getByRole("heading", { name: "Mock Edge A" })).toBeTruthy();
    expect(summaryLamp().getAttribute("data-color")).toBe("green");
    expect(summaryLamp().textContent).toBe("正常");
    expect(screen.getByText("最後更新 10:32:15（每 5 秒）")).toBeTruthy();
  });

  it.each([
    [{ connection: "online", summary_color: "yellow" }, "yellow", "注意"],
    [{ connection: "online", summary_color: "red" }, "red", "異常"],
    [{ connection: "offline", summary_color: "gray" }, "gray", "無法連線"],
    [{ connection: "stale", summary_color: "gray" }, "gray", "資料過舊"],
  ] as const)("uses the overview status table for %j", async (overrides, color, state) => {
    serve(targetDetail(overrides));
    render(<App />);
    await advance(0);
    expect(summaryLamp().getAttribute("data-color")).toBe(color);
    expect(summaryLamp().textContent).toBe(state);
  });

  it("grays the overall lamp with 未知 on backend error and recovers", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    mockTarget.mockRejectedValue(new TypeError("Failed to fetch"));
    await advance(INTERVAL_MS);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(summaryLamp().getAttribute("data-color")).toBe("gray");
    expect(summaryLamp().textContent).toBe("未知");

    serve(targetDetail());
    await advance(INTERVAL_MS);
    expect(summaryLamp().getAttribute("data-color")).toBe("green");
    expect(summaryLamp().textContent).toBe("正常");
  });

  it("shows the name as plain text", async () => {
    const html = "<b>bold</b>";
    serve(targetDetail({ name: html }));
    render(<App />);
    await advance(0);
    const h = header().querySelector("h1")!;
    expect(h.textContent).toBe(html);
    expect(h.querySelector("b")).toBeNull();
  });

  it("polls only /api/targets/{id}", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    await advance(INTERVAL_MS);
    await advance(INTERVAL_MS);
    expect(mockTarget).toHaveBeenCalledTimes(3);
    expect(mockTarget.mock.calls.every(([id]) => id === "mock-edge-a")).toBe(true);
    expect(mockTargets).not.toHaveBeenCalled();
  });
});

// v1.8：「回到總覽」改成圖示連結（SPEC §7.1 視覺）
describe("服務畫面：回到總覽圖示", () => {
  function expectIconLink(link: HTMLElement) {
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("aria-label")).toBe("回到總覽");
    expect(link.getAttribute("title")).toBe("回到總覽");
    expect(link.textContent).toBe("");
    const svg = link.querySelector("svg")!;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    expect(svg.querySelector("path")?.getAttribute("d")).toBe("M15 18l-6-6 6-6");
  }

  it("is an icon link with aria-label and title and no visible text", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    expectIconLink(backLink());
    expect(backLink().getAttribute("href")).toBe("#/");
  });

  it("sits right before the service name", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    expect(backLink().nextElementSibling).toBe(screen.getByRole("heading", { name: "Mock Edge A" }));
  });

  it("is the same icon link on the not-found screen", async () => {
    setHash("#/targets/mock-new");
    mockTarget.mockRejectedValue(new ApiError(404));
    render(<App />);
    await advance(0);
    expect(notFound()).not.toBeNull();
    expectIconLink(backLink());
    expect(backLink().getAttribute("href")).toBe("#/");
  });

  it("is the same icon link for an id in the wrong format", async () => {
    setHash("#/targets/Bad");
    render(<App />);
    await advance(0);
    expectIconLink(backLink());
  });
});

describe("服務畫面：回到總覽", () => {
  const thirty = summaries(30);

  beforeEach(() => {
    mockTargets.mockResolvedValue(thirty);
    mockTarget.mockImplementation(async (id) => ({ ...targetDetail(), ...thirty.find((t) => t.id === id)! }));
  });

  it("returns to the overview page viewed last", async () => {
    setHash("#/?page=2");
    render(<App />);
    await advance(0);
    await follow(card("svc-26"));
    expect(screen.getByRole("heading", { name: "Service 26" })).toBeTruthy();
    expect(backLink().getAttribute("href")).toBe("#/?page=2");

    await follow(backLink());
    expect(window.location.hash).toBe("#/?page=2");
    expect(cards().map((c) => c.getAttribute("data-target-id"))).toEqual(thirty.slice(24).map((t) => t.id));
  });

  it("returns to page 1 after the last overview page viewed was page 1", async () => {
    setHash("#/?page=2");
    render(<App />);
    await advance(0);
    await navigate("#/");
    await follow(card("svc-03"));
    expect(backLink().getAttribute("href")).toBe("#/");
  });

  it("returns to the clamped page when the requested page was past the end", async () => {
    setHash("#/?page=9");
    render(<App />);
    await advance(0);
    await follow(card("svc-25"));
    expect(backLink().getAttribute("href")).toBe("#/?page=2");
  });

  it("returns to page 1 when the service URL was opened directly", async () => {
    setHash("#/targets/svc-26");
    render(<App />);
    await advance(0);
    expect(backLink().getAttribute("href")).toBe("#/");
    await follow(backLink());
    expect(screen.getByRole("heading", { name: "服務總覽" })).toBeTruthy();
    expect(cards().map((c) => c.getAttribute("data-target-id"))).toEqual(thirty.slice(0, 24).map((t) => t.id));
  });
});

describe("服務畫面：找不到服務", () => {
  it("shows the not-found message on 404, keeps polling and recovers when the target is added back", async () => {
    setHash("#/targets/mock-new");
    mockTarget.mockRejectedValue(new ApiError(404));
    render(<App />);
    await advance(0);
    expect(notFound()?.textContent).toBe("找不到服務 mock-new");
    expect(backLink().getAttribute("href")).toBe("#/");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryAllByRole("button")).toHaveLength(0);

    await advance(INTERVAL_MS);
    expect(mockTarget).toHaveBeenCalledTimes(2);
    expect(notFound()).not.toBeNull();

    mockTarget.mockResolvedValue(targetDetail({ id: "mock-new", name: "Mock New" }));
    await advance(INTERVAL_MS);
    expect(notFound()).toBeNull();
    expect(screen.getByRole("heading", { name: "Mock New" })).toBeTruthy();
    expect(lamp("infer")).toBeTruthy();
  });

  it("shows the not-found message when the target is removed while viewing it", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    expect(lamp("infer")).toBeTruthy();

    mockTarget.mockRejectedValue(new ApiError(404));
    await advance(INTERVAL_MS);
    expect(notFound()?.textContent).toBe("找不到服務 mock-edge-a");
    expect(screen.queryAllByRole("button")).toHaveLength(0);

    serve(targetDetail());
    await advance(INTERVAL_MS);
    expect(notFound()).toBeNull();
    expect(lamp("infer")).toBeTruthy();
  });

  it("treats other HTTP errors as a backend error, not as not found", async () => {
    serve(targetDetail());
    render(<App />);
    await advance(0);
    mockTarget.mockRejectedValue(new ApiError(500));
    await advance(INTERVAL_MS);
    expect(notFound()).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(lamp("infer").getAttribute("data-color")).toBe("gray");
  });

  it.each([
    ["#/targets/Mock-Edge", "Mock-Edge"],
    ["#/targets/a%2Fb", "a/b"],
    ["#/targets/", ""],
    ["#/targets/%3Cb%3Ex%3C%2Fb%3E", "<b>x</b>"],
  ])("shows not found for an id in the wrong format (%s) without calling the backend", async (hash, id) => {
    setHash(hash);
    render(<App />);
    await advance(0);
    await advance(INTERVAL_MS);
    expect(notFound()?.textContent).toBe(`找不到服務 ${id}`);
    expect(notFound()?.querySelector("b")).toBeNull();
    expect(backLink().getAttribute("href")).toBe("#/");
    expect(window.location.hash).toBe(hash);
    expect(mockTarget).not.toHaveBeenCalled();
  });

  it.each([
    ["#/targets/%", "%"],
    ["#/targets/abc%E4", "abc%E4"],
  ])("shows not found when the id cannot be decoded (%s)", async (hash, id) => {
    setHash(hash);
    render(<App />);
    await advance(0);
    expect(notFound()?.textContent).toBe(`找不到服務 ${id}`);
    expect(mockTarget).not.toHaveBeenCalled();
  });
});

describe("服務畫面：切換與每秒次數", () => {
  it("clears the node selection when switching to another service", async () => {
    const a = targetDetail();
    const b = targetDetail({ id: "mock-api", name: "Mock API", topology: apiTopology });
    mockTarget.mockImplementation(async (id) => (id === b.id ? b : a));
    render(<App />);
    await advance(0);
    fireEvent.click(lamp("infer"));
    expect(detailRegion()).not.toBeNull();

    await navigate("#/targets/mock-api");
    expect(lamp("gateway")).toBeTruthy();
    expect(detailRegion()).toBeNull();

    await navigate("#/targets/mock-edge-a");
    expect(lamp("infer").getAttribute("aria-pressed")).toBe("false");
    expect(detailRegion()).toBeNull();
  });

  it("shows rate_per_s under the lamps and hides it on backend error", async () => {
    const nodes = Object.fromEntries(edgeTopology.nodes.map((n) => [n.id, nodeView()]));
    nodes.infer = nodeView({ metrics: { rate_per_s: 3.998789, duration_ms: 12.3456 } });
    serve(targetDetail({ nodes }));
    render(<App />);
    await advance(0);
    expect(lamp("infer").querySelector(".lamp-rate")?.textContent).toBe("4.00/s");
    expect(lamp("ingest").querySelector(".lamp-rate")).toBeNull();

    fireEvent.click(lamp("infer"));
    expect(detailRegion()?.textContent).toContain("duration_ms = 12.35");
    expect(detailRegion()?.textContent).toContain("rate_per_s = 4.00");

    mockTarget.mockRejectedValue(new TypeError("Failed to fetch"));
    await advance(INTERVAL_MS);
    expect(lamp("infer").querySelector(".lamp-rate")).toBeNull();
  });

  it("hides rate_per_s when the target is not online", async () => {
    const nodes = Object.fromEntries(
      edgeTopology.nodes.map((n) => [n.id, nodeView({ metrics: { rate_per_s: 4 } })]),
    );
    serve(targetDetail({ connection: "stale", summary_color: "gray", nodes }));
    render(<App />);
    await advance(0);
    expect(document.querySelectorAll(".lamp-rate")).toHaveLength(0);
  });
});

// v1.8 光點流動（SPEC §7.1 視覺）：經由輪詢重新判斷
describe("服務畫面：光點流動", () => {
  const main = () => document.querySelector<HTMLElement>('[data-lane-id="main"]')!;
  const flowing = (id: string) => document.querySelector(`[data-lane-id="${id}"]`)?.getAttribute("data-flowing");
  const allGreen = () => targetDetail();
  const withNode = (id: string, color: "yellow" | "red" | "gray") => {
    const nodes = Object.fromEntries(edgeTopology.nodes.map((n) => [n.id, nodeView()]));
    nodes[id] = nodeView({ color, state: color === "gray" ? "waiting" : "degraded" });
    return targetDetail({ nodes, summary_color: color });
  };

  it("flows the all-green main lane but not the single-node or non-sequential lanes", async () => {
    serve(allGreen());
    render(<App />);
    await advance(0);
    expect(flowing("main")).toBe("true");
    expect(flowing("ingest-bg")).toBe("false");
    expect(flowing("stream-bg")).toBe("false");
  });

  it("switches after each poll: node not green, not online, backend error, then back", async () => {
    serve(allGreen());
    render(<App />);
    await advance(0);
    expect(flowing("main")).toBe("true");

    serve(withNode("stream", "yellow"));
    await advance(INTERVAL_MS);
    expect(flowing("main")).toBe("false");

    serve(allGreen());
    await advance(INTERVAL_MS);
    expect(flowing("main")).toBe("true");

    serve(targetDetail({ connection: "stale", summary_color: "gray" }));
    await advance(INTERVAL_MS);
    expect(flowing("main")).toBe("false");

    serve(allGreen());
    await advance(INTERVAL_MS);
    expect(flowing("main")).toBe("true");

    mockTarget.mockRejectedValue(new TypeError("Failed to fetch"));
    await advance(INTERVAL_MS);
    expect(flowing("main")).toBe("false");

    serve(allGreen());
    await advance(INTERVAL_MS);
    expect(flowing("main")).toBe("true");
  });

  it("keeps the same lamp and arrow elements over two polls", async () => {
    serve(allGreen());
    render(<App />);
    await advance(0);
    const lamps = [...main().querySelectorAll(".lamp")];
    const arrows = [...main().querySelectorAll(".lane-arrow")];
    const dots = [...main().querySelectorAll(".lane-flow-dot")];
    const style = document.querySelector(".topology style");
    expect(lamps).toHaveLength(6);
    expect(arrows).toHaveLength(3);

    await advance(INTERVAL_MS);
    await advance(INTERVAL_MS);
    expect(mockTarget).toHaveBeenCalledTimes(3);
    expect([...main().querySelectorAll(".lamp")]).toEqual(lamps);
    expect([...main().querySelectorAll(".lane-arrow")]).toEqual(arrows);
    expect([...main().querySelectorAll(".lane-flow-dot")]).toEqual(dots);
    expect(document.querySelector(".topology style")).toBe(style);
    expect(main().getAttribute("data-flowing")).toBe("true");
  });

  it("keeps the selection while flowing", async () => {
    serve(allGreen());
    render(<App />);
    await advance(0);
    fireEvent.click(lamp("infer"));
    await advance(INTERVAL_MS);
    expect(flowing("main")).toBe("true");
    expect(lamp("infer").getAttribute("aria-pressed")).toBe("true");
    expect(detailRegion()).not.toBeNull();
  });
});
