import { describe, expect, it } from "vitest";
import { formatMetric, formatRate } from "./format";

// SPEC §7.1「數值格式」：只改顯示，後端資料保留完整精度。
describe("formatMetric", () => {
  it.each([
    [7, "7"],
    [0, "0"],
    [-3, "-3"],
    [1200000, "1200000"],
  ])("shows integer %s as is", (value, text) => {
    expect(formatMetric(value)).toBe(text);
  });

  it.each([
    [3.998789, "4.00"],
    [0.023092, "0.02"],
    [12.5, "12.50"],
    [0.005, "0.01"],
    [2.675, "2.67"], // 2.675 的二進位值略小於 2.675
  ])("shows non-integer %s with 2 decimals", (value, text) => {
    expect(formatMetric(value)).toBe(text);
  });

  it.each([
    [-1.234, "-1.23"],
    [-0.006, "-0.01"],
    [-12.5, "-12.50"],
  ])("shows negative %s with 2 decimals", (value, text) => {
    expect(formatMetric(value)).toBe(text);
  });

  it.each([-0.001, -0.004999, -0])("never shows -0.00 (%s)", (value) => {
    expect(formatMetric(value)).toBe(Object.is(value, -0) ? "0" : "0.00");
  });

  it.each([
    ["cam-a", "cam-a"],
    ["", ""],
    ["3.14159", "3.14159"],
  ])("shows string %j as is", (value, text) => {
    expect(formatMetric(value)).toBe(text);
  });

  it.each([
    [true, "true"],
    [false, "false"],
  ])("shows boolean %s as is", (value, text) => {
    expect(formatMetric(value)).toBe(text);
  });

  it("shows null as —", () => {
    expect(formatMetric(null)).toBe("—");
  });
});

// 每秒次數一律小數 2 位（驗收裁定）：停住的節點是 0，要和其他節點的 4.00/s 一致。
describe("formatRate", () => {
  it.each([
    [0, "0.00/s"],
    [4, "4.00/s"],
    [-0, "0.00/s"],
  ])("shows integer %s with 2 decimals as N.NN/s", (value, text) => {
    expect(formatRate(value)).toBe(text);
  });

  it.each([
    [3.998789, "4.00/s"],
    [0.023092, "0.02/s"],
    [12.5, "12.50/s"],
  ])("shows non-integer %s as N.NN/s", (value, text) => {
    expect(formatRate(value)).toBe(text);
  });

  it.each([-0.001, -0.004999])("never shows -0.00/s (%s)", (value) => {
    expect(formatRate(value)).toBe("0.00/s");
  });

  it("keeps the metric panel format for integers", () => {
    expect(formatMetric(4)).toBe("4");
    expect(formatRate(4)).toBe("4.00/s");
  });
});
