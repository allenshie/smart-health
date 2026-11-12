import type { Color, Connection, TargetSummary } from "../api/types";

/** 總覽每頁的服務數（SPEC §7.1）。 */
export const PAGE_SIZE = 24;

export const COLORS: readonly Color[] = ["green", "yellow", "red", "gray"];

const UNKNOWN = "未知";

const ONLINE_TEXT: Record<Color, string> = {
  green: "正常",
  yellow: "注意",
  red: "異常",
  gray: "等待中",
};

const CONNECTION_TEXT: Record<Exclude<Connection, "online">, string> = {
  unknown: "尚未取得",
  offline: "無法連線",
  stale: "資料過舊",
  incompatible: "版本不相容",
  invalid_response: "回應無效",
};

function own<T extends object>(table: T, key: string): key is Extract<keyof T, string> {
  return Object.prototype.hasOwnProperty.call(table, key);
}

/** 總體燈號顏色：取 summary_color；後端請求失敗或不認得的值時為灰色。 */
export function summaryColor(target: TargetSummary, backendError = false): Color {
  if (backendError) return "gray";
  return COLORS.includes(target.summary_color) ? target.summary_color : "gray";
}

/** 總體狀態文字（SPEC §7.1 的表）；後端請求失敗或不認得的值時為「未知」。 */
export function summaryText(target: TargetSummary, backendError = false): string {
  if (backendError) return UNKNOWN;
  if (target.connection === "online") {
    return own(ONLINE_TEXT, target.summary_color) ? ONLINE_TEXT[target.summary_color] : UNKNOWN;
  }
  return own(CONNECTION_TEXT, target.connection) ? CONNECTION_TEXT[target.connection] : UNKNOWN;
}

/** 依 summary_color 計數全部目標；不認得的顏色算灰色。 */
export function colorCounts(targets: readonly TargetSummary[]): Record<Color, number> {
  const counts: Record<Color, number> = { green: 0, yellow: 0, red: 0, gray: 0 };
  for (const t of targets) counts[summaryColor(t)] += 1;
  return counts;
}

export interface Paged<T> {
  /** 實際顯示的頁碼：超過最後一頁時為最後一頁。 */
  page: number;
  pageCount: number;
  items: T[];
}

/** 取第 page 頁；沒有項目時只有第 1 頁。 */
export function paginate<T>(items: readonly T[], page: number): Paged<T> {
  const pageCount = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const shown = Math.min(Math.max(1, page), pageCount);
  const start = (shown - 1) * PAGE_SIZE;
  return { page: shown, pageCount, items: items.slice(start, start + PAGE_SIZE) };
}
