import type { Lane, TopologyView } from "../api/types";

/** 畫面上的一條 lane，節點依 topology 的順序排列。 */
export interface LaneNode {
  id: string;
  label: string;
  sequential: boolean;
  nodes: LaneItem[];
}

/** lane 裡的一個節點；children 是從這個節點分出的 lane。 */
export interface LaneItem {
  id: string;
  label: string;
  children: LaneNode[];
}

// 合成 lane 的 id 以底線開頭，契約的 id 格式（^[a-z]...）不允許，因此不會和真實 lane 衝突。
const ORPHAN_LANE_ID = "__other_nodes__";
const ORPHAN_LANE_LABEL = "其他節點";

/** 節點 id 對應 label；同一 id 出現多次時取第一個。 */
export function nodeLabels(topology: TopologyView): Map<string, string> {
  const labels = new Map<string, string>();
  for (const node of topology.nodes) {
    if (!labels.has(node.id)) labels.set(node.id, node.label);
  }
  return labels;
}

/** topology 中出現過的所有節點 id（lane 列出的與 nodes 列出的）。 */
export function topologyNodeIds(topology: TopologyView): Set<string> {
  const ids = new Set(topology.nodes.map((n) => n.id));
  for (const lane of topology.lanes) {
    for (const id of lane.nodes) ids.add(id);
  }
  return ids;
}

/**
 * 把 topology 的 lanes 轉成巢狀結構。被監控服務的輸入不一定正確，因此：
 * - parent 不在任何 lane 裡，或 parent 形成循環的 lane 當成頂層 lane。
 * - 每條 lane 只出現一次；parent 節點出現在多條 lane 時，掛在走訪時第一次遇到的位置。
 * - 沒被任何 lane 列出的節點放進最後一條「其他節點」lane。
 * - lane 列出但 nodes 沒有的 id 照樣顯示，label 用 id。
 * 以 lane 在陣列中的位置辨識 lane，重複的 lane id 也不會互相覆蓋。
 */
export function buildLaneTree(topology: TopologyView): LaneNode[] {
  const lanes = topology.lanes;
  const labels = nodeLabels(topology);
  const placed = new Set<number>();
  const topLevel: Array<{ index: number; lane: LaneNode }> = [];

  const nodesInLanes = new Set(lanes.flatMap((l) => l.nodes));

  const buildLane = (index: number): LaneNode => {
    const lane: Lane = lanes[index];
    return {
      id: lane.id,
      label: lane.label,
      sequential: lane.sequential,
      nodes: lane.nodes.map((id) => ({
        id,
        label: labels.get(id) ?? id,
        children: claimChildren(id),
      })),
    };
  };

  // 取走所有 parent 等於 nodeId 且尚未放置的 lane，依原順序。先標記再遞迴，避免循環。
  const claimChildren = (nodeId: string): LaneNode[] => {
    const indexes: number[] = [];
    lanes.forEach((lane, i) => {
      if (!placed.has(i) && lane.parent === nodeId) {
        placed.add(i);
        indexes.push(i);
      }
    });
    return indexes.map(buildLane);
  };

  const placeTopLevel = (index: number) => {
    placed.add(index);
    topLevel.push({ index, lane: buildLane(index) });
  };

  lanes.forEach((lane, i) => {
    if (!placed.has(i) && (lane.parent === null || !nodesInLanes.has(lane.parent))) {
      placeTopLevel(i);
    }
  });
  // 剩下的 lane 都在循環裡：依原順序取第一條當頂層，其餘會在走訪時掛上去。
  lanes.forEach((_lane, i) => {
    if (!placed.has(i)) placeTopLevel(i);
  });

  const tree = topLevel.sort((a, b) => a.index - b.index).map((t) => t.lane);

  const orphans = [...labels.keys()].filter((id) => !nodesInLanes.has(id));
  if (orphans.length > 0) {
    tree.push({
      id: ORPHAN_LANE_ID,
      label: ORPHAN_LANE_LABEL,
      sequential: false,
      nodes: orphans.map((id) => ({ id, label: labels.get(id) ?? id, children: [] })),
    });
  }
  return tree;
}
