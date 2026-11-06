import type { NodeView } from "../api/types";
import { lampColor, stateText } from "../lib/status";

export interface NodeLampProps {
  id: string;
  label: string;
  /** 沒有該節點的狀態時為 undefined。 */
  node: NodeView | undefined;
  /** 目標不是 online 時一律顯示灰色。 */
  online: boolean;
  selected: boolean;
  onSelect: (id: string) => void;
}

/** 節點燈號：顏色加上狀態文字，色弱使用者也能分辨。 */
export function NodeLamp({ id, label, node, online, selected, onSelect }: NodeLampProps) {
  const color = lampColor(node, online);
  return (
    <button
      type="button"
      className={`lamp lamp-${color}`}
      data-color={color}
      data-node-id={id}
      aria-pressed={selected}
      onClick={() => onSelect(id)}
    >
      <span className="lamp-dot" aria-hidden="true" />
      <span className="lamp-label">{label}</span>{" "}
      <span className="lamp-state">{stateText(node)}</span>
    </button>
  );
}
