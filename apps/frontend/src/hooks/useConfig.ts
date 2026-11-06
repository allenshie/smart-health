import { useEffect, useState } from "react";
import { fetchConfig } from "../api/client";
import type { ConfigResponse } from "../api/types";

export const CONFIG_RETRY_MS = 3000;

export interface ConfigState {
  config: ConfigResponse | null;
  error: Error | null;
}

/** 取得 /api/config：成功後不再呼叫；失敗時每 CONFIG_RETRY_MS 重試，直到成功。 */
export function useConfig(): ConfigState {
  const [state, setState] = useState<ConfigState>({ config: null, error: null });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const attempt = async () => {
      try {
        const config = await fetchConfig();
        if (!cancelled) setState({ config, error: null });
      } catch (e) {
        if (cancelled) return;
        setState({ config: null, error: e instanceof Error ? e : new Error(String(e)) });
        timer = setTimeout(attempt, CONFIG_RETRY_MS);
      }
    };

    void attempt();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, []);

  return state;
}
