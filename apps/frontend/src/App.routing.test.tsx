// App 整合測試：網址的 hash 與兩層畫面（SPEC §7.1）。api/client 以 vi.mock 取代，共用工具見 test/appHarness.ts。
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { advance, card, cards, follow, goBack, goForward, lamp, mockTarget, mockTargets, navigate, resetMocks, setHash, summaries } from "./test/appHarness";
import { apiTopology, summaryOf, targetDetail } from "./test/fixtures";

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

const a = targetDetail();
const b = targetDetail({ id: "mock-api", name: "Mock API", topology: apiTopology });

beforeEach(() => {
  resetMocks();
  mockTargets.mockResolvedValue([summaryOf(a), summaryOf(b)]);
  mockTarget.mockImplementation(async (id) => (id === b.id ? b : a));
});
afterEach(() => {
  vi.useRealTimers();
});

const isOverview = () => screen.queryByRole("heading", { name: "服務總覽" }) !== null;
const isService = (name: string) => screen.queryByRole("heading", { name }) !== null && !isOverview();

describe("hash 與畫面", () => {
  it("shows overview page 1 for an empty hash without rewriting it", async () => {
    setHash("");
    render(<App />);
    await advance(0);
    expect(isOverview()).toBe(true);
    expect(cards()).toHaveLength(2);
    expect(window.location.hash).toBe("");
  });

  it("shows overview page 1 for #/", async () => {
    setHash("#/");
    render(<App />);
    await advance(0);
    expect(isOverview()).toBe(true);
    expect(window.location.hash).toBe("#/");
  });

  it("shows the service screen for #/targets/<id> and polls only that target", async () => {
    setHash("#/targets/mock-api");
    render(<App />);
    await advance(0);
    expect(isService("Mock API")).toBe(true);
    expect(lamp("gateway")).toBeTruthy();
    expect(mockTarget).toHaveBeenCalledWith("mock-api");
    expect(mockTargets).not.toHaveBeenCalled();
  });

  it.each(["#foo", "#/foo", "#/targets", "#?page=2"])(
    "replaces %s with #/ and shows the overview",
    async (hash) => {
      setHash(hash);
      const length = window.history.length;
      render(<App />);
      await advance(0);
      expect(window.location.hash).toBe("#/");
      expect(window.history.length).toBe(length);
      expect(isOverview()).toBe(true);
    },
  );

  it("replaces an unknown hash typed while the app is open", async () => {
    setHash("#/");
    render(<App />);
    await advance(0);
    await navigate("#/nowhere");
    expect(window.location.hash).toBe("#/");
    expect(isOverview()).toBe(true);
  });
});

describe("瀏覽紀錄", () => {
  it("goes overview → card → service and back and forward with the browser", async () => {
    setHash("#/");
    render(<App />);
    await advance(0);

    await follow(card("mock-api"));
    expect(window.location.hash).toBe("#/targets/mock-api");
    expect(isService("Mock API")).toBe(true);
    expect(lamp("gateway")).toBeTruthy();

    await goBack();
    expect(window.location.hash).toBe("#/");
    expect(isOverview()).toBe(true);

    await goForward();
    expect(isService("Mock API")).toBe(true);
    expect(lamp("gateway")).toBeTruthy();
  });

  it("stays on the same service screen after a refresh", async () => {
    setHash("#/targets/mock-api");
    const first = render(<App />);
    await advance(0);
    expect(isService("Mock API")).toBe(true);
    first.unmount();

    render(<App />);
    await advance(0);
    expect(window.location.hash).toBe("#/targets/mock-api");
    expect(isService("Mock API")).toBe(true);
    expect(lamp("gateway")).toBeTruthy();
  });

  it("stays on the same overview page after a refresh", async () => {
    mockTargets.mockResolvedValue(summaries(30));
    setHash("#/?page=2");
    const first = render(<App />);
    await advance(0);
    expect(cards()).toHaveLength(6);
    first.unmount();

    render(<App />);
    await advance(0);
    expect(window.location.hash).toBe("#/?page=2");
    expect(cards()).toHaveLength(6);
  });
});
