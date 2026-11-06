import { useState } from "react";
import { fetchTargets } from "./api/client";
import type { TargetSummary } from "./api/types";
import { BackendError } from "./components/BackendError";
import { TargetPanel } from "./components/TargetPanel";
import { TargetSelector } from "./components/TargetSelector";
import { useConfig } from "./hooks/useConfig";
import { usePolling } from "./hooks/usePolling";
import { formatTime } from "./lib/time";

/** 先取得 /api/config，取得之前不輪詢目標。 */
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
  return <Dashboard intervalS={config.poll_interval_s} />;
}

/** 所選目標仍在清單中就保留，否則改選第一個。 */
function resolveTarget(targets: TargetSummary[], chosen: string | null): TargetSummary | undefined {
  return targets.find((t) => t.id === chosen) ?? targets[0];
}

function Dashboard({ intervalS }: { intervalS: number }) {
  const intervalMs = intervalS * 1000;
  const { data: targets, error, lastSuccessAt } = usePolling(fetchTargets, intervalMs);
  const [chosenId, setChosenId] = useState<string | null>(null);
  const target = targets === null ? undefined : resolveTarget(targets, chosenId);
  // 初始選擇或 fallback 時，把實際顯示的目標同步回 state，之後清單順序改變或原目標重新出現都不會跳動。
  // （render 期間調整 state，React 會立即重新 render。）
  if (target !== undefined && target.id !== chosenId) {
    setChosenId(target.id);
  }
  const lastUpdate =
    target?.last_success_at == null ? "尚未取得" : formatTime(target.last_success_at);

  return (
    <main className="app">
      <header className="app-header">
        {targets !== null && target !== undefined && (
          <TargetSelector targets={targets} selectedId={target.id} onChange={setChosenId} />
        )}
        <span className="last-update">{`最後更新 ${lastUpdate}（每 ${intervalS} 秒）`}</span>
      </header>
      {error !== null && <BackendError lastSuccessAt={lastSuccessAt} />}
      {targets === null && error === null && <p className="loading">載入中…</p>}
      {targets !== null && targets.length === 0 && <p className="empty">尚未設定任何服務</p>}
      {target !== undefined && (
        <TargetPanel
          key={target.id}
          targetId={target.id}
          intervalMs={intervalMs}
          suppressError={error !== null}
        />
      )}
    </main>
  );
}
