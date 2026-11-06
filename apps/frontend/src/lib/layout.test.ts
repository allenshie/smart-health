import { describe, expect, it } from "vitest";
import type { Lane, TopologyView } from "../api/types";
import { apiTopology, edgeTopology } from "../test/fixtures";
import { buildLaneTree, topologyNodeIds, type LaneNode } from "./layout";

function topology(lanes: Lane[], nodeIds: string[] = []): TopologyView {
  return {
    service: "svc",
    instance: "svc-1",
    topology_version: "0000000000000000",
    lanes,
    nodes: nodeIds.map((id) => ({
      id,
      label: id.toUpperCase(),
      upstream: [],
      dependencies: [],
    })),
  };
}

function lane(id: string, parent: string | null, nodes: string[], sequential = true): Lane {
  return { id, label: `lane ${id}`, parent, sequential, nodes };
}

/** 走訪整棵樹，回傳出現過的 lane id（含重複）。 */
function laneIds(tree: LaneNode[]): string[] {
  return tree.flatMap((l) => [
    l.id,
    ...l.nodes.flatMap((item) => laneIds(item.children)),
  ]);
}

describe("buildLaneTree", () => {
  it("buildLaneTree handles edge topology", () => {
    expect(buildLaneTree(edgeTopology)).toEqual([
      {
        id: "main",
        label: "Main",
        sequential: true,
        nodes: [
          {
            id: "ingest",
            label: "Ingest",
            children: [
              {
                id: "ingest-bg",
                label: "Ingest worker",
                sequential: false,
                nodes: [{ id: "ingest-worker", label: "Ingest worker", children: [] }],
              },
            ],
          },
          { id: "infer", label: "Infer", children: [] },
          {
            id: "stream",
            label: "Stream",
            children: [
              {
                id: "stream-bg",
                label: "Stream output",
                sequential: false,
                nodes: [{ id: "stream-output", label: "Stream output", children: [] }],
              },
            ],
          },
          { id: "publish", label: "Publish", children: [] },
        ],
      },
    ]);
  });

  it("buildLaneTree handles nested lanes", () => {
    expect(buildLaneTree(apiTopology)).toEqual([
      {
        id: "main",
        label: "Request path",
        sequential: true,
        nodes: [
          { id: "gateway", label: "Gateway", children: [] },
          {
            id: "handler",
            label: "Handler",
            children: [
              {
                id: "workers",
                label: "Background workers",
                sequential: false,
                nodes: [
                  {
                    id: "job-runner",
                    label: "Job runner",
                    children: [
                      {
                        id: "batch",
                        label: "Batch jobs",
                        sequential: false,
                        nodes: [{ id: "batch-export", label: "Batch export", children: [] }],
                      },
                    ],
                  },
                  { id: "cache-warmer", label: "Cache warmer", children: [] },
                ],
              },
            ],
          },
          { id: "response", label: "Response", children: [] },
        ],
      },
    ]);
  });

  it("keeps child lanes in original order under the same parent", () => {
    const tree = buildLaneTree(
      topology([lane("m", null, ["a"]), lane("y", "a", ["y1"]), lane("x", "a", ["x1"])]),
    );
    expect(tree[0].nodes[0].children.map((l) => l.id)).toEqual(["y", "x"]);
  });

  it("returns an empty tree for an empty topology", () => {
    expect(buildLaneTree(topology([]))).toEqual([]);
  });

  it("treats a lane whose parent is not in any lane as top-level", () => {
    const tree = buildLaneTree(
      topology([lane("m", null, ["a"]), lane("ghost-child", "ghost", ["b"]), lane("n", null, ["c"])]),
    );
    expect(tree.map((l) => l.id)).toEqual(["m", "ghost-child", "n"]);
  });

  it("breaks parent cycles without looping and places each lane once", () => {
    const lanes = [
      lane("p", "y", ["x"]),
      lane("q", "x", ["y"]),
      lane("self", "z", ["z"]),
    ];
    const tree = buildLaneTree(topology(lanes, ["x", "y", "z"]));
    expect(tree.map((l) => l.id)).toEqual(["p", "self"]);
    expect(tree[0].nodes[0].children.map((l) => l.id)).toEqual(["q"]);
    expect(tree[0].nodes[0].children[0].nodes[0].children).toEqual([]);
    expect(tree[1].nodes[0].children).toEqual([]);
    expect(laneIds(tree).sort()).toEqual(["p", "q", "self"]);
  });

  it("attaches a child lane only once when its parent appears in several lanes", () => {
    const tree = buildLaneTree(
      topology([lane("m", null, ["a", "b"]), lane("n", null, ["a"]), lane("c", "a", ["c1"])]),
    );
    expect(laneIds(tree)).toEqual(["m", "c", "n"]);
    expect(tree[0].nodes[0].children.map((l) => l.id)).toEqual(["c"]);
    expect(tree[1].nodes[0].children).toEqual([]);
  });

  it("puts nodes not listed in any lane into a final 其他節點 lane", () => {
    const tree = buildLaneTree(topology([lane("m", null, ["a"])], ["a", "lonely", "alone"]));
    expect(tree).toHaveLength(2);
    expect(tree[1]).toMatchObject({ label: "其他節點", sequential: false });
    expect(tree[1].nodes).toEqual([
      { id: "lonely", label: "LONELY", children: [] },
      { id: "alone", label: "ALONE", children: [] },
    ]);
    expect(tree[1].id).not.toBe("m");
  });

  it("does not add the 其他節點 lane when every node is listed", () => {
    const tree = buildLaneTree(topology([lane("m", null, ["a"])], ["a"]));
    expect(tree.map((l) => l.label)).toEqual(["lane m"]);
  });

  it("shows lane nodes missing from topology.nodes with their id as label", () => {
    const tree = buildLaneTree(topology([lane("m", null, ["a", "missing"])], ["a"]));
    expect(tree[0].nodes).toEqual([
      { id: "a", label: "A", children: [] },
      { id: "missing", label: "missing", children: [] },
    ]);
  });
});

describe("topologyNodeIds", () => {
  it("collects ids from lanes and nodes", () => {
    const ids = topologyNodeIds(topology([lane("m", null, ["a", "b"])], ["a", "c"]));
    expect([...ids].sort()).toEqual(["a", "b", "c"]);
  });
});
