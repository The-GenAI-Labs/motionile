import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { recordShareView } from "@/features/library/api/library.api";
import { SharedVideoPlayer } from "@/features/library/components/shared-video-player";
import type { SharedVideo } from "@/features/library/types/library.types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/features/library/api/library.api", () => ({ recordShareView: vi.fn() }));
vi.mock("@/features/library/components/lazy-video-player", async () => {
  const { VideoPlayer } = await import("@/features/library/components/video-player");
  return { LazyVideoPlayer: VideoPlayer };
});

const recorded = vi.mocked(recordShareView);

const video: SharedVideo = {
  allowIndexing: false,
  aspect: "16:9",
  durationMs: 62_000,
  height: 1080,
  language: "en",
  playbackExpiresInSeconds: 900,
  playbackUrl: "https://cdn.motionile.test/media/u/u1/r1/16x9.mp4?sig=abc",
  posterUrl: null,
  summary: null,
  title: "How DNS works",
  uploadedAt: "2026-10-01T10:00:00Z",
  width: 1920,
};

const player = (): HTMLVideoElement =>
  screen.getByLabelText("How DNS works", { selector: "video" });

beforeEach(() => {
  vi.clearAllMocks();
  recorded.mockResolvedValue(undefined);
});

describe("SharedVideoPlayer view counting", () => {
  it("counts nothing while the visitor has not pressed play", () => {
    render(<SharedVideoPlayer slug="abc123abc123" video={video} />);

    expect(recorded).not.toHaveBeenCalled();
  });

  it("records the view once when playback first starts", () => {
    render(<SharedVideoPlayer slug="abc123abc123" video={video} />);

    fireEvent.play(player());
    fireEvent.pause(player());
    fireEvent.play(player());
    fireEvent.play(player());

    expect(recorded).toHaveBeenCalledTimes(1);
    expect(recorded).toHaveBeenCalledWith("abc123abc123");
  });

  it("keeps playing and does not retry when the request fails", async () => {
    recorded.mockRejectedValue(new Error("offline"));
    render(<SharedVideoPlayer slug="abc123abc123" video={video} />);

    fireEvent.play(player());
    await Promise.resolve();
    fireEvent.play(player());

    expect(recorded).toHaveBeenCalledTimes(1);
    expect(player()).toBeInTheDocument();
  });
});
