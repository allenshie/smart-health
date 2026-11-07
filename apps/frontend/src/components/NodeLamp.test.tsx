import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { nodeView } from "../test/fixtures";
import { NodeLamp } from "./NodeLamp";

function renderLamp(props: Partial<Parameters<typeof NodeLamp>[0]> = {}) {
  const onSelect = vi.fn();
  render(
    <NodeLamp
      id="infer"
      label="Infer"
      node={nodeView()}
      online
      selected={false}
      onSelect={onSelect}
      {...props}
    />,
  );
  return { button: screen.getByRole("button"), onSelect };
}

describe("NodeLamp", () => {
  it("lamp shows state text as well as color", () => {
    const { button } = renderLamp({ node: nodeView({ state: "degraded", color: "yellow" }) });
    expect(screen.getByRole("button", { name: "Infer degraded" })).toBe(button);
    expect(button.getAttribute("data-color")).toBe("yellow");
    expect(button.className).toContain("lamp-yellow");
  });

  it.each(["ok", "degraded", "unavailable", "waiting", "disabled"])(
    "shows state code %s as text",
    (state) => {
      const { button } = renderLamp({ node: nodeView({ state }) });
      expect(button.textContent).toContain(state);
    },
  );

  it("shows 未知 and gray on backend error even when the node has a state", () => {
    const { button } = renderLamp({ node: nodeView({ state: "ok" }), backendError: true, online: false });
    expect(screen.getByRole("button", { name: "Infer 未知" })).toBe(button);
    expect(button.getAttribute("data-color")).toBe("gray");
  });

  it("shows 未知 in gray when the node has no status", () => {
    const { button } = renderLamp({ node: undefined });
    expect(screen.getByRole("button", { name: "Infer 未知" })).toBe(button);
    expect(button.getAttribute("data-color")).toBe("gray");
  });

  it("is gray when the target is not online even if color says otherwise", () => {
    const { button } = renderLamp({ online: false, node: nodeView({ color: "green" }) });
    expect(button.getAttribute("data-color")).toBe("gray");
  });

  it("falls back to gray for an unexpected color value", () => {
    const node = { ...nodeView(), color: "purple" } as unknown as ReturnType<typeof nodeView>;
    const { button } = renderLamp({ node });
    expect(button.getAttribute("data-color")).toBe("gray");
  });

  it("reflects selection with aria-pressed and reports clicks with the node id", () => {
    const { button, onSelect } = renderLamp({ selected: true });
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(button.getAttribute("data-node-id")).toBe("infer");
    fireEvent.click(button);
    expect(onSelect).toHaveBeenCalledWith("infer");
  });

  it("is not pressed when not selected", () => {
    const { button } = renderLamp();
    expect(button.getAttribute("aria-pressed")).toBe("false");
  });
});
