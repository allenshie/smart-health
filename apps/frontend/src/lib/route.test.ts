import { describe, expect, it } from "vitest";
import { overviewHash, parseHash, targetHash } from "./route";

// SPEC §7.1 的 hash 表。
describe("parseHash：總覽", () => {
  it.each(["", "#", "#/"])("treats %j as overview page 1 without rewriting", (hash) => {
    expect(parseHash(hash)).toEqual({ route: { kind: "overview", page: 1 }, rewrite: null });
  });

  it.each([
    ["#/?page=1", 1],
    ["#/?page=2", 2],
    ["#/?page=30", 30],
  ])("reads the page from %s", (hash, page) => {
    expect(parseHash(hash)).toEqual({ route: { kind: "overview", page }, rewrite: null });
  });

  it("only looks at the page parameter", () => {
    expect(parseHash("#/?page=2&sort=name")).toEqual({ route: { kind: "overview", page: 2 }, rewrite: null });
    expect(parseHash("#/?sort=name")).toEqual({ route: { kind: "overview", page: 1 }, rewrite: null });
  });

  it.each(["0", "-1", "abc", "1.5", "01", "", "1e2", " 2", "2 "])(
    "shows page 1 and rewrites to #/ when page is %j",
    (page) => {
      expect(parseHash(`#/?page=${page}`)).toEqual({ route: { kind: "overview", page: 1 }, rewrite: "#/" });
    },
  );
});

describe("parseHash：服務畫面", () => {
  it.each(["mock-edge-a", "a", "raw_http-500", "x1"])("reads a valid id %s", (id) => {
    expect(parseHash(`#/targets/${id}`)).toEqual({ route: { kind: "target", id, valid: true }, rewrite: null });
  });

  it("decodes the id", () => {
    expect(parseHash("#/targets/mock%2Dedge")).toEqual({
      route: { kind: "target", id: "mock-edge", valid: true },
      rewrite: null,
    });
  });

  it.each([
    ["#/targets/Mock", "Mock"],
    ["#/targets/1abc", "1abc"],
    ["#/targets/", ""],
    ["#/targets/a/b", "a/b"],
    ["#/targets/a%2Fb", "a/b"],
    ["#/targets/a?page=2", "a?page=2"],
    ["#/targets/%E4%B8%AD", "中"],
    ["#/targets/%3Cb%3E", "<b>"],
  ])("treats %s as an invalid id without rewriting", (hash, id) => {
    expect(parseHash(hash)).toEqual({ route: { kind: "target", id, valid: false }, rewrite: null });
  });

  it.each([
    ["#/targets/%", "%"],
    ["#/targets/a%E4", "a%E4"],
    ["#/targets/%zz", "%zz"],
  ])("treats an id that cannot be decoded (%s) as invalid, keeping the raw text", (hash, id) => {
    expect(parseHash(hash)).toEqual({ route: { kind: "target", id, valid: false }, rewrite: null });
  });
});

describe("parseHash：其他", () => {
  it.each(["#foo", "#/foo", "#/targets", "#//", "#?page=2", "#/target/a", "#/TARGETS/a", "#/overview"])(
    "rewrites %s to #/",
    (hash) => {
      expect(parseHash(hash)).toEqual({ route: { kind: "overview", page: 1 }, rewrite: "#/" });
    },
  );
});

describe("hash 產生", () => {
  it("writes page 1 as #/ and other pages with ?page=", () => {
    expect(overviewHash(1)).toBe("#/");
    expect(overviewHash(2)).toBe("#/?page=2");
  });

  it("encodes the target id", () => {
    expect(targetHash("mock-edge-a")).toBe("#/targets/mock-edge-a");
    expect(targetHash("a/b")).toBe("#/targets/a%2Fb");
  });

  it("round-trips through parseHash", () => {
    expect(parseHash(overviewHash(3)).route).toEqual({ kind: "overview", page: 3 });
    expect(parseHash(targetHash("mock-api")).route).toEqual({ kind: "target", id: "mock-api", valid: true });
  });
});
