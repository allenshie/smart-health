import type { NodeView } from "../api/types";
import type { LaneNode } from "./layout";
import { lampColor, nodeStatus } from "./status";

/**
 * 主迴圈的光點流動（SPEC §7.1 視覺）。一格 0.32 秒，依序為「節點 1、箭頭 1、節點 2……最後一個節點」，
 * 再停頓 3 格。速度固定，不和 rate_per_s 連動；光點是裝飾，不代表實際的畫面或事件。
 */
export const FLOW_STEP_S = 0.32;
const PAUSE_STEPS = 3;
/** 節點經過時約 0.1 秒最亮、約 0.38 秒回到原樣。 */
const NODE_PEAK_S = 0.1;
const NODE_END_S = 0.38;
/** 箭頭的光點在一格內淡入淡出：前 20% 淡入、後 20% 淡出。 */
const ARROW_FADE = 0.2;
/** 箭頭寬 40px、光點 8px：光點由左端移到右端。 */
const ARROW_TRAVEL_PX = 32;

/** n 個節點一輪的秒數：(2n − 1) 格加上停頓 3 格，即 (2n + 2) × 0.32。 */
export function flowCycleS(n: number): number {
  return (2 * n - 1 + PAUSE_STEPS) * FLOW_STEP_S;
}

/** 第 index 個節點（從 0 起算）的延遲。 */
export function nodeDelayS(index: number): number {
  return 2 * index * FLOW_STEP_S;
}

/** 第 index 個節點（從 1 起算）前面那個箭頭的延遲。 */
export function arrowDelayS(index: number): number {
  return (2 * index - 1) * FLOW_STEP_S;
}

/** CSS 的秒數，固定小數 2 位。 */
export function seconds(value: number): string {
  return `${value.toFixed(2)}s`;
}

/** 可能流動的 lane：sequential 且有 2 個以上節點。 */
export function canFlow(lane: LaneNode): boolean {
  return lane.sequential && lane.nodes.length >= 2;
}

/**
 * 這條 lane 是否流動：可能流動，而且自己的每個節點都是綠（子 lane 各自判斷）。
 * online 為 false（目標不是 online 或後端請求失敗）時燈號一律灰，所以不流動。
 */
export function laneFlowing(lane: LaneNode, nodes: Record<string, NodeView>, online: boolean): boolean {
  return canFlow(lane) && lane.nodes.every((item) => lampColor(nodeStatus(nodes, item.id), online) === "green");
}

export interface FlowNames {
  /** 節點燈號外框 */
  node: string;
  /** 選取中的節點燈號外框：光暈裡保留選取框 */
  pressed: string;
  /** 節點的圓點 */
  dot: string;
  /** 箭頭上的光點 */
  arrow: string;
}

export function flowNames(n: number): FlowNames {
  return {
    node: `flow-node-n${n}`,
    pressed: `flow-node-pressed-n${n}`,
    dot: `flow-dot-n${n}`,
    arrow: `flow-arrow-n${n}`,
  };
}

const NODE_REST = "0 0 0 0 rgba(52,199,89,0), 0 0 0 0 rgba(52,199,89,0)";
const NODE_PEAK = "0 0 0 4px rgba(52,199,89,.12), 0 0 16px 2px rgba(52,199,89,.30)";
const PRESSED_RING = "0 0 0 1px var(--fg)";
const DOT_REST = "0 0 5px 1px rgba(52,199,89,.42)";
const DOT_PEAK = "0 0 12px 4px rgba(52,199,89,.75)";

function shadowKeyframes(name: string, rest: string, peak: string, cycle: number): string {
  return (
    `@keyframes ${name} { 0% { box-shadow: ${rest}; } ${percent(NODE_PEAK_S, cycle)} { box-shadow: ${peak}; } ` +
    `${percent(NODE_END_S, cycle)} { box-shadow: ${rest}; } 100% { box-shadow: ${rest}; } }`
  );
}

function percent(at: number, cycle: number): string {
  return `${((at / cycle) * 100).toFixed(3)}%`;
}

/**
 * n 個節點的 keyframes。百分比依一輪的長度而定，CSS 變數不能用在 keyframes 的百分比，
 * 所以依節點數產生。內容只由整數 n 與計算出的數字組成，同樣的 n 一定產生同樣的文字。
 */
export function flowKeyframes(n: number): string {
  const cycle = flowCycleS(n);
  const names = flowNames(n);
  const end = `opacity: 0; transform: translateX(${ARROW_TRAVEL_PX}px);`;
  const arrow =
    `@keyframes ${names.arrow} { 0% { opacity: 0; transform: translateX(0); } ` +
    `${percent(FLOW_STEP_S * ARROW_FADE, cycle)} { opacity: 1; } ` +
    `${percent(FLOW_STEP_S * (1 - ARROW_FADE), cycle)} { opacity: 1; } ` +
    `${percent(FLOW_STEP_S, cycle)} { ${end} } 100% { ${end} } }`;
  return [
    shadowKeyframes(names.node, NODE_REST, NODE_PEAK, cycle),
    shadowKeyframes(names.pressed, `${PRESSED_RING}, ${NODE_REST}`, `${PRESSED_RING}, ${NODE_PEAK}`, cycle),
    shadowKeyframes(names.dot, DOT_REST, DOT_PEAK, cycle),
    arrow,
  ].join("\n");
}
