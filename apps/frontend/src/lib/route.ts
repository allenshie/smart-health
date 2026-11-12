/** 網址的 hash 與畫面的對應（SPEC §7.1）。 */

/** SPEC §4.1 的 id 格式；target id 也套用。 */
export const ID_PATTERN = /^[a-z][a-z0-9_-]*$/;

const PAGE_PATTERN = /^[1-9][0-9]*$/;
const TARGET_PREFIX = "/targets/";

export type Route =
  | { kind: "overview"; page: number }
  /** valid 為 false：id 解碼失敗或不符合格式，視為找不到服務。 */
  | { kind: "target"; id: string; valid: boolean };

export interface ParsedRoute {
  route: Route;
  /** 需要以 replace 改寫成的 hash；不需要時為 null。 */
  rewrite: string | null;
}

const HOME = "#/";

export function overviewHash(page: number): string {
  return page <= 1 ? HOME : `${HOME}?page=${page}`;
}

export function targetHash(id: string): string {
  return `#${TARGET_PREFIX}${encodeURIComponent(id)}`;
}

function overview(page: number, rewrite: string | null = null): ParsedRoute {
  return { route: { kind: "overview", page }, rewrite };
}

function decode(text: string): string | null {
  try {
    return decodeURIComponent(text);
  } catch {
    return null;
  }
}

/**
 * 解析 location.hash：
 * - 空白、`#/`：總覽第 1 頁；`#/?page=N`：只看 page，不是正整數時第 1 頁並改寫成 `#/`。
 * - `#/targets/<id>`：其後全部內容解碼後當作 id；解碼失敗時保留原文，兩者不合格式都不改寫。
 * - 其他：總覽第 1 頁並改寫成 `#/`。
 */
export function parseHash(hash: string): ParsedRoute {
  const text = hash.startsWith("#") ? hash.slice(1) : hash;
  if (text === "") return overview(1);

  if (text.startsWith(TARGET_PREFIX)) {
    const raw = text.slice(TARGET_PREFIX.length);
    const decoded = decode(raw);
    const id = decoded ?? raw;
    return { route: { kind: "target", id, valid: decoded !== null && ID_PATTERN.test(id) }, rewrite: null };
  }

  const q = text.indexOf("?");
  const path = q < 0 ? text : text.slice(0, q);
  if (path !== "/") return overview(1, HOME);

  const page = new URLSearchParams(q < 0 ? "" : text.slice(q + 1)).get("page");
  if (page === null) return overview(1);
  if (!PAGE_PATTERN.test(page)) return overview(1, HOME);
  return overview(Number(page));
}
