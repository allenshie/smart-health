import { useEffect, useRef, useState } from "react";

export interface PollingResult<T> {
  data: T | null;
  error: Error | null;
  lastSuccessAt: Date | null;
}

/**
 * 輪詢 fn：掛載時立刻呼叫，之後在上一次呼叫結束後等待 intervalMs 再呼叫。
 * 失敗時保留上一次的 data 與 lastSuccessAt，並持續重試。
 * intervalMs 不是有限正數時只呼叫第一次。
 */
export function usePolling<T>(fn: () => Promise<T>, intervalMs: number): PollingResult<T> {
  const [state, setState] = useState<PollingResult<T>>({
    data: null,
    error: null,
    lastSuccessAt: null,
  });
  const fnRef = useRef(fn);

  useEffect(() => {
    fnRef.current = fn;
  });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const repeat = Number.isFinite(intervalMs) && intervalMs > 0;

    const tick = async () => {
      try {
        const data = await fnRef.current();
        if (cancelled) return;
        setState({ data, error: null, lastSuccessAt: new Date() });
      } catch (e) {
        if (cancelled) return;
        const error = e instanceof Error ? e : new Error(String(e));
        setState((prev) => ({ ...prev, error }));
      }
      if (!cancelled && repeat) {
        timer = setTimeout(tick, intervalMs);
      }
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [intervalMs]);

  return state;
}
