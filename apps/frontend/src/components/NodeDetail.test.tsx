import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { nodeView } from "../test/fixtures";
import { NodeDetail } from "./NodeDetail";
import { NodeLamp } from "./NodeLamp";

function detailRegion() {
  return screen.getByRole("region", { name: "節點詳細資料" });
}

/** 取得「欄位名稱」對應的值文字。 */
function field(name: string): string {
  const term = within(detailRegion()).getByText(name);
  const value = term.nextElementSibling;
  if (value === null) throw new Error(`找不到 ${name} 的值`);
  return value.textContent ?? "";
}

describe("NodeDetail", () => {
  it("null state shows 未知", () => {
    const node = nodeView({ state: null, reason: "status_missing", color: "gray" });
    render(
      <>
        <NodeLamp id="infer" label="Infer" node={node} online selected onSelect={() => {}} />
        <NodeDetail id="infer" label="Infer" node={node} />
      </>,
    );
    expect(screen.getByRole("button", { name: "Infer 未知" })).toBeTruthy();
    expect(field("狀態")).toBe("未知");
    expect(field("原因")).toBe("status_missing");
  });

  it("shows every field in order with metrics as key = value lines", () => {
    render(
      <NodeDetail
        id="ingest-worker"
        label="Ingest worker"
        node={nodeView({
          state: "unavailable",
          reason: "no_new_frame",
          message: "已 12 秒沒有成功紀錄",
          since: "2026-11-06T02:32:03Z",
          metrics: { fps: 12.5, camera: "cam-a", healthy: false, lag: null },
        })}
      />,
    );
    const region = detailRegion();
    expect(within(region).getByRole("heading").textContent).toBe("Ingest worker（ingest-worker）");
    const terms = within(region)
      .getAllByRole("term")
      .map((t) => t.textContent);
    expect(terms).toEqual(["狀態", "原因", "說明", "開始時間", "指標"]);
    expect(field("狀態")).toBe("unavailable");
    expect(field("原因")).toBe("no_new_frame");
    expect(field("說明")).toBe("已 12 秒沒有成功紀錄");
    expect(field("開始時間")).toBe("10:32:03");
    expect(within(region).getByText("10:32:03").getAttribute("title")).toBe(
      "2026-11-06T02:32:03Z",
    );
    const metricLines = within(region)
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(metricLines).toEqual([
      "fps = 12.50",
      "camera = cam-a",
      "healthy = false",
      "lag = —",
    ]);
  });

  it("shows only the label in the heading when it equals the id", () => {
    render(<NodeDetail id="infer" label="infer" node={nodeView()} />);
    expect(within(detailRegion()).getByRole("heading").textContent).toBe("infer");
  });

  it("shows — for null fields and empty metrics", () => {
    render(<NodeDetail id="infer" label="Infer" node={nodeView()} />);
    expect(field("原因")).toBe("—");
    expect(field("說明")).toBe("—");
    expect(field("開始時間")).toBe("—");
    expect(field("指標")).toBe("—");
  });

  it("shows 未知 and — when the node has no status at all", () => {
    render(<NodeDetail id="infer" label="Infer" node={undefined} />);
    expect(field("狀態")).toBe("未知");
    expect(field("原因")).toBe("—");
  });

  it("renders html in message as plain text", () => {
    const html = "<img src=x onerror=alert(1)>";
    const { container } = render(
      <NodeDetail
        id="infer"
        label="<b>Infer</b>"
        node={nodeView({ message: html, reason: "<i>r</i>", metrics: { "<u>k</u>": "<s>v</s>" } })}
      />,
    );
    expect(field("說明")).toBe(html);
    expect(screen.getByText(html)).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b, i, u, s")).toBeNull();
  });
});
