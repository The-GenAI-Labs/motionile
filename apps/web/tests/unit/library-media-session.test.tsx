import { focusManager, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMediaSession } from "@/features/library/hooks/use-media-session";
import { useRenditions } from "@/features/library/hooks/use-renditions";
import { REFRESH_LEAD_MS } from "@/features/library/media-session-sync";
import { libraryKeys } from "@/features/library/query-keys";

import {
  cloudfrontSession,
  presignedSession,
  presignedUrl,
  RENDER_ID,
  rendition,
} from "./library-fixtures";
import { makeTestQueryClient } from "./render-with-query";

const api = vi.hoisted(() => ({
  getMediaSession: vi.fn(),
  getRender: vi.fn(),
  listRenditions: vi.fn(),
}));

vi.mock("@/features/library/api/library.api", () => api);

const START = new Date("2026-10-20T10:00:00.000Z");
const TTL_MS = 3_600_000;
const isoAfter = (ms: number): string => new Date(START.getTime() + ms).toISOString();

const wrapperFor =
  (client = makeTestQueryClient()) =>
  ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );

const advance = async (ms: number): Promise<void> => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

beforeEach(() => {
  vi.useFakeTimers({ now: START });
  vi.clearAllMocks();
  localStorage.clear();
  focusManager.setFocused(undefined);
});

afterEach(() => {
  vi.useRealTimers();
  focusManager.setFocused(undefined);
});

describe("useMediaSession in cloudfront mode", () => {
  it("fetches once and exposes the mode and expiry", async () => {
    api.getMediaSession.mockResolvedValue(cloudfrontSession(isoAfter(TTL_MS)));
    const { result } = renderHook(() => useMediaSession(), { wrapper: wrapperFor() });

    expect(result.current.isReady).toBe(false);
    await advance(0);

    expect(result.current.isReady).toBe(true);
    expect(result.current.mode).toBe("cloudfront");
    expect(result.current.expiresAt).toBe(isoAfter(TTL_MS));
    expect(api.getMediaSession).toHaveBeenCalledTimes(1);
  });

  it("refreshes the cookies about sixty seconds before they expire", async () => {
    api.getMediaSession
      .mockResolvedValueOnce(cloudfrontSession(isoAfter(TTL_MS)))
      .mockResolvedValueOnce(cloudfrontSession(isoAfter(2 * TTL_MS)));
    const { result } = renderHook(() => useMediaSession(), { wrapper: wrapperFor() });
    await advance(0);

    await advance(TTL_MS - REFRESH_LEAD_MS - 1_000);
    expect(api.getMediaSession).toHaveBeenCalledTimes(1);

    await advance(1_500);
    expect(api.getMediaSession).toHaveBeenCalledTimes(2);
    expect(result.current.expiresAt).toBe(isoAfter(2 * TTL_MS));
  });

  it("keeps refreshing on every cycle", async () => {
    let calls = 0;
    api.getMediaSession.mockImplementation(() => {
      calls += 1;
      return Promise.resolve(cloudfrontSession(new Date(Date.now() + TTL_MS).toISOString()));
    });
    localStorage.clear();
    renderHook(() => useMediaSession(), { wrapper: wrapperFor() });
    await advance(0);

    await advance(TTL_MS - REFRESH_LEAD_MS + 1_000);
    await advance(TTL_MS - REFRESH_LEAD_MS + 1_000);

    expect(calls).toBe(3);
  });

  it("shares one refresh between players that mount the hook", async () => {
    api.getMediaSession
      .mockResolvedValueOnce(cloudfrontSession(isoAfter(TTL_MS)))
      .mockResolvedValue(cloudfrontSession(isoAfter(2 * TTL_MS)));
    const client = makeTestQueryClient();
    const first = renderHook(() => useMediaSession(), { wrapper: wrapperFor(client) });
    const second = renderHook(() => useMediaSession(), { wrapper: wrapperFor(client) });
    const third = renderHook(() => useMediaSession(), { wrapper: wrapperFor(client) });
    await advance(0);

    expect(api.getMediaSession).toHaveBeenCalledTimes(1);

    await advance(TTL_MS - REFRESH_LEAD_MS + 1_000);

    expect(api.getMediaSession).toHaveBeenCalledTimes(2);
    for (const player of [first, second, third]) {
      expect(player.result.current.expiresAt).toBe(isoAfter(2 * TTL_MS));
    }
  });

  it("does not refresh while the tab is hidden and refreshes when it becomes visible", async () => {
    api.getMediaSession
      .mockResolvedValueOnce(cloudfrontSession(isoAfter(TTL_MS)))
      .mockResolvedValueOnce(cloudfrontSession(isoAfter(3 * TTL_MS)));
    renderHook(() => useMediaSession(), { wrapper: wrapperFor() });
    await advance(0);

    act(() => {
      focusManager.setFocused(false);
    });
    await advance(TTL_MS + 5 * 60_000);
    expect(api.getMediaSession).toHaveBeenCalledTimes(1);

    act(() => {
      focusManager.setFocused(true);
    });
    await advance(0);
    expect(api.getMediaSession).toHaveBeenCalledTimes(2);
  });

  it("adopts a newer session written by another tab instead of calling the API", async () => {
    api.getMediaSession.mockResolvedValue(cloudfrontSession(isoAfter(TTL_MS)));
    const { result } = renderHook(() => useMediaSession(), { wrapper: wrapperFor() });
    await advance(0);

    localStorage.setItem(
      "mo-media-session",
      JSON.stringify(cloudfrontSession(isoAfter(2 * TTL_MS))),
    );
    await advance(TTL_MS - REFRESH_LEAD_MS + 1_000);

    expect(api.getMediaSession).toHaveBeenCalledTimes(1);
    expect(result.current.expiresAt).toBe(isoAfter(2 * TTL_MS));
  });

  it("ignores corrupt shared state and refreshes from the API", async () => {
    api.getMediaSession.mockResolvedValue(cloudfrontSession(isoAfter(TTL_MS)));
    renderHook(() => useMediaSession(), { wrapper: wrapperFor() });
    await advance(0);

    localStorage.setItem("mo-media-session", "{not json");
    await advance(TTL_MS - REFRESH_LEAD_MS + 1_000);

    expect(api.getMediaSession).toHaveBeenCalledTimes(2);
  });

  it("forces a refresh on demand and shares it between concurrent callers", async () => {
    api.getMediaSession
      .mockResolvedValueOnce(cloudfrontSession(isoAfter(TTL_MS)))
      .mockResolvedValue(cloudfrontSession(isoAfter(2 * TTL_MS)));
    const client = makeTestQueryClient();
    const first = renderHook(() => useMediaSession(), { wrapper: wrapperFor(client) });
    const second = renderHook(() => useMediaSession(), { wrapper: wrapperFor(client) });
    await advance(0);

    await act(async () => {
      await Promise.all([first.result.current.refresh(), second.result.current.refresh()]);
    });

    expect(api.getMediaSession).toHaveBeenCalledTimes(2);
    expect(first.result.current.expiresAt).toBe(isoAfter(2 * TTL_MS));
    expect(client.getQueryData(libraryKeys.mediaSession())).toEqual(
      cloudfrontSession(isoAfter(2 * TTL_MS)),
    );
  });

  it("does not fetch when disabled", async () => {
    renderHook(() => useMediaSession({ enabled: false }), { wrapper: wrapperFor() });
    await advance(TTL_MS);

    expect(api.getMediaSession).not.toHaveBeenCalled();
  });
});

describe("useMediaSession in presigned mode", () => {
  it("exposes the mode and never schedules a refresh", async () => {
    api.getMediaSession.mockResolvedValue(presignedSession);
    const { result } = renderHook(() => useMediaSession(), { wrapper: wrapperFor() });
    await advance(0);

    expect(result.current.mode).toBe("presigned");
    expect(result.current.expiresAt).toBeNull();
    expect(result.current.isReady).toBe(true);

    await advance(24 * TTL_MS);
    expect(api.getMediaSession).toHaveBeenCalledTimes(1);
  });

  it("reports a failed session start", async () => {
    api.getMediaSession.mockRejectedValue(new Error("down"));
    const { result } = renderHook(() => useMediaSession(), { wrapper: wrapperFor() });
    await advance(0);

    expect(result.current.isError).toBe(true);
    expect(result.current.isReady).toBe(false);
    expect(result.current.mode).toBeUndefined();
  });
});

describe("useRenditions", () => {
  it("returns the renditions without scheduling refreshes for cdn urls", async () => {
    api.listRenditions.mockResolvedValue({ items: [rendition()] });
    const { result } = renderHook(() => useRenditions(RENDER_ID), { wrapper: wrapperFor() });
    await advance(0);

    expect(result.current.data).toHaveLength(1);

    await advance(24 * TTL_MS);
    expect(api.listRenditions).toHaveBeenCalledTimes(1);
  });

  it("re-fetches the list before presigned urls expire", async () => {
    const signed = (at: Date) =>
      rendition({
        url: presignedUrl(at, 900),
        posterUrl: presignedUrl(at, 900, "poster-16x9.webp"),
        subtitlesUrl: presignedUrl(at, 900, "subtitles.vtt"),
      });
    api.listRenditions
      .mockResolvedValueOnce({ items: [signed(START)] })
      .mockImplementation(() => Promise.resolve({ items: [signed(new Date())] }));
    const { result } = renderHook(() => useRenditions(RENDER_ID), { wrapper: wrapperFor() });
    await advance(0);
    expect(api.listRenditions).toHaveBeenCalledTimes(1);

    await advance(900_000 - 60_000 - 5_000);
    expect(api.listRenditions).toHaveBeenCalledTimes(1);

    await advance(6_000);
    expect(api.listRenditions).toHaveBeenCalledTimes(2);
    expect(result.current.data?.[0]?.url).toContain("X-Amz-Date=20261020T10140");
  });

  it("does not fetch when disabled", async () => {
    renderHook(() => useRenditions(RENDER_ID, { enabled: false }), { wrapper: wrapperFor() });
    await advance(1_000);

    expect(api.listRenditions).not.toHaveBeenCalled();
  });
});
