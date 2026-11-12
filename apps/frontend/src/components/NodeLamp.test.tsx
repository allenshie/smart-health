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

// SPEC §7.1「每秒次數」：metrics.rate_per_s 是數字時，顯示在狀態文字下方。
describe("NodeLamp 每秒次數", () => {
  const rate = (button: HTMLElement) => button.querySelector(".lamp-rate");

  it("shows rate_per_s below the state text as N.NN/s", () => {
    const { button } = renderLamp({ node: nodeView({ metrics: { rate_per_s: 3.998789 } }) });
    const shown = rate(button);
    expect(shown?.textContent).toBe("4.00/s");
    const state = button.querySelector(".lamp-state")!;
    expect(state.compareDocumentPosition(shown!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(state.textContent).toBe("ok");
  });

  it("uses the shared number format", () => {
    const { button } = renderLamp({ node: nodeView({ metrics: { rate_per_s: -0.001 } }) });
    expect(rate(button)?.textContent).toBe("0.00/s");
  });

  it("works for any node id and keeps other metrics out of the lamp", () => {
    const { button } = renderLamp({
      id: "whatever-node",
      label: "Whatever",
      node: nodeView({ metrics: { duration_ms: 12.3456, rate_per_s: 0.023092 } }),
    });
    expect(rate(button)?.textContent).toBe("0.02/s");
    expect(button.textContent).not.toContain("12.35");
  });

  it("shows nothing without rate_per_s", () => {
    const { button } = renderLamp({ node: nodeView({ metrics: { fps: 4 } }) });
    expect(rate(button)).toBeNull();
    expect(button.textContent).not.toContain("/s");
  });

  it.each([["4"], [null], [true]])("shows nothing when rate_per_s is not a number (%j)", (value) => {
    const { button } = renderLamp({ node: nodeView({ metrics: { rate_per_s: value } }) });
    expect(rate(button)).toBeNull();
  });

  it("shows nothing when the target is not online", () => {
    const { button } = renderLamp({ online: false, node: nodeView({ metrics: { rate_per_s: 4 } }) });
    expect(rate(button)).toBeNull();
  });

  it("shows nothing on backend error", () => {
    const { button } = renderLamp({ backendError: true, node: nodeView({ metrics: { rate_per_s: 4 } }) });
    expect(rate(button)).toBeNull();
    expect(button.textContent).not.toContain("/s");
  });

  it("shows nothing when the node has no status", () => {
    const { button } = renderLamp({ node: undefined });
    expect(rate(button)).toBeNull();
  });
});

// v1.8 發光燈號（SPEC §7.1 視覺）：樣式由 lamp-<color> class 決定；鎖住現有行為的測試。
describe("NodeLamp 顏色 class", () => {
  it.each(["green", "yellow", "red", "gray"] as const)("gives a %s node the lamp-%s class and a dot", (color) => {
    const { button } = renderLamp({ node: nodeView({ color }) });
    expect(button.getAttribute("data-color")).toBe(color);
    expect(button.classList.contains(`lamp-${color}`)).toBe(true);
    expect(button.querySelector(".lamp-dot")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("uses lamp-gray when not online or on backend error", () => {
    const { button } = renderLamp({ node: nodeView({ color: "green" }), online: false, backendError: true });
    expect(button.classList.contains("lamp-gray")).toBe(true);
    expect(button.classList.contains("lamp-green")).toBe(false);
  });

  it("sets --flow-delay when given", () => {
    const { button } = renderLamp({ flowDelay: "1.28s" });
    expect(button.style.getPropertyValue("--flow-delay")).toBe("1.28s");
  });

  it("has no inline style outside a lane that can flow", () => {
    const { button } = renderLamp();
    expect(button.getAttribute("style")).toBeNull();
  });
});
