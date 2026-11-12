import { useState } from "react";
import { BackendError } from "./components/BackendError";
import { OverviewScreen } from "./components/OverviewScreen";
import { TargetScreen } from "./components/TargetScreen";
import { useConfig } from "./hooks/useConfig";
import { useHashRoute } from "./hooks/useHashRoute";
import { overviewHash } from "./lib/route";

/** 先取得 /api/config，取得之前不輪詢。 */
export default function App() {
  const { config, error } = useConfig();
  if (config === null) {
    return (
      <main className="app">
        {error !== null && <BackendError lastSuccessAt={null} />}
        <p className="loading">載入中…</p>
      </main>
    );
  }
  return <Screens intervalS={config.poll_interval_s} />;
}

/**
 * 依網址 hash 顯示總覽或服務畫面（SPEC §7.1）。記住這次瀏覽中最後看過的總覽頁，
 * 作為服務畫面「回到總覽」的目的地；直接開啟服務網址時為第 1 頁。
 */
function Screens({ intervalS }: { intervalS: number }) {
  const { route, replace } = useHashRoute();
  const [lastPage, setLastPage] = useState(1);
  // 總覽頁碼改變時記下（render 期間調整 state，React 會立即重新 render）。
  if (route.kind === "overview" && route.page !== lastPage) {
    setLastPage(route.page);
  }

  return (
    <main className="app">
      {route.kind === "overview" ? (
        <OverviewScreen intervalS={intervalS} page={route.page} replace={replace} />
      ) : (
        <TargetScreen
          key={route.id}
          id={route.id}
          valid={route.valid}
          intervalS={intervalS}
          backHref={overviewHash(lastPage)}
        />
      )}
    </main>
  );
}
