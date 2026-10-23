import type { MusicTrack } from "@/features/admin-music/types/admin-music.types";

export const TRACK_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9f01";

export const musicTrack = (overrides: Partial<MusicTrack> = {}): MusicTrack => ({
  id: TRACK_ID,
  title: "Quiet Orbit",
  mood: "calm",
  bpm: 92,
  durationMs: 125_000,
  licenseName: "CC BY 4.0",
  licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
  attributionText: "Composed by Ada",
  isActive: true,
  audioAssetId: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9f02",
  previewUrl: "http://localhost:9000/motionile/music/quiet-orbit.m4a?X-Amz-Signature=abc",
  createdByUserId: null,
  createdAt: "2026-10-18T09:30:00.000Z",
  updatedAt: "2026-10-18T09:30:00.000Z",
  ...overrides,
});

export const inactiveTrack = musicTrack({
  id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9f03",
  title: "Neon Harbor",
  mood: "upbeat",
  bpm: null,
  isActive: false,
  attributionText: null,
  previewUrl: null,
});
