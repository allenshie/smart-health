import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TargetSummary } from "../api/types";
import { TargetSelector } from "./TargetSelector";

const targets: TargetSummary[] = [
  { id: "a", name: "Mock Edge A", connection: "online", summary_color: "green", last_success_at: null },
  { id: "b", name: "Mock API", connection: "offline", summary_color: "gray", last_success_at: null },
];

describe("TargetSelector", () => {
  it("lists targets as 名稱（connection 代碼） and marks the selected one", () => {
    render(<TargetSelector targets={targets} selectedId="b" onChange={() => {}} />);
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "服務：" });
    const options = screen.getAllByRole<HTMLOptionElement>("option");
    expect(options.map((o) => o.textContent)).toEqual(["Mock Edge A（online）", "Mock API（offline）"]);
    expect(select.value).toBe("b");
  });

  it("renders html in target names as plain text", () => {
    const html = "<img src=x onerror=alert(1)>";
    const { container } = render(
      <TargetSelector targets={[{ ...targets[0], name: html }]} selectedId="a" onChange={() => {}} />,
    );
    expect(screen.getByRole("option").textContent).toBe(`${html}（online）`);
    expect(container.querySelector("img")).toBeNull();
  });

  it("reports the chosen target id", () => {
    const onChange = vi.fn();
    render(<TargetSelector targets={targets} selectedId="a" onChange={onChange} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "b" } });
    expect(onChange).toHaveBeenCalledWith("b");
  });
});
