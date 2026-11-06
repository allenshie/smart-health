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

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) {
    throw new ApiError(res.status);
  }
  return (await res.json()) as T;
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
