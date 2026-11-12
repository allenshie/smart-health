// App 整合測試：服務總覽與分頁（SPEC §7.1）。api/client 以 vi.mock 取代，共用工具見 test/appHarness.ts。
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Color, Connection, TargetSummary } from "./api/types";
import {
  INTERVAL_MS,
  advance,
  follow,
  goBack,
  goForward,
  card,
  cards,
  mockTarget,
  mockTargets,
  pager,
  resetMocks,
  setHash,
  statsText,
  summaries,
} from "./test/appHarness";
import { summaryOf, targetDetail } from "./test/fixtures";

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
  setHash("#/");
});
afterEach(() => {
  vi.useRealTimers();
});

function target(id: string, connection: Connection, color: Color, last: string | null = "2026-11-06T02:32:15Z"): TargetSummary {
  return { id, name: `Name ${id}`, connection, summary_color: color, last_success_at: last };
}

const text = (el: Element, selector: string) => el.querySelector(selector)?.textContent;

describe("總覽：頂端與輪詢", () => {
  it("shows the title and the time of the last successful list request", async () => {
    vi.setSystemTime(new Date("2026-11-06T02:40:00Z"));
    mockTargets.mockResolvedValue([summaryOf(targetDetail())]);
    render(<App />);
    await advance(0);
    expect(screen.getByRole("heading", { name: "服務總覽" })).toBeTruthy();
    expect(screen.getByText("最後更新 10:40:00（每 5 秒）")).toBeTruthy();

    await advance(INTERVAL_MS);
    expect(screen.getByText("最後更新 10:40:05（每 5 秒）")).toBeTruthy();
  });

  it("shows 尚未取得 before the list was ever fetched", async () => {
    mockTargets.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<App />);
    await advance(0);
    expect(screen.getByText("最後更新 尚未取得（每 5 秒）")).toBeTruthy();
  });

  it("polls only /api/targets and never the target details", async () => {
    mockTargets.mockResolvedValue(summaries(3));
    render(<App />);
    await advance(0);
    await advance(INTERVAL_MS);
    await advance(INTERVAL_MS);
    expect(mockTargets).toHaveBeenCalledTimes(3);
    expect(mockTarget).not.toHaveBeenCalled();
  });

  it("does not pick the first target by itself", async () => {
    mockTargets.mockResolvedValue(summaries(2));
    render(<App />);
    await advance(0);
    expect(window.location.hash).toBe("#/");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(cards()).toHaveLength(2);
  });
});

describe("總覽：卡片", () => {
  // SPEC §7.1 的狀態文字表，每一列一張卡片。
  const ROWS: Array<[Connection, Color, string]> = [
    ["online", "green", "正常"],
    ["online", "yellow", "注意"],
    ["online", "red", "異常"],
    ["online", "gray", "等待中"],
    ["unknown", "gray", "尚未取得"],
    ["offline", "gray", "無法連線"],
    ["stale", "gray", "資料過舊"],
    ["incompatible", "gray", "版本不相容"],
    ["invalid_response", "gray", "回應無效"],
  ];

  it("shows the status text of every row of the table, with the summary color", async () => {
    mockTargets.mockResolvedValue(ROWS.map(([c, color], i) => target(`t${i}`, c, color)));
    render(<App />);
    await advance(0);
    ROWS.forEach(([, color, state], i) => {
      const c = card(`t${i}`);
      expect(text(c, ".card-state")).toBe(state);
      expect(c.getAttribute("data-color")).toBe(color);
    });
  });

  it("shows the connection code and the time", async () => {
    mockTargets.mockResolvedValue([
      target("up", "online", "green"),
      target("down", "offline", "gray"),
      target("never", "unknown", "gray", null),
    ]);
    render(<App />);
    await advance(0);
    expect(text(card("up"), ".card-connection")).toBe("online");
    expect(text(card("up"), ".card-time")).toBe("最後更新 10:32:15");
    expect(text(card("down"), ".card-connection")).toBe("offline");
    expect(text(card("down"), ".card-time")).toBe("最後成功 10:32:15");
    expect(text(card("never"), ".card-connection")).toBe("unknown");
    expect(text(card("never"), ".card-time")).toBe("尚未取得");
  });

  it("makes each card a link to the service screen with the full name in title", async () => {
    mockTargets.mockResolvedValue([summaryOf(targetDetail())]);
    render(<App />);
    await advance(0);
    const link = screen.getByRole("link", { name: /Mock Edge A/ });
    expect(link).toBe(card("mock-edge-a"));
    expect(link.getAttribute("href")).toBe("#/targets/mock-edge-a");
    const name = link.querySelector(".card-name")!;
    expect(name.textContent).toBe("Mock Edge A");
    expect(name.getAttribute("title")).toBe("Mock Edge A");
  });

  it("keeps the order of /api/targets", async () => {
    mockTargets.mockResolvedValue([target("zeta", "online", "green"), target("alpha", "online", "red"), target("mid", "offline", "gray")]);
    render(<App />);
    await advance(0);
    expect(cards().map((c) => c.getAttribute("data-target-id"))).toEqual(["zeta", "alpha", "mid"]);
  });

  it("shows names as plain text", async () => {
    const html = '<img src=x onerror="alert(1)"><b>bold</b>';
    mockTargets.mockResolvedValue([{ ...target("x", "online", "green"), name: html }]);
    render(<App />);
    await advance(0);
    const c = card("x");
    expect(text(c, ".card-name")).toBe(html);
    expect(c.querySelector("img")).toBeNull();
    expect(c.querySelector("b")).toBeNull();
  });

  it("shows 尚未設定任何服務 when there are no targets", async () => {
    mockTargets.mockResolvedValue([]);
    render(<App />);
    await advance(0);
    expect(screen.getByText("尚未設定任何服務")).toBeTruthy();
    expect(cards()).toHaveLength(0);
    expect(pager()).toBeNull();
  });
});

describe("總覽：統計列", () => {
  it("counts all targets, not only this page", async () => {
    // 30 個目標：第 1 頁只有 24 個，黃、紅、灰都有一部分在第 2 頁。
    const list = [
      ...summaries(20),
      ...summaries(5, "online", "yellow").map((t, i) => ({ ...t, id: `y${i}` })),
      ...summaries(3, "online", "red").map((t, i) => ({ ...t, id: `r${i}` })),
      ...summaries(2, "offline", "gray").map((t, i) => ({ ...t, id: `g${i}` })),
    ];
    mockTargets.mockResolvedValue(list);
    render(<App />);
    await advance(0);
    expect(cards()).toHaveLength(24);
    expect(statsText()).toEqual(["正常 20", "注意 5", "異常 3", "離線或等待 2"]);
  });

  it("always shows the 4 categories, including zeros", async () => {
    mockTargets.mockResolvedValue(summaries(1));
    render(<App />);
    await advance(0);
    expect(statsText()).toEqual(["正常 1", "注意 0", "異常 0", "離線或等待 0"]);
  });

  it("shows — before the first list", async () => {
    mockTargets.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<App />);
    await advance(0);
    expect(statsText()).toEqual(["正常 —", "注意 —", "異常 —", "離線或等待 —"]);
  });
});

describe("總覽：後端請求失敗", () => {
  it("shows the banner, grays cards with 未知, shows — in the stats, keeps retrying and recovers", async () => {
    vi.setSystemTime(new Date("2026-11-06T02:32:15Z"));
    mockTargets.mockResolvedValue([target("a", "online", "green"), target("b", "online", "red")]);
    render(<App />);
    await advance(0);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(statsText()).toEqual(["正常 1", "注意 0", "異常 1", "離線或等待 0"]);

    mockTargets.mockRejectedValue(new TypeError("Failed to fetch"));
    await advance(INTERVAL_MS);
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toBe("無法連線到後端，將自動重試（最後成功 10:32:15）");
    expect(cards()).toHaveLength(2);
    for (const c of cards()) {
      expect(c.getAttribute("data-color")).toBe("gray");
      expect(text(c, ".card-state")).toBe("未知");
    }
    expect(statsText()).toEqual(["正常 —", "注意 —", "異常 —", "離線或等待 —"]);

    const calls = mockTargets.mock.calls.length;
    await advance(INTERVAL_MS);
    expect(mockTargets.mock.calls.length).toBeGreaterThan(calls);

    // 恢復後重新計數（清單已改變）
    mockTargets.mockResolvedValue([target("a", "online", "yellow"), target("b", "online", "red"), target("c", "offline", "gray")]);
    await advance(INTERVAL_MS);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(statsText()).toEqual(["正常 0", "注意 1", "異常 1", "離線或等待 1"]);
    expect(card("a").getAttribute("data-color")).toBe("yellow");
    expect(text(card("a"), ".card-state")).toBe("注意");
  });
});

describe("總覽：分頁", () => {
  const ids = () => cards().map((c) => c.getAttribute("data-target-id"));
  const thirty = summaries(30);

  it("shows 24 per page with the pager", async () => {
    mockTargets.mockResolvedValue(thirty);
    render(<App />);
    await advance(0);
    expect(ids()).toEqual(thirty.slice(0, 24).map((t) => t.id));
    const nav = pager()!;
    expect(nav.querySelector(".pager-status")?.textContent).toBe("第 1 / 2 頁（共 30 個服務）");
    expect(screen.queryByRole("link", { name: "上一頁" })).toBeNull();
    expect(screen.getByText("上一頁").getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByRole("link", { name: "下一頁" }).getAttribute("href")).toBe("#/?page=2");
  });

  it("shows the second page from the hash", async () => {
    setHash("#/?page=2");
    mockTargets.mockResolvedValue(thirty);
    render(<App />);
    await advance(0);
    expect(ids()).toEqual(thirty.slice(24).map((t) => t.id));
    expect(pager()!.querySelector(".pager-status")?.textContent).toBe("第 2 / 2 頁（共 30 個服務）");
    expect(screen.getByRole("link", { name: "上一頁" }).getAttribute("href")).toBe("#/");
    expect(screen.queryByRole("link", { name: "下一頁" })).toBeNull();
    expect(screen.getByText("下一頁").getAttribute("aria-disabled")).toBe("true");
  });

  it("moves between pages with the pager links and the browser history", async () => {
    mockTargets.mockResolvedValue(thirty);
    render(<App />);
    await advance(0);
    await follow(screen.getByRole("link", { name: "下一頁" }));
    expect(window.location.hash).toBe("#/?page=2");
    expect(ids()).toEqual(thirty.slice(24).map((t) => t.id));

    await goBack();
    expect(window.location.hash).toBe("#/");
    expect(ids()).toEqual(thirty.slice(0, 24).map((t) => t.id));

    await goForward();
    expect(ids()).toEqual(thirty.slice(24).map((t) => t.id));
  });

  it.each(["#/?page=0", "#/?page=-1", "#/?page=abc", "#/?page=1.5", "#/?page="])(
    "shows page 1 and replaces the hash with #/ for %s",
    async (hash) => {
      setHash(hash);
      const length = window.history.length;
      mockTargets.mockResolvedValue(thirty);
      render(<App />);
      await advance(0);
      expect(window.location.hash).toBe("#/");
      expect(window.history.length).toBe(length);
      expect(ids()).toEqual(thirty.slice(0, 24).map((t) => t.id));
    },
  );

  it("shows the last page and replaces the hash when the page is past the end", async () => {
    setHash("#/?page=5");
    const length = window.history.length;
    mockTargets.mockResolvedValue(thirty);
    render(<App />);
    await advance(0);
    expect(window.location.hash).toBe("#/?page=2");
    expect(window.history.length).toBe(length);
    expect(ids()).toEqual(thirty.slice(24).map((t) => t.id));
  });

  it("moves to the last page when targets are removed", async () => {
    setHash("#/?page=2");
    mockTargets.mockResolvedValue(thirty);
    render(<App />);
    await advance(0);
    const length = window.history.length;

    mockTargets.mockResolvedValue(thirty.slice(0, 20));
    await advance(INTERVAL_MS);
    expect(window.location.hash).toBe("#/");
    expect(window.history.length).toBe(length);
    expect(ids()).toEqual(thirty.slice(0, 20).map((t) => t.id));
    expect(pager()).toBeNull();
  });

  it("does not rewrite the page before the list is known", async () => {
    setHash("#/?page=2");
    mockTargets.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<App />);
    await advance(0);
    await advance(INTERVAL_MS);
    expect(window.location.hash).toBe("#/?page=2");

    mockTargets.mockResolvedValue(thirty);
    await advance(INTERVAL_MS);
    expect(ids()).toEqual(thirty.slice(24).map((t) => t.id));
  });

  it("hides the pager with 24 targets or fewer", async () => {
    mockTargets.mockResolvedValue(thirty.slice(0, 24));
    render(<App />);
    await advance(0);
    expect(cards()).toHaveLength(24);
    expect(pager()).toBeNull();

    mockTargets.mockResolvedValue(thirty.slice(0, 25));
    await advance(INTERVAL_MS);
    expect(pager()!.querySelector(".pager-status")?.textContent).toBe("第 1 / 2 頁（共 25 個服務）");
  });
});
