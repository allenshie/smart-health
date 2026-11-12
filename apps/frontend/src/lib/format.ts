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
  const text = value.toFixed(2);
  return text === "-0.00" ? "0.00" : text;
}

/** 每秒次數：同指標格式，加上單位 /s。 */
export function formatRate(value: number): string {
  return `${formatMetric(value)}/s`;
}
