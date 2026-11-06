import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Connection } from "../api/types";
import { ConnectionBanner } from "./ConnectionBanner";

describe("ConnectionBanner", () => {
  it("renders nothing when online", () => {
    const { container } = render(
      <ConnectionBanner connection="online" lastSuccessAt="2026-11-06T02:32:15Z" />,
    );
    expect(container.innerHTML).toBe("");
  });

  it.each<[Connection, string]>([
    ["offline", "無法連線到此服務"],
    ["stale", "此服務的評估已停止更新"],
    ["incompatible", "此服務的契約版本不相容"],
    ["invalid_response", "此服務回傳的資料無效"],
    ["unknown", "尚未取得此服務的狀態"],
  ])("shows text and code for %s with the last success time", (connection, text) => {
    render(<ConnectionBanner connection={connection} lastSuccessAt="2026-11-06T02:32:15Z" />);
    const banner = screen.getByRole("status");
    expect(banner.textContent).toBe(`${text}（${connection}），最後更新 10:32:15`);
    expect(banner.getAttribute("data-connection")).toBe(connection);
  });

  it("says 尚未成功取得 when there was never a success", () => {
    render(<ConnectionBanner connection="offline" lastSuccessAt={null} />);
    expect(screen.getByRole("status").textContent).toBe(
      "無法連線到此服務（offline），尚未成功取得",
    );
  });
});
