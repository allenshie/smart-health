import type { Color, NodeView } from "../api/types";

const COLORS: readonly Color[] = ["green", "yellow", "red", "gray"];

/** 燈號顏色取後端給的值；不認得的值、沒有狀態或目標不在線時一律灰色。 */
export function lampColor(node: NodeView | undefined, online: boolean): Color {
  if (!online || node === undefined) return "gray";
  return COLORS.includes(node.color) ? node.color : "gray";
}

/** 狀態文字直接用 state 代碼；null 或沒有狀態時為「未知」。 */
export function stateText(node: NodeView | undefined): string {
  return node?.state ?? "未知";
}

/** 取節點狀態；只看自身屬性，節點 id 為 "constructor" 等名稱時也不會取到原型上的值。 */
export function nodeStatus(nodes: Record<string, NodeView>, id: string): NodeView | undefined {
  return Object.prototype.hasOwnProperty.call(nodes, id) ? nodes[id] : undefined;
}
