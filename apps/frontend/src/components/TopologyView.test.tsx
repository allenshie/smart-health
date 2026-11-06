import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TopologyView as Topology } from "../api/types";
import { apiTopology, edgeTopology, nodeView } from "../test/fixtures";
import { TopologyView } from "./TopologyView";

const irregular: Topology = {
  service: "odd",
  instance: "odd-1",
  topology_version: "0000000000000000",
  lanes: [
    { id: "one", label: "One", parent: "nowhere", sequential: true, nodes: ["p", "q", "unlisted"] },
    { id: "two", label: "Two", parent: "p", sequential: false, nodes: ["p", "r"] },
    { id: "three", label: "Three", parent: "r", sequential: true, nodes: ["s"] },
  ],
  nodes: ["p", "q", "r", "s", "orphan-a", "orphan-b"].map((id) => ({
    id,
    label: `Node ${id}`,
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
