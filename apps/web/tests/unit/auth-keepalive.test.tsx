import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionKeepalive } from "@/features/auth/hooks/use-session-keepalive";
import { broadcastAuth } from "@/lib/auth/broadcast";
import { refreshSession } from "@/lib/auth/refresh";

vi.mock("@/lib/auth/refresh", () => ({ refreshSession: vi.fn().mockResolvedValue(undefined) }));

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-15T12:00:00Z"));
  vi.clearAllMocks();
  document.cookie = "mo_auth=; Max-Age=0";
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const setExpiry = (seconds: number): void => {
  document.cookie = `mo_auth=${Math.floor(Date.now() / 1000) + seconds}`;
};

describe("visible session keepalive", () => {
  it("refreshes sixty seconds before expiry and cleans up on unmount", async () => {
    setExpiry(120);
    const { unmount } = renderHook(useSessionKeepalive);
    await act(() => vi.advanceTimersByTimeAsync(59_999));
    expect(refreshSession).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(refreshSession).toHaveBeenCalledTimes(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("never schedules a signed-out session", async () => {
    renderHook(useSessionKeepalive);
    await act(() => vi.advanceTimersByTimeAsync(120_000));
    expect(refreshSession).not.toHaveBeenCalled();
  });

  it("pauses while hidden and refreshes on returning near expiry", async () => {
    setExpiry(120);
    renderHook(useSessionKeepalive);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await act(() => vi.advanceTimersByTimeAsync(90_000));
    expect(refreshSession).not.toHaveBeenCalled();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(refreshSession).toHaveBeenCalledTimes(1);
  });

  it("reschedules against updated cookies after a refreshed broadcast", async () => {
    setExpiry(120);
    renderHook(useSessionKeepalive);
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    setExpiry(180);
    act(() => {
      broadcastAuth("refreshed");
    });
    await act(() => vi.advanceTimersByTimeAsync(119_999));
    expect(refreshSession).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(refreshSession).toHaveBeenCalledTimes(1);
  });
});
