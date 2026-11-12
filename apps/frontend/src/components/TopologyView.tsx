import { useMemo } from "react";
import type { NodeView, TopologyView as Topology } from "../api/types";
import { canFlow, flowKeyframes } from "../lib/flow";
import { buildLaneTree, type LaneNode } from "../lib/layout";
import { LaneRow } from "./LaneRow";

export interface TopologyViewProps {
  topology: Topology;
  nodes: Record<string, NodeView>;
  online: boolean;
  backendError?: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/** 可能流動的 lane（含巢狀的）出現過的節點數，由小到大。 */
function flowCounts(lanes: LaneNode[]): number[] {
  const counts = new Set<number>();
  const walk = (lane: LaneNode) => {
    if (canFlow(lane)) counts.add(lane.nodes.length);
    for (const item of lane.nodes) item.children.forEach(walk);
  };
  lanes.forEach(walk);
  return [...counts].sort((a, b) => a - b);
}

/**
 * 由 topology 動態產生的架構圖；放在自己的容器內，過寬時在容器內水平捲動。
 * 光點流動的 keyframes 依畫面上出現的節點數產生（SPEC §7.1 視覺），內容只有整數 n 與計算出的數字；
 * 同樣的架構產生同樣的文字，輪詢時不變動。
 */
export function TopologyView({ topology, nodes, online, backendError, selectedId, onSelect }: TopologyViewProps) {
  const tree = useMemo(() => buildLaneTree(topology), [topology]);
  const keyframes = flowCounts(tree).map(flowKeyframes).join("\n");
  return (
    <div className="topology" aria-label="架構圖" role="group">
      {keyframes !== "" && <style>{keyframes}</style>}
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
