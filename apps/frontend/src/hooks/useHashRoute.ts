import { useCallback, useEffect, useMemo, useState } from "react";
import { parseHash, type Route } from "../lib/route";

export interface HashRoute {
  route: Route;
  /** 以 replace 改寫 hash（不新增瀏覽紀錄）並更新畫面。 */
  replace: (hash: string) => void;
}

/**
 * 目前網址 hash 對應的畫面（SPEC §7.1）。上一頁、下一頁、連結與手動輸入都會觸發 hashchange；
 * 需要改寫的 hash（例如不合法的頁碼）一律用 history.replaceState，不新增瀏覽紀錄。
 */
export function useHashRoute(): HashRoute {
  const [hash, setHash] = useState(() => window.location.hash);
  const parsed = useMemo(() => parseHash(hash), [hash]);

  const replace = useCallback((next: string) => {
    window.history.replaceState(window.history.state, "", next);
    setHash(window.location.hash);
  }, []);

  useEffect(() => {
    const sync = () => setHash(window.location.hash);
    window.addEventListener("hashchange", sync);
    sync(); // 掛載前就已改變的 hash
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const { rewrite } = parsed;
  useEffect(() => {
    if (rewrite !== null) replace(rewrite);
  }, [rewrite, replace]);

  return { route: parsed.route, replace };
}
