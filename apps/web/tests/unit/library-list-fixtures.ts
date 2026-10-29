import type { JobSummary, LibraryItem } from "@/features/library/types/library.types";

import { landscape, portrait } from "./library-fixtures";

export const JOB_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8da001";

export const jobId = (index: number): string =>
  `0197c5a2-1b2c-7d3e-8f40-${String(index).padStart(12, "0")}`;

export const libraryItem = (overrides: Partial<LibraryItem> = {}): LibraryItem => ({
  jobId: JOB_ID,
  title: "How DNS works",
  query: "Explain how DNS resolves a domain name",
  durationMs: 62_000,
  aspects: ["16:9", "9:16"],
  thumbnailUrl: "https://cdn.motionile.test/media/u/u1/renders/r1/poster-16x9.webp",
  fallbackSceneIds: [],
  renditions: [landscape, portrait],
  shareSlug: null,
  createdAt: "2026-10-20T09:00:00.000Z",
  completedAt: "2026-10-20T09:05:00.000Z",
  ...overrides,
});

export const activeJob = (overrides: Partial<JobSummary> = {}): JobSummary => ({
  cancelRequestedAt: null,
  completedAt: null,
  createdAt: "2026-10-25T09:00:00.000Z",
  creditsCharged: null,
  creditsEstimated: 60,
  creditsReserved: 60,
  currentStage: "voice",
  errorCode: null,
  errorMessage: null,
  errorTitle: null,
  fallbackSceneIds: [],
  id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8db001",
  options: {
    aspects: ["16:9"],
    burnInSubtitles: false,
    durationSeconds: 30,
    language: "en",
    musicTrackId: null,
    reviewStoryboard: false,
    revision: null,
    style: "minimal-dark",
    subtitles: true,
    voiceId: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8dc001",
    voiceIsCloned: false,
  },
  parentJobId: null,
  query: "Explain TCP handshakes",
  renderId: null,
  source: "query",
  startedAt: "2026-10-25T09:00:05.000Z",
  status: "voicing",
  topicId: null,
  updatedAt: "2026-10-25T09:01:00.000Z",
  ...overrides,
});
