import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { LaneItem, LaneNode } from "../lib/layout";
import { nodeView } from "../test/fixtures";
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

// v1.8 光點流動（SPEC §7.1 視覺）
describe("LaneRow 流動", () => {
  const green = (ids: string[]) => Object.fromEntries(ids.map((id) => [id, nodeView()]));
  const seq = (ids: string[], sequential = true): LaneNode => ({
    id: "m",
    label: "Main",
    sequential,
    nodes: ids.map((id) => item(id)),
  });
  const laneEl = (container: HTMLElement, id = "m") => container.querySelector<HTMLElement>(`[data-lane-id="${id}"]`)!;
  const props = { selectedId: null, onSelect: () => {} };

  it("marks an all-green sequential lane as flowing", () => {
    const { container } = render(<LaneRow lane={seq(["a", "b", "c"])} nodes={green(["a", "b", "c"])} online {...props} />);
    expect(laneEl(container).getAttribute("data-flowing")).toBe("true");
  });

  it.each([
    ["a yellow node", seq(["a", "b"]), { ...green(["a"]), b: nodeView({ color: "yellow" }) }, true],
    ["a red node", seq(["a", "b"]), { ...green(["a"]), b: nodeView({ color: "red" }) }, true],
    ["a gray node", seq(["a", "b"]), { ...green(["a"]), b: nodeView({ color: "gray" }) }, true],
    ["a node without status", seq(["a", "b"]), green(["a"]), true],
    ["not online", seq(["a", "b"]), green(["a", "b"]), false],
    ["non-sequential", seq(["a", "b"], false), green(["a", "b"]), true],
    ["a single node", seq(["a"]), green(["a"]), true],
  ] as const)("does not flow with %s", (_name, lane, nodes, online) => {
    const { container } = render(<LaneRow lane={lane} nodes={nodes} online={online} {...props} />);
    expect(laneEl(container).getAttribute("data-flowing")).toBe("false");
  });

  it("does not flow on backend error", () => {
    const { container } = render(
      <LaneRow lane={seq(["a", "b"])} nodes={green(["a", "b"])} online={false} backendError {...props} />,
    );
    expect(laneEl(container).getAttribute("data-flowing")).toBe("false");
  });

  it("judges each nested lane on its own", () => {
    const child: LaneNode = { id: "c", label: "Child", sequential: true, nodes: [item("x"), item("y")] };
    const lane: LaneNode = { id: "m", label: "Main", sequential: true, nodes: [item("a", [child]), item("b")] };
    const { container } = render(
      <LaneRow lane={lane} nodes={{ ...green(["a", "b", "x"]), y: nodeView({ color: "red" }) }} online {...props} />,
    );
    expect(laneEl(container, "m").getAttribute("data-flowing")).toBe("true");
    expect(laneEl(container, "c").getAttribute("data-flowing")).toBe("false");
  });

  it("switches data-flowing when the condition changes and keeps the same lamp and arrow elements", () => {
    const lane = seq(["a", "b", "c"]);
    const { container, rerender } = render(<LaneRow lane={lane} nodes={green(["a", "b", "c"])} online {...props} />);
    const lamps = [...container.querySelectorAll(".lamp")];
    const arrows = [...container.querySelectorAll(".lane-arrow")];
    expect(laneEl(container).getAttribute("data-flowing")).toBe("true");

    rerender(<LaneRow lane={lane} nodes={{ ...green(["a", "c"]), b: nodeView({ color: "red" }) }} online {...props} />);
    expect(laneEl(container).getAttribute("data-flowing")).toBe("false");

    rerender(<LaneRow lane={{ ...lane }} nodes={green(["a", "b", "c"])} online {...props} />);
    expect(laneEl(container).getAttribute("data-flowing")).toBe("true");
    expect([...container.querySelectorAll(".lamp")]).toEqual(lamps);
    expect([...container.querySelectorAll(".lane-arrow")]).toEqual(arrows);
  });

  it("sets the cycle and keyframes of n nodes on the lane and the delay of each lamp and arrow", () => {
    const { container } = render(
      <LaneRow lane={seq(["a", "b", "c", "d"])} nodes={green(["a", "b", "c", "d"])} online {...props} />,
    );
    const style = laneEl(container).style;
    expect(style.getPropertyValue("--flow-cycle")).toBe("3.20s");
    expect(style.getPropertyValue("--flow-node")).toBe("flow-node-n4");
    expect(style.getPropertyValue("--flow-node-pressed")).toBe("flow-node-pressed-n4");
    expect(style.getPropertyValue("--flow-dot")).toBe("flow-dot-n4");
    expect(style.getPropertyValue("--flow-arrow")).toBe("flow-arrow-n4");
    const delays = (sel: string) =>
      [...container.querySelectorAll<HTMLElement>(sel)].map((el) => el.style.getPropertyValue("--flow-delay"));
    expect(delays(".lamp")).toEqual(["0.00s", "0.64s", "1.28s", "1.92s"]);
    expect(delays(".lane-arrow")).toEqual(["0.32s", "0.96s", "1.60s"]);
  });

  it("draws each arrow as a line with a light dot instead of text", () => {
    const { container } = render(<LaneRow lane={seq(["a", "b"])} nodes={green(["a", "b"])} online {...props} />);
    const arrow = container.querySelector(".lane-arrow")!;
    expect(arrow.getAttribute("aria-hidden")).toBe("true");
    expect(arrow.textContent).toBe("");
    expect(arrow.querySelectorAll(".lane-flow-dot")).toHaveLength(1);
  });
});
