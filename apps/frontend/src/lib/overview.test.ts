import { describe, expect, it } from "vitest";
import type { Color, Connection, TargetSummary } from "../api/types";
import { PAGE_SIZE, colorCounts, paginate, summaryColor, summaryText } from "./overview";

function summary(connection: Connection, summary_color: Color, id = "t"): TargetSummary {
  return { id, name: id, connection, summary_color, last_success_at: null };
}

// SPEC §7.1 總覽的狀態文字表，每一列一個案例。
describe("summaryText", () => {
  it.each([
    ["online", "green", "正常"],
    ["online", "yellow", "注意"],
    ["online", "red", "異常"],
    ["online", "gray", "等待中"],
  ] as const)("%s + %s → %s", (connection, color, text) => {
    expect(summaryText(summary(connection, color))).toBe(text);
  });

  it.each([
    ["unknown", "尚未取得"],
    ["offline", "無法連線"],
    ["stale", "資料過舊"],
    ["incompatible", "版本不相容"],
    ["invalid_response", "回應無效"],
  ] as const)("%s → %s regardless of summary_color", (connection, text) => {
    for (const color of ["green", "yellow", "red", "gray"] as const) {
      expect(summaryText(summary(connection, color))).toBe(text);
    }
  });

  it("shows 未知 on backend error", () => {
    expect(summaryText(summary("online", "green"), true)).toBe("未知");
    expect(summaryText(summary("offline", "gray"), true)).toBe("未知");
  });

  it("falls back to 未知 for unexpected values", () => {
    expect(summaryText({ ...summary("online", "green"), summary_color: "purple" as Color })).toBe("未知");
    expect(summaryText({ ...summary("online", "green"), connection: "weird" as Connection })).toBe("未知");
  });
});

describe("summaryColor", () => {
  it("uses summary_color as is", () => {
    for (const color of ["green", "yellow", "red", "gray"] as const) {
      expect(summaryColor(summary("online", color))).toBe(color);
    }
  });

  it("is gray on backend error or for an unexpected color", () => {
    expect(summaryColor(summary("online", "green"), true)).toBe("gray");
    expect(summaryColor({ ...summary("online", "green"), summary_color: "purple" as Color })).toBe("gray");
  });
});

describe("colorCounts", () => {
  it("counts every target by summary_color, including zeros", () => {
    const targets = [
      summary("online", "green", "a"),
      summary("online", "green", "b"),
      summary("online", "yellow", "c"),
      summary("offline", "gray", "d"),
      summary("online", "gray", "e"),
    ];
    expect(colorCounts(targets)).toEqual({ green: 2, yellow: 1, red: 0, gray: 2 });
  });

  it("counts an unexpected color as gray", () => {
    expect(colorCounts([{ ...summary("online", "green"), summary_color: "purple" as Color }])).toEqual({
      green: 0,
      yellow: 0,
      red: 0,
      gray: 1,
    });
  });
});

describe("paginate", () => {
  const items = Array.from({ length: 30 }, (_v, i) => i);

  it("has 24 items per page", () => {
    expect(PAGE_SIZE).toBe(24);
    expect(paginate(items, 1)).toEqual({ page: 1, pageCount: 2, items: items.slice(0, 24) });
    expect(paginate(items, 2)).toEqual({ page: 2, pageCount: 2, items: items.slice(24) });
  });

  it("clamps a page past the end to the last page", () => {
    expect(paginate(items, 5)).toEqual({ page: 2, pageCount: 2, items: items.slice(24) });
    expect(paginate(items.slice(0, 24), 2)).toEqual({ page: 1, pageCount: 1, items: items.slice(0, 24) });
  });

  it("has one page when empty", () => {
    expect(paginate([], 3)).toEqual({ page: 1, pageCount: 1, items: [] });
  });

  it("keeps exactly 48 items on 2 pages", () => {
    const many = Array.from({ length: 48 }, (_v, i) => i);
    expect(paginate(many, 3)).toEqual({ page: 2, pageCount: 2, items: many.slice(24) });
  });
});
