import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TopologyView as Topology } from "../api/types";
import { flowKeyframes } from "../lib/flow";
import { apiTopology, edgeTopology, nodeView } from "../test/fixtures";
import { TopologyView } from "./TopologyView";

const HTML = "<img src=x onerror=alert(1)>";

const irregular: Topology = {
  service: "odd",
  instance: "odd-1",
  topology_version: "0000000000000000",
  lanes: [
    { id: "one", label: "One", parent: "nowhere", sequential: true, nodes: ["p", "q", "unlisted"] },
    { id: "two", label: "Two", parent: "p", sequential: false, nodes: ["p", "r"] },
    { id: "three", label: `Three ${HTML}`, parent: "r", sequential: true, nodes: ["s"] },
  ],
  nodes: ["p", "q", "r", "s", "orphan-a", "orphan-b"].map((id) => ({
    id,
    label: id === "s" ? `Node s ${HTML}` : `Node ${id}`,
    upstream: [],
    dependencies: [],
  })),
};

function lampIds(): string[] {
  return screen.getAllByRole("button").map((b) => b.getAttribute("data-node-id") ?? "");
}

describe("TopologyView", () => {
  it.each([
    ["edge", edgeTopology],
    ["api", apiTopology],
    ["irregular", irregular],
  ])("renders every node from any topology (%s)", (_name, topology) => {
    const nodes = Object.fromEntries(topology.nodes.map((n) => [n.id, nodeView()]));
    render(
      <TopologyView
        topology={topology}
        nodes={nodes}
        online
        selectedId={null}
        onSelect={() => {}}
      />,
    );
    const shown = new Set(lampIds());
    for (const n of topology.nodes) {
      expect(shown.has(n.id), n.id).toBe(true);
      expect(screen.getAllByText(n.label).length).toBeGreaterThan(0);
    }
    for (const lane of topology.lanes) {
      for (const id of lane.nodes) expect(shown.has(id), id).toBe(true);
      expect(screen.getAllByText(lane.label).length).toBeGreaterThan(0);
    }
  });

  it("shows orphan nodes in a 其他節點 lane and unknown ids by id", () => {
    render(
      <TopologyView topology={irregular} nodes={{}} online selectedId={null} onSelect={() => {}} />,
    );
    expect(screen.getByText("其他節點")).toBeTruthy();
    expect(screen.getByRole("button", { name: "unlisted 未知" })).toBeTruthy();
  });

  it("renders html in node and lane labels as plain text", () => {
    const { container } = render(
      <TopologyView topology={irregular} nodes={{}} online selectedId={null} onSelect={() => {}} />,
    );
    expect(screen.getByText(`Node s ${HTML}`)).toBeTruthy();
    expect(screen.getByText(`Three ${HTML}`)).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
  });

  it("marks every lamp of the selected node as pressed", () => {
    render(
      <TopologyView topology={irregular} nodes={{}} online selectedId="p" onSelect={() => {}} />,
    );
    const pressed = screen
      .getAllByRole("button")
      .filter((b) => b.getAttribute("aria-pressed") === "true")
      .map((b) => b.getAttribute("data-node-id"));
    expect(pressed).toEqual(["p", "p"]);
  });
});

// v1.8 光點流動：依畫面上出現的節點數產生 keyframes（SPEC §7.1 視覺）
describe("TopologyView keyframes", () => {
  const lanes: Topology = {
    ...irregular,
    lanes: [
      { id: "a", label: "A", parent: null, sequential: true, nodes: ["p", "q", "r"] },
      { id: "b", label: "B", parent: "p", sequential: true, nodes: ["s", "orphan-a"] },
      { id: "c", label: "C", parent: null, sequential: true, nodes: ["orphan-b", "q", "r"] },
      { id: "d", label: "D", parent: null, sequential: false, nodes: ["p", "q", "r", "s"] },
      { id: "e", label: "E", parent: null, sequential: true, nodes: ["s"] },
    ],
  };
  const styleText = (container: HTMLElement) => [...container.querySelectorAll("style")].map((s) => s.textContent).join("");

  it("outputs one style with one set of keyframes per node count of the lanes that can flow", () => {
    const { container } = render(<TopologyView topology={lanes} nodes={{}} online selectedId={null} onSelect={() => {}} />);
    expect(container.querySelectorAll("style")).toHaveLength(1);
    expect(styleText(container)).toBe([flowKeyframes(2), flowKeyframes(3)].join("\n"));
  });

  it("outputs no style when no lane can flow", () => {
    const still: Topology = {
      ...irregular,
      lanes: [
        { id: "a", label: "A", parent: null, sequential: false, nodes: ["p", "q", "r"] },
        { id: "b", label: "B", parent: "p", sequential: true, nodes: ["s"] },
      ],
    };
    const { container } = render(<TopologyView topology={still} nodes={{}} online selectedId={null} onSelect={() => {}} />);
    expect(container.querySelectorAll("style")).toHaveLength(0);
  });

  it("keeps the same style element and text across updates", () => {
    const nodes = Object.fromEntries(edgeTopology.nodes.map((n) => [n.id, nodeView()]));
    const view = (n: typeof nodes) => (
      <TopologyView topology={{ ...edgeTopology }} nodes={n} online selectedId={null} onSelect={() => {}} />
    );
    const { container, rerender } = render(view(nodes));
    const style = container.querySelector("style")!;
    const text = style.textContent;
    expect(text).toBe(flowKeyframes(4));
    rerender(view({ ...nodes, infer: nodeView({ color: "red" }) }));
    expect(container.querySelector("style")).toBe(style);
    expect(style.textContent).toBe(text);
  });
});
