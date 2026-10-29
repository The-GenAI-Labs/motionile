import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as sharePage from "@/app/(public)/v/[shareId]/page";
import { sharedRendition } from "@/features/library/components/shared-video-player";
import type { SharedVideo } from "@/features/library/types/library.types";
import { ApiError } from "@/lib/api/api-error";

const { notFound, loadSharedVideo, refresh } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
  loadSharedVideo: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({ notFound, useRouter: () => ({ refresh }) }));
vi.mock("@/features/library/api/share.server.api", () => ({ loadSharedVideo }));
vi.mock("@/features/library/components/lazy-video-player", () => ({
  LazyVideoPlayer: ({ title, renditions }: { title: string; renditions: { url?: string }[] }) => (
    <video aria-label={title} src={renditions[0]?.url} />
  ),
}));

const video = (overrides: Partial<SharedVideo> = {}): SharedVideo => ({
  allowIndexing: false,
  aspect: "16:9",
  durationMs: 62_000,
  height: 1080,
  language: "en",
  playbackExpiresInSeconds: 900,
  playbackUrl: "https://cdn.motionile.test/media/u/u1/r1/16x9.mp4?sig=abc",
  posterUrl: "https://cdn.motionile.test/media/u/u1/r1/poster.webp",
  summary: "A short tour of DNS lookups.",
  title: "How DNS works",
  width: 1920,
  ...overrides,
});

const params = (shareId = "abc123abc123") => ({ params: Promise.resolve({ shareId }) });

const metadataOf = async (shared: SharedVideo | null) => {
  loadSharedVideo.mockResolvedValue(shared);
  return sharePage.generateMetadata(params());
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("shared video metadata", () => {
  it("asks search engines not to index a link without indexing", async () => {
    const metadata = await metadataOf(video());

    expect(metadata.robots).toEqual({ index: false, follow: false });
    expect(metadata.alternates?.canonical).toBe("https://motionile.test/v/abc123abc123");
    expect(metadata.title).toBe("How DNS works");
    expect(metadata.description).toBe("A short tour of DNS lookups.");
  });

  it("allows indexing only when the owner opted in", async () => {
    const metadata = await metadataOf(video({ allowIndexing: true }));

    expect(metadata.robots).toEqual({ index: true, follow: true });
  });

  it("describes the video to social networks", async () => {
    const metadata = await metadataOf(video());

    expect(metadata.openGraph).toMatchObject({
      type: "video.other",
      url: "https://motionile.test/v/abc123abc123",
      videos: [
        {
          url: "https://cdn.motionile.test/media/u/u1/r1/16x9.mp4?sig=abc",
          secureUrl: "https://cdn.motionile.test/media/u/u1/r1/16x9.mp4?sig=abc",
          type: "video/mp4",
          width: 1920,
          height: 1080,
        },
      ],
      images: [{ url: "https://cdn.motionile.test/media/u/u1/r1/poster.webp" }],
    });
    expect(metadata.twitter).toMatchObject({
      card: "player",
      players: [
        {
          playerUrl: "https://motionile.test/v/abc123abc123",
          streamUrl: "https://cdn.motionile.test/media/u/u1/r1/16x9.mp4?sig=abc",
          width: 1920,
          height: 1080,
        },
      ],
    });
  });

  it("falls back to a generated description without a summary", async () => {
    const metadata = await metadataOf(video({ summary: null, posterUrl: null }));

    expect(metadata.description).toContain("How DNS works");
    expect(metadata.openGraph?.images).toEqual([
      expect.objectContaining({ url: "https://motionile.test/opengraph-image" }),
    ]);
  });

  it("keeps a missing link out of search engines", async () => {
    const metadata = await metadataOf(null);

    expect(metadata.robots).toEqual({ index: false, follow: false });
    expect(metadata.title).toBe("Video not found");
  });
});

describe("shared video page", () => {
  it("plays the video and invites visitors to make their own", async () => {
    loadSharedVideo.mockResolvedValue(video());
    render(await sharePage.default(params()));

    expect(screen.getByRole("heading", { level: 1, name: "How DNS works" })).toBeInTheDocument();
    expect(screen.getByText("A short tour of DNS lookups.")).toBeInTheDocument();
    expect(screen.getByLabelText("How DNS works", { selector: "video" })).toHaveAttribute(
      "src",
      "https://cdn.motionile.test/media/u/u1/r1/16x9.mp4?sig=abc",
    );
    expect(screen.getByRole("heading", { name: "Made with Motionile" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create your own video" })).toHaveAttribute(
      "href",
      "/register",
    );
    expect(screen.getByRole("link", { name: "Open Motionile" })).toHaveAttribute("href", "/create");
  });

  it("adds no structured data to a page that is not indexable", async () => {
    loadSharedVideo.mockResolvedValue(video());
    const { container } = render(await sharePage.default(params()));

    expect(container.querySelector('script[type="application/ld+json"]')).toBeNull();
  });

  it("adds VideoObject structured data to an indexable page", async () => {
    loadSharedVideo.mockResolvedValue(video({ allowIndexing: true }));
    const { container } = render(await sharePage.default(params()));

    const script = container.querySelector('script[type="application/ld+json"]');
    expect(JSON.parse(script?.textContent ?? "{}")).toMatchObject({
      "@type": "VideoObject",
      name: "How DNS works",
      description: "A short tour of DNS lookups.",
      thumbnailUrl: ["https://cdn.motionile.test/media/u/u1/r1/poster.webp"],
      duration: "PT1M2S",
      contentUrl: "https://cdn.motionile.test/media/u/u1/r1/16x9.mp4?sig=abc",
      embedUrl: "https://motionile.test/v/abc123abc123",
    });
  });

  it("responds with not found for a missing or revoked link", async () => {
    loadSharedVideo.mockResolvedValue(null);

    await expect(sharePage.default(params("gone-gone-gone"))).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
  });

  it("is rendered on every request because views are counted", () => {
    expect(sharePage.dynamic).toBe("force-dynamic");
  });

  it("surfaces unexpected failures instead of hiding them as not found", async () => {
    loadSharedVideo.mockRejectedValue(
      new ApiError({ kind: "http", status: 503, code: "x", title: "x", detail: null }),
    );

    await expect(sharePage.default(params())).rejects.toBeInstanceOf(ApiError);
  });
});

describe("shared rendition", () => {
  it("describes the single signed file for the player", () => {
    expect(sharedRendition("abc", video())).toMatchObject({
      id: "shared-abc",
      aspect: "16:9",
      status: "ready",
      url: "https://cdn.motionile.test/media/u/u1/r1/16x9.mp4?sig=abc",
      posterUrl: "https://cdn.motionile.test/media/u/u1/r1/poster.webp",
      burnedInSubtitles: false,
    });
  });
});
