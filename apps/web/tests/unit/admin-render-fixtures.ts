import type { RenderBed } from "@/features/admin-render/types/admin-render.types";

export const RENDER_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9a01";
export const BED_VOICE_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9a02";
export const BED_MUSIC_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9a03";

export const renderBed = (overrides: Partial<RenderBed> = {}): RenderBed => ({
  id: RENDER_ID,
  status: "capturing",
  stage: "capturing",
  progress: 40,
  source: "testbed",
  options: {},
  stageTimings: { preparing: 1200, voicing: 4100 },
  validationReport: null,
  errorCode: null,
  errorMessage: null,
  durationMs: null,
  startedAt: "2026-10-20T10:00:00Z",
  completedAt: null,
  cancelRequestedAt: null,
  createdAt: "2026-10-20T09:59:00Z",
  updatedAt: "2026-10-20T10:00:30Z",
  renditions: [],
  ...overrides,
});

export const completedBed = renderBed({
  status: "completed",
  stage: "finalizing",
  progress: 100,
  stageTimings: { preparing: 1200, capturing: 30_000 },
  validationReport: { version: 1, valid: true, issues: [], stats: { scenes: 2 } },
  renditions: [
    {
      id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9a10",
      aspect: "16:9",
      width: 1920,
      height: 1080,
      durationMs: 30_000,
      status: "ready",
      burnedInSubtitles: false,
      url: "https://cdn.motionile.test/16x9.mp4",
      posterUrl: "https://cdn.motionile.test/poster-16x9.webp",
      posterJpegUrl: null,
      subtitlesUrl: "https://cdn.motionile.test/subtitles.vtt",
      subtitlesSrtUrl: "https://cdn.motionile.test/subtitles.srt",
      attribution: null,
    },
  ],
});

export const failedBed = renderBed({
  status: "failed",
  progress: 55,
  errorCode: "validation_failed",
  errorMessage: "The composition has 2 validation errors.",
  validationReport: {
    version: 1,
    valid: false,
    issues: [
      {
        code: "empty_scene",
        severity: "warning",
        kind: "layout",
        message: "The middle of the scene is empty",
        scene: "outro",
        timeMs: 500,
        aspect: "1:1",
        selector: null,
      },
      {
        code: "font_too_small",
        severity: "error",
        kind: "layout",
        message: "Text is 24px; the minimum for 9:16 is 34px",
        scene: "intro",
        timeMs: 1800,
        aspect: "9:16",
        selector: "#footnote",
      },
    ],
    stats: { scenes: 2 },
  },
});

export const goldenCatalog = {
  items: [
    {
      name: "flow-diagram",
      title: "Flow diagram",
      description: "A diagram that builds one step at a time",
      language: "en",
      sceneIds: ["intro", "steps"],
      scenes: [
        { sceneId: "intro", text: "First." },
        { sceneId: "steps", text: "Second." },
      ],
    },
    {
      name: "kinetic-typography",
      title: "Kinetic typography",
      description: "Words appearing in sync with narration",
      language: "en",
      sceneIds: ["hook"],
      scenes: [{ sceneId: "hook", text: "Hello." }],
    },
  ],
};

export const bedMusic = {
  items: [
    {
      id: BED_MUSIC_ID,
      title: "Quiet Orbit",
      mood: "calm",
      bpm: 92,
      durationMs: 125_000,
      attribution: null,
    },
  ],
};
