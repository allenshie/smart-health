import type { CSSProperties } from "react";
import type { NodeView } from "../api/types";
import { formatRate } from "../lib/format";
import { lampColor, stateText } from "../lib/status";

export interface NodeLampProps {
  id: string;
  label: string;
  /** 沒有該節點的狀態時為 undefined。 */
  node: NodeView | undefined;
  /** 目標不是 online 時一律顯示灰色。 */
  online: boolean;
  /** 後端請求失敗：顏色與文字都不可信，狀態文字顯示「未知」（顏色不能是唯一線索）。 */
  backendError?: boolean;
  selected: boolean;
  onSelect: (id: string) => void;
  /** 光點流動時這個燈號的延遲（CSS 時間，例如 "1.28s"）；不在可能流動的 lane 時不給。 */
  flowDelay?: string;
}

/** 每秒次數的標準指標名稱（SPEC §7.1）：smart-workflow 為每個節點產生，其他整合方式提供同名指標也會顯示。 */
export const RATE_METRIC = "rate_per_s";

/** 目標 online 且後端請求成功時，取節點的每秒次數；不是數字時不顯示。 */
function rateOf(node: NodeView | undefined, online: boolean, backendError: boolean): number | null {
  if (!online || backendError || node === undefined) return null;
  const value = Object.prototype.hasOwnProperty.call(node.metrics, RATE_METRIC) ? node.metrics[RATE_METRIC] : null;
  return typeof value === "number" ? value : null;
}

/** 節點燈號：顏色加上狀態文字，色弱使用者也能分辨；有每秒次數時顯示在狀態文字下方。 */
export function NodeLamp({ id, label, node, online, backendError = false, selected, onSelect, flowDelay }: NodeLampProps) {
  const color = lampColor(node, online);
  const rate = rateOf(node, online, backendError);
  return (
    <button
      type="button"
      className={`lamp lamp-${color}`}
      data-color={color}
      data-node-id={id}
      aria-pressed={selected}
      onClick={() => onSelect(id)}
      style={flowDelay === undefined ? undefined : ({ "--flow-delay": flowDelay } as CSSProperties)}
    >
      <span className="lamp-dot" aria-hidden="true" />
      <span className="lamp-label">{label}</span>{" "}
      <span className="lamp-status">
        <span className="lamp-state">{backendError ? stateText(undefined) : stateText(node)}</span>
        {rate !== null && (
          <>
            {" "}
            <span className="lamp-rate">{formatRate(rate)}</span>
          </>
        )}
      </span>
    </button>
  );
}
