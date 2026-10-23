import type { MediaSession, Rendition } from "@/features/library/types/library.types";

export const RENDER_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e01";

export const rendition = (overrides: Partial<Rendition> = {}): Rendition => ({
  id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e10",
  aspect: "16:9",
  width: 1920,
  height: 1080,
  durationMs: 42_000,
  status: "ready",
  burnedInSubtitles: false,
  url: "https://cdn.motionile.test/media/u/u1/renders/r1/16x9.mp4",
  posterUrl: "https://cdn.motionile.test/media/u/u1/renders/r1/poster-16x9.webp",
  posterJpegUrl: null,
  subtitlesUrl: "https://cdn.motionile.test/media/u/u1/renders/r1/subtitles.vtt",
  subtitlesSrtUrl: null,
  attribution: null,
  ...overrides,
});

export const landscape = rendition();

export const portrait = rendition({
  id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e11",
  aspect: "9:16",
  width: 1080,
  height: 1920,
  url: "https://cdn.motionile.test/media/u/u1/renders/r1/9x16.mp4",
  posterUrl: "https://cdn.motionile.test/media/u/u1/renders/r1/poster-9x16.webp",
});

export const square = rendition({
  id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e12",
  aspect: "1:1",
  width: 1080,
  height: 1080,
  url: "https://cdn.motionile.test/media/u/u1/renders/r1/1x1.mp4",
  posterUrl: "https://cdn.motionile.test/media/u/u1/renders/r1/poster-1x1.webp",
});

export const cloudfrontSession = (expiresAt: string): MediaSession => ({
  mode: "cloudfront",
  expiresAt,
});

export const presignedSession: MediaSession = { mode: "presigned", expiresAt: null };

export const amzDate = (date: Date): string =>
  date
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}Z$/, "Z");

export const presignedUrl = (signedAt: Date, expiresSeconds: number, name = "16x9.mp4"): string =>
  `http://localhost:9000/motionile/media/u/u1/renders/r1/${name}?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Date=${amzDate(signedAt)}&X-Amz-Expires=${String(expiresSeconds)}&X-Amz-Signature=abc`;
