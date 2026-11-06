import { describe, expect, it } from "vitest";
import { formatTime } from "./time";

// vite.config.ts 將測試時區固定為 Asia/Taipei（UTC+8）。
describe("formatTime", () => {
  it("formats an ISO string as local HH:MM:SS", () => {
    expect(formatTime("2026-11-06T02:32:15Z")).toBe("10:32:15");
  });

  it("pads with zeros and uses 24-hour clock", () => {
    expect(formatTime("2026-11-06T13:05:09+08:00")).toBe("13:05:09");
    expect(formatTime("2026-11-05T16:00:00Z")).toBe("00:00:00");
  });

  it("accepts a Date", () => {
    expect(formatTime(new Date("2026-11-06T02:32:15Z"))).toBe("10:32:15");
  });

  it("returns the original string when the date is invalid", () => {
    expect(formatTime("not-a-date")).toBe("not-a-date");
  });
});
