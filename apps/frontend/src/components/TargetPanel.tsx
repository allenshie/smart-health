import { useCallback, useMemo, useState } from "react";
import type { TargetDetail } from "../api/types";
import { nodeLabels, topologyNodeIds } from "../lib/layout";
import { nodeStatus } from "../lib/status";
import { ConnectionBanner } from "./ConnectionBanner";
import { NodeDetail } from "./NodeDetail";
import { TopologyView } from "./TopologyView";

export interface TargetPanelProps {
  detail: TargetDetail;
  /** 後端請求失敗：保留架構，燈號一律轉灰並顯示「未知」。 */
  backendError: boolean;
}

/**
 * 服務的架構圖與詳細面板。上層以 key 區分服務，切換服務時清空選取。
 * 選取以節點 id 保存：更新後節點仍在 topology 中就保留，不在時關閉。
 */
export function TargetPanel({ detail, backendError }: TargetPanelProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const topology = detail.topology;
  const ids = useMemo(() => (topology === null ? new Set<string>() : topologyNodeIds(topology)), [topology]);
  const labels = useMemo(() => (topology === null ? new Map<string, string>() : nodeLabels(topology)), [topology]);

  // 節點從 topology 消失時清除選取（render 期間調整 state，React 會立即重新 render）。
  if (selectedId !== null && !ids.has(selectedId)) {
    setSelectedId(null);
  }

  const toggle = useCallback((id: string) => setSelectedId((cur) => (cur === id ? null : id)), []);
  // 後端請求失敗時沒有人知道最後的顏色是否仍成立：保留架構，燈號一律轉灰（SPEC §7.1 第 5 點）。
  const online = detail.connection === "online" && !backendError;

  return (
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
  );
}
