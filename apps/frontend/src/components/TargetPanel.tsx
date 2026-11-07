import { useCallback, useMemo, useState } from "react";
import { fetchTarget } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import { nodeLabels, topologyNodeIds } from "../lib/layout";
import { nodeStatus } from "../lib/status";
import { BackendError } from "./BackendError";
import { ConnectionBanner } from "./ConnectionBanner";
import { NodeDetail } from "./NodeDetail";
import { TopologyView } from "./TopologyView";

export interface TargetPanelProps {
  targetId: string;
  intervalMs: number;
  /** 上層已經顯示後端錯誤時不再重複顯示，燈號同樣轉灰。 */
  suppressError: boolean;
}

/**
 * 所選目標的架構圖與詳細面板。上層以 key={targetId} 掛載，切換目標時清空資料與選取。
 * 選取以節點 id 保存：更新後節點仍在 topology 中就保留，不在時關閉。
 */
export function TargetPanel({ targetId, intervalMs, suppressError }: TargetPanelProps) {
  const fetchDetail = useCallback(() => fetchTarget(targetId), [targetId]);
  const { data: detail, error, lastSuccessAt } = usePolling(fetchDetail, intervalMs);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const topology = detail?.topology ?? null;
  const ids = useMemo(() => (topology === null ? new Set<string>() : topologyNodeIds(topology)), [topology]);
  const labels = useMemo(() => (topology === null ? new Map<string, string>() : nodeLabels(topology)), [topology]);

  // 節點從 topology 消失時清除選取（render 期間調整 state，React 會立即重新 render）。
  if (detail !== null && selectedId !== null && !ids.has(selectedId)) {
    setSelectedId(null);
  }

  const toggle = useCallback((id: string) => setSelectedId((cur) => (cur === id ? null : id)), []);
  // 後端請求失敗時沒有人知道最後的顏色是否仍成立：保留架構，燈號一律轉灰（SPEC §7.1 第 3 點的精神）。
  const backendError = error !== null || suppressError;
  const online = detail?.connection === "online" && !backendError;

  return (
    <>
      {error !== null && !suppressError && <BackendError lastSuccessAt={lastSuccessAt} />}
      {detail === null ? (
        error === null && <p className="loading">載入中…</p>
      ) : (
        <>
          <ConnectionBanner connection={detail.connection} lastSuccessAt={detail.last_success_at} />
          {topology === null ? (
            <p className="empty">尚未取得此服務的架構</p>
          ) : (
            <TopologyView
              topology={topology}
              nodes={detail.nodes}
              online={online}
              backendError={backendError}
              selectedId={selectedId}
              onSelect={toggle}
            />
          )}
          {selectedId !== null && ids.has(selectedId) && (
            <NodeDetail
              id={selectedId}
              label={labels.get(selectedId) ?? selectedId}
              node={nodeStatus(detail.nodes, selectedId)}
            />
          )}
        </>
      )}
    </>
  );
}
