import { Fragment } from "react";
import type { NodeView } from "../api/types";
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
 */
export function LaneRow({ lane, nodes, online, backendError, selectedId, onSelect, parentLabel }: LaneRowProps) {
  const branches = lane.nodes.flatMap((item, i) =>
    item.children.map((child, j) => ({ key: `${i}-${j}-${child.id}`, child, parentLabel: item.label })),
  );
  return (
    <div className="lane" data-lane-id={lane.id}>
      <div className="lane-row">
        <div className="lane-label">
          <span className="lane-name">{lane.label}</span>
          {parentLabel !== undefined && <span className="lane-parent">{`從 ${parentLabel} 分出`}</span>}
        </div>
        <div className="lane-nodes">
          {lane.nodes.map((item, i) => (
            <Fragment key={`${i}-${item.id}`}>
              {lane.sequential && i > 0 && (
                <span className="lane-arrow" aria-hidden="true">
                  →
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
