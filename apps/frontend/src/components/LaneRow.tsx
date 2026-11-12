import { Fragment, type CSSProperties } from "react";
import type { NodeView } from "../api/types";
import { arrowDelayS, canFlow, flowCycleS, flowNames, laneFlowing, nodeDelayS, seconds } from "../lib/flow";
import type { LaneNode } from "../lib/layout";
import { nodeStatus } from "../lib/status";
import { NodeLamp } from "./NodeLamp";

export interface LaneRowProps {
  lane: LaneNode;
  nodes: Record<string, NodeView>;
  online: boolean;
  backendError?: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** 子 lane 的 parent 節點 label；頂層 lane 不給。 */
  parentLabel?: string;
}

/**
 * 一條 lane：左側 label，右側依序排列燈號。sequential lane 的相鄰節點之間畫箭頭。
 * 從節點分出的子 lane 顯示在下方並縮排。同一節點可能出現多次，key 一律帶位置。
 *
 * 光點流動（SPEC §7.1 視覺）：可能流動的 lane 一律帶一輪的時間與 keyframes 名稱（CSS 變數），
 * 每個燈號與箭頭帶自己的延遲；是否流動只由 data-flowing 切換，動畫本身全由 CSS 處理。
 * 元素的 key 不隨資料改變，輪詢時不重新掛載，動畫不會重新開始。
 */
export function LaneRow({ lane, nodes, online, backendError, selectedId, onSelect, parentLabel }: LaneRowProps) {
  const branches = lane.nodes.flatMap((item, i) =>
    item.children.map((child, j) => ({ key: `${i}-${j}-${child.id}`, child, parentLabel: item.label })),
  );
  const flowable = canFlow(lane);
  const flowing = laneFlowing(lane, nodes, online);
  return (
    <div
      className="lane"
      data-lane-id={lane.id}
      data-flowing={flowing ? "true" : "false"}
      style={flowable ? laneFlowStyle(lane.nodes.length) : undefined}
    >
      <div className="lane-row">
        <div className="lane-label">
          <span className="lane-name">{lane.label}</span>
          {parentLabel !== undefined && <span className="lane-parent">{`從 ${parentLabel} 分出`}</span>}
        </div>
        <div className="lane-nodes">
          {lane.nodes.map((item, i) => (
            <Fragment key={`${i}-${item.id}`}>
              {lane.sequential && i > 0 && (
                <span className="lane-arrow" aria-hidden="true" style={delayStyle(arrowDelayS(i))}>
                  <span className="lane-flow-dot" />
                </span>
              )}
              <NodeLamp
                id={item.id}
                label={item.label}
                node={nodeStatus(nodes, item.id)}
                online={online}
                backendError={backendError}
                selected={selectedId === item.id}
                onSelect={onSelect}
                flowDelay={flowable ? seconds(nodeDelayS(i)) : undefined}
              />
            </Fragment>
          ))}
        </div>
      </div>
      {branches.length > 0 && (
        <div className="lane-children">
          {branches.map((b) => (
            <LaneRow
              key={b.key}
              lane={b.child}
              nodes={nodes}
              online={online}
              backendError={backendError}
              selectedId={selectedId}
              onSelect={onSelect}
              parentLabel={b.parentLabel}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** lane 的 CSS 變數：一輪的時間與 n 個節點的 keyframes 名稱（keyframes 由 TopologyView 輸出）。 */
function laneFlowStyle(n: number): CSSProperties {
  const names = flowNames(n);
  return {
    "--flow-cycle": seconds(flowCycleS(n)),
    "--flow-node": names.node,
    "--flow-node-pressed": names.pressed,
    "--flow-dot": names.dot,
    "--flow-arrow": names.arrow,
  } as CSSProperties;
}

function delayStyle(delayS: number): CSSProperties {
  return { "--flow-delay": seconds(delayS) } as CSSProperties;
}
