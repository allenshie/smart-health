import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { LaneItem, LaneNode } from "../lib/layout";
import { LaneRow } from "./LaneRow";

function item(id: string, children: LaneNode[] = []): LaneItem {
  return { id, label: id.toUpperCase(), children };
}

function renderLane(lane: LaneNode) {
  return render(
    <LaneRow lane={lane} nodes={{}} online selectedId={null} onSelect={() => {}} />,
  );
}

describe("LaneRow", () => {
  it("draws arrows between nodes of a sequential lane", () => {
    const { container } = renderLane({
      id: "m",
      label: "Main",
      sequential: true,
      nodes: [item("a"), item("b"), item("c")],
    });
    expect(screen.getByText("Main")).toBeTruthy();
    expect(container.querySelectorAll(".lane-arrow")).toHaveLength(2);
    expect(screen.getAllByRole("button").map((b) => b.getAttribute("data-node-id"))).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("draws no arrows in a non-sequential lane", () => {
    const { container } = renderLane({
      id: "w",
      label: "Workers",
      sequential: false,
      nodes: [item("a"), item("b")],
    });
    expect(container.querySelectorAll(".lane-arrow")).toHaveLength(0);
  });

  it("shows child lanes below, marked with the parent label", () => {
    const grandchild: LaneNode = { id: "g", label: "Grand", sequential: false, nodes: [item("z")] };
    const child: LaneNode = {
      id: "c",
      label: "Child",
      sequential: false,
      nodes: [item("y", [grandchild])],
    };
    const { container } = renderLane({
      id: "m",
      label: "Main",
      sequential: true,
      nodes: [item("a"), item("x", [child])],
    });
    expect(screen.getByText("從 X 分出")).toBeTruthy();
    expect(screen.getByText("從 Y 分出")).toBeTruthy();
    const childLane = container.querySelector('[data-lane-id="c"]');
    expect(childLane?.closest(".lane-children")).not.toBeNull();
    expect(childLane?.querySelector('[data-lane-id="g"]')).not.toBeNull();
  });

  it("renders a node listed twice in one lane without duplicate key warnings", () => {
    renderLane({ id: "m", label: "Main", sequential: true, nodes: [item("a"), item("a")] });
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });
});
