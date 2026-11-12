import { describe, expect, it } from "vitest";
import type { NodeView } from "../api/types";
import { nodeView } from "../test/fixtures";
import type { LaneItem, LaneNode } from "./layout";
import {
  FLOW_STEP_S,
  arrowDelayS,
  canFlow,
  flowCycleS,
  flowKeyframes,
  flowNames,
  laneFlowing,
  nodeDelayS,
  seconds,
} from "./flow";

function item(id: string, children: LaneNode[] = []): LaneItem {
  return { id, label: id, children };
}

function lane(ids: string[], sequential = true, children: Record<string, LaneNode[]> = {}): LaneNode {
  return { id: "main", label: "Main", sequential, nodes: ids.map((id) => item(id, children[id] ?? [])) };
}

function green(ids: string[]): Record<string, NodeView> {
  return Object.fromEntries(ids.map((id) => [id, nodeView()]));
}

describe("流動的時間（SPEC §7.1 視覺）", () => {
  it("uses 0.32 s steps", () => {
    expect(FLOW_STEP_S).toBe(0.32);
  });

  it.each([
    [2, "1.92s"],
    [3, "2.56s"],
    [4, "3.20s"],
    [7, "5.12s"],
  ])("computes the cycle of %i nodes as (2n + 2) × 0.32 s = %s", (n, text) => {
    expect(flowCycleS(n)).toBeCloseTo((2 * n + 2) * 0.32, 10);
    expect(seconds(flowCycleS(n))).toBe(text);
  });

  it("delays node k by 2(k − 1) steps: node 3 of 4 starts at 1.28 s", () => {
    expect([0, 1, 2, 3].map((i) => seconds(nodeDelayS(i)))).toEqual(["0.00s", "0.64s", "1.28s", "1.92s"]);
  });

  it("delays arrow k (before node k + 1) by 2k − 1 steps", () => {
    expect([1, 2, 3].map((i) => seconds(arrowDelayS(i)))).toEqual(["0.32s", "0.96s", "1.60s"]);
  });

  it("formats seconds with 2 decimals", () => {
    expect(seconds(0)).toBe("0.00s");
    expect(seconds(0.32 * 3)).toBe("0.96s");
  });
});

describe("流動的條件", () => {
  it("flows when a sequential lane of 2+ nodes is all green and online", () => {
    expect(laneFlowing(lane(["a", "b", "c"]), green(["a", "b", "c"]), true)).toBe(true);
    expect(laneFlowing(lane(["a", "b"]), green(["a", "b"]), true)).toBe(true);
  });

  it.each(["yellow", "red", "gray"] as const)("stops when any node is %s", (color) => {
    const nodes = { ...green(["a", "b", "c"]), b: nodeView({ color }) };
    expect(laneFlowing(lane(["a", "b", "c"]), nodes, true)).toBe(false);
  });

  it("stops when a node has no status", () => {
    expect(laneFlowing(lane(["a", "b", "c"]), green(["a", "c"]), true)).toBe(false);
  });

  it("stops when the target is not online (or the backend request failed)", () => {
    expect(laneFlowing(lane(["a", "b"]), green(["a", "b"]), false)).toBe(false);
  });

  it("never flows in a non-sequential lane", () => {
    expect(canFlow(lane(["a", "b"], false))).toBe(false);
    expect(laneFlowing(lane(["a", "b"], false), green(["a", "b"]), true)).toBe(false);
  });

  it("never flows with a single node", () => {
    expect(canFlow(lane(["a"]))).toBe(false);
    expect(laneFlowing(lane(["a"]), green(["a"]), true)).toBe(false);
  });

  it("judges only the lane's own nodes, not its child lanes", () => {
    const child: LaneNode = { id: "bg", label: "BG", sequential: false, nodes: [item("w")] };
    const nodes = { ...green(["a", "b"]), w: nodeView({ color: "red" }) };
    expect(laneFlowing(lane(["a", "b"], true, { a: [child] }), nodes, true)).toBe(true);
  });

  it("ignores prototype names such as constructor", () => {
    expect(laneFlowing(lane(["constructor", "a"]), green(["a"]), true)).toBe(false);
  });
});

describe("keyframes", () => {
  it("names one set of keyframes per node count", () => {
    expect(flowNames(4)).toEqual({
      node: "flow-node-n4",
      pressed: "flow-node-pressed-n4",
      dot: "flow-dot-n4",
      arrow: "flow-arrow-n4",
    });
  });

  it("defines every named keyframes for n", () => {
    const css = flowKeyframes(4);
    for (const name of Object.values(flowNames(4))) {
      expect(css).toContain(`@keyframes ${name} {`);
    }
  });

  it("places the node peak at 0.1 s and the end at 0.38 s of the cycle", () => {
    // 4 個節點一輪 3.20 秒：0.1 / 3.2 = 3.125%，0.38 / 3.2 = 11.875%
    const css = flowKeyframes(4);
    expect(css).toContain("3.125%");
    expect(css).toContain("11.875%");
  });

  it("moves the arrow light across within one 0.32 s step", () => {
    // 0.32 / 3.2 = 10%
    const arrow = flowKeyframes(4).split("@keyframes flow-arrow-n4")[1];
    expect(arrow).toContain("10.000% { opacity: 0; transform: translateX(32px); }");
  });

  it("produces the same text for the same n and differs between n only in numbers", () => {
    expect(flowKeyframes(4)).toBe(flowKeyframes(4));
    const strip = (css: string) => css.replace(/[0-9.]+/g, "#");
    expect(strip(flowKeyframes(3))).toBe(strip(flowKeyframes(9)));
  });

  it("uses only transform, opacity and box-shadow", () => {
    const props = new Set([...flowKeyframes(5).matchAll(/([a-z-]+):/g)].map((m) => m[1]));
    expect([...props].sort()).toEqual(["box-shadow", "opacity", "transform"]);
  });
});
