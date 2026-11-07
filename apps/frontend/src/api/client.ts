import type {
  ConfigResponse,
  TargetDetail,
  TargetSummary,
  Transition,
} from "./types";

/** 後端回應非 2xx；訊息不含回應內文。 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`API 請求失敗（HTTP ${status}）`);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * 單次 API 請求（含讀取本文）的逾時。後端只回傳記憶體內的資料，正常時遠低於此值；
 * 沒有逾時的話，後端或網路掛住時 usePolling 永遠等不到結果，畫面會一直留著舊燈號。
 */
export const REQUEST_TIMEOUT_MS = 10_000;

async function getJson<T>(path: string): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(path, { cache: "no-store", signal: ctrl.signal });
    if (!res.ok) {
      throw new ApiError(res.status);
    }
    return (await res.json()) as T;
  } catch (e) {
    if (ctrl.signal.aborted) {
      throw new Error("API 請求逾時");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export function fetchConfig(): Promise<ConfigResponse> {
  return getJson("/api/config");
}

export function fetchTargets(): Promise<TargetSummary[]> {
  return getJson("/api/targets");
}

export function fetchTarget(id: string): Promise<TargetDetail> {
  return getJson(`/api/targets/${encodeURIComponent(id)}`);
}

export function fetchTransitions(id: string, limit?: number): Promise<Transition[]> {
  const query = limit === undefined ? "" : `?limit=${encodeURIComponent(String(limit))}`;
  return getJson(`/api/targets/${encodeURIComponent(id)}/transitions${query}`);
}
