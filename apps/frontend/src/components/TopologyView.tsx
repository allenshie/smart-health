import { useMemo } from "react";
import type { NodeView, TopologyView as Topology } from "../api/types";
import { buildLaneTree } from "../lib/layout";
import { LaneRow } from "./LaneRow";

export interface TopologyViewProps {
  topology: Topology;
  nodes: Record<string, NodeView>;
  online: boolean;
  backendError?: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/** 由 topology 動態產生的架構圖；放在自己的容器內，過寬時在容器內水平捲動。 */
export function TopologyView({ topology, nodes, online, backendError, selectedId, onSelect }: TopologyViewProps) {
  const tree = useMemo(() => buildLaneTree(topology), [topology]);
  return (
    <div className="topology" aria-label="架構圖" role="group">
      {tree.map((lane, i) => (
        <LaneRow
          key={`${i}-${lane.id}`}
          lane={lane}
          nodes={nodes}
          online={online}
          backendError={backendError}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
