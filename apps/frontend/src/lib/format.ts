import type { MetricValue } from "../api/types";

export const EMPTY = "—";

/**
 * 指標值的顯示文字（SPEC §7.1「數值格式」）：整數原樣，非整數小數 2 位（四捨五入），
 * 不顯示 -0.00；字串、布林原樣；null 為「—」。只改顯示，不改資料。
 */
export function formatMetric(value: MetricValue): string {
  if (value === null) return EMPTY;
  if (typeof value !== "number") return String(value);
  if (Number.isInteger(value) || !Number.isFinite(value)) return String(value);
  return twoDecimals(value);
}

/**
 * 每秒次數：整數也一律小數 2 位，加上單位 /s（例如 0 → 0.00/s、4 → 4.00/s）。
 * rate_per_s 是 count/elapsed，實務上只有停住的節點會是整數 0，要和其他節點的 4.00/s 一致。
 */
export function formatRate(value: number): string {
  return `${Number.isFinite(value) ? twoDecimals(value) : String(value)}/s`;
}

/** 小數 2 位（四捨五入），不顯示 -0.00。 */
function twoDecimals(value: number): string {
  const text = value.toFixed(2);
  return text === "-0.00" ? "0.00" : text;
}
