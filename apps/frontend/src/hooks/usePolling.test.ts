import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePolling } from "./usePolling";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("usePolling", () => {
  it("calls fn immediately and exposes data", async () => {
    const fn = vi.fn().mockResolvedValue("a");
    const { result } = renderHook(() => usePolling(fn, 1000));
    await advance(0);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe("a");
    expect(result.current.error).toBeNull();
    expect(result.current.lastSuccessAt).toBeInstanceOf(Date);
  });

  it("keeps last data when a poll fails", async () => {
    const boom = new Error("boom");
    const fn = vi.fn().mockResolvedValueOnce("a").mockRejectedValue(boom);
    const { result } = renderHook(() => usePolling(fn, 1000));
    await advance(0);
    const first = result.current.lastSuccessAt;
    await advance(1000);
    expect(result.current.data).toBe("a");
    expect(result.current.error).toBe(boom);
    expect(result.current.lastSuccessAt).toBe(first);
  });

  it("wraps non-Error rejections", async () => {
    const fn = vi.fn().mockRejectedValue("oops");
    const { result } = renderHook(() => usePolling(fn, 1000));
    await advance(0);
    expect(result.current.error).toBeInstanceOf(Error);
  });

  it("recovers after failure", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("x"))
      .mockResolvedValue("ok");
    const { result } = renderHook(() => usePolling(fn, 1000));
    await advance(0);
    expect(result.current.error).not.toBeNull();
    expect(result.current.data).toBeNull();
    await advance(1000);
    expect(result.current.data).toBe("ok");
    expect(result.current.error).toBeNull();
    expect(result.current.lastSuccessAt).toBeInstanceOf(Date);
  });

  it("uses configured interval", async () => {
    const fn = vi.fn().mockResolvedValue(1);
    renderHook(() => usePolling(fn, 3000));
    await advance(0);
    expect(fn).toHaveBeenCalledTimes(1);
    await advance(2999);
    expect(fn).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("waits for the previous call to finish before scheduling the next", async () => {
    let resolve: (v: number) => void = () => {};
    const fn = vi.fn().mockImplementation(
      () => new Promise<number>((r) => { resolve = r; }),
    );
    renderHook(() => usePolling(fn, 1000));
    await advance(5000);
    expect(fn).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolve(1);
    });
    await advance(1000);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("stops polling on unmount", async () => {
    const fn = vi.fn().mockResolvedValue(1);
    const { unmount } = renderHook(() => usePolling(fn, 1000));
    await advance(0);
    unmount();
    await advance(10000);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("ignores a result that arrives after unmount", async () => {
    let resolve: (v: number) => void = () => {};
    const fn = vi.fn().mockImplementation(
      () => new Promise<number>((r) => { resolve = r; }),
    );
    const { unmount } = renderHook(() => usePolling(fn, 1000));
    await advance(0);
    unmount();
    await act(async () => {
      resolve(1);
    });
    await advance(5000);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("does not restart when fn identity changes", async () => {
    const first = vi.fn().mockResolvedValue("first");
    const second = vi.fn().mockResolvedValue("second");
    const { result, rerender } = renderHook(({ f }) => usePolling(f, 1000), {
      initialProps: { f: first },
    });
    await advance(0);
    rerender({ f: second });
    await advance(0);
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).not.toHaveBeenCalled();
    await advance(1000);
    expect(second).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe("second");
  });

  it("reschedules with the new interval when it changes", async () => {
    const fn = vi.fn().mockResolvedValue(1);
    const { rerender } = renderHook(({ ms }) => usePolling(fn, ms), {
      initialProps: { ms: 10000 },
    });
    await advance(0);
    rerender({ ms: 1000 });
    await advance(1000);
    expect(fn.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it.each([0, -1, Number.NaN, Number.POSITIVE_INFINITY])(
    "calls only once when interval is %s",
    async (ms) => {
      const fn = vi.fn().mockResolvedValue(1);
      renderHook(() => usePolling(fn, ms));
      await advance(0);
      await advance(60000);
      expect(fn).toHaveBeenCalledTimes(1);
    },
  );
});
