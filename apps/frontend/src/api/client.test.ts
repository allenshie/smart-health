import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  fetchConfig,
  fetchTarget,
  fetchTargets,
  fetchTransitions,
} from "./client";

function stubFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("client", () => {
  it("fetchConfig requests /api/config without caching", async () => {
    const fn = stubFetch(200, { poll_interval_s: 5 });
    await expect(fetchConfig()).resolves.toEqual({ poll_interval_s: 5 });
    expect(fn).toHaveBeenCalledWith("/api/config", { cache: "no-store" });
  });

  it("fetchTargets requests /api/targets", async () => {
    const fn = stubFetch(200, []);
    await expect(fetchTargets()).resolves.toEqual([]);
    expect(fn.mock.calls[0][0]).toBe("/api/targets");
  });

  it("fetchTarget encodes the id in the path", async () => {
    const fn = stubFetch(200, { id: "a/b c" });
    await fetchTarget("a/b c");
    expect(fn.mock.calls[0][0]).toBe("/api/targets/a%2Fb%20c");
  });

  it("fetchTransitions omits limit when not given", async () => {
    const fn = stubFetch(200, []);
    await fetchTransitions("t1");
    expect(fn.mock.calls[0][0]).toBe("/api/targets/t1/transitions");
  });

  it("fetchTransitions sends limit when given", async () => {
    const fn = stubFetch(200, []);
    await fetchTransitions("t 1", 20);
    expect(fn.mock.calls[0][0]).toBe("/api/targets/t%201/transitions?limit=20");
  });

  it("client throws on non-2xx", async () => {
    stubFetch(404, { detail: "target_not_found" });
    const err = await fetchTarget("x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toBeInstanceOf(Error);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).message).not.toContain("target_not_found");
  });

  it("propagates network errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(fetchTargets()).rejects.toThrow("offline");
  });
});
