import type { JobEvent } from "@/features/generation/schemas/generation.schema";
import type {
  Estimate,
  Job,
  StoryboardScene,
  StoryboardView,
  StyleOption,
} from "@/features/generation/types/generation.types";

export const JOB_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8da001";
export const RENDER_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8da002";
export const TOPIC_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8da003";
export const VOICE_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8da004";
export const CLONED_VOICE_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8da005";

export const job = (overrides: Partial<Job> = {}): Job => ({
  id: JOB_ID,
  status: "planning",
  source: "query",
  query: "How does a hash map work?",
  topicId: null,
  parentJobId: null,
  renderId: null,
  currentStage: "plan",
  creditsEstimated: 140,
  creditsReserved: 140,
  creditsCharged: null,
  errorCode: null,
  errorMessage: null,
  errorTitle: null,
  fallbackSceneIds: [],
  cancelRequestedAt: null,
  startedAt: "2026-10-25T10:00:00Z",
  completedAt: null,
  createdAt: "2026-10-25T09:59:00Z",
  updatedAt: "2026-10-25T10:00:00Z",
  options: {
    aspects: ["16:9"],
    burnInSubtitles: false,
    durationSeconds: 60,
    language: "en",
    musicTrackId: null,
    reviewStoryboard: true,
    revision: null,
    style: "minimal-dark",
    subtitles: true,
    voiceId: VOICE_ID,
    voiceIsCloned: false,
  },
  ...overrides,
});

export const event = (
  type: string,
  payload: Record<string, unknown> = {},
  index = 1,
  stage: string | null = null,
): JobEvent => ({
  id: `0197c5a2-1b2c-7d3e-8f40-5a6b7c8d${String(index).padStart(4, "0")}`,
  type,
  stage,
  payload,
  at: "2026-10-25T10:00:00Z",
});

export const styles: StyleOption[] = [
  {
    slug: "minimal-dark",
    name: "Minimal dark",
    description: "Quiet dark slides.",
    background: "#0b0b0f",
    surface: "#16161d",
    text: "#f2f2f5",
    accent: "#7c5cff",
  },
  {
    slug: "whiteboard",
    name: "Whiteboard",
    description: "Hand drawn on white.",
    background: "#ffffff",
    surface: "#eeeeee",
    text: "#111111",
    accent: "#ff5c5c",
  },
];

export const estimateView = (overrides: Partial<Estimate> = {}): Estimate => ({
  affordable: true,
  aspectCount: 1,
  availableCredits: 500,
  clonedVoice: false,
  credits: 140,
  parameters: {
    baseCredits: 20,
    clonedVoicePremium: 10,
    creditsPerSecond: 2,
    extraAspectPercent: 40,
  },
  seconds: 60,
  ...overrides,
});

export const scene = (
  index: number,
  overrides: Partial<StoryboardScene> = {},
): StoryboardScene => ({
  id: `s${String(index + 1)}`,
  position: index,
  goal: `Goal ${String(index + 1)}`,
  narration: "one two three four five six seven eight nine ten",
  visualBrief: `Brief ${String(index + 1)}`,
  onScreenText: ["Key idea"],
  targetDurationMs: 4000,
  layoutNotes: { "16:9": "Centered" },
  keyTerms: [],
  visualSkills: [],
  ...overrides,
});

export const storyboardView = (overrides: Partial<StoryboardView> = {}): StoryboardView => ({
  approved: false,
  version: 1,
  origin: "planner",
  updatedAt: "2026-10-25T10:00:00Z",
  issues: [],
  limits: {
    durationTolerancePercent: 10,
    maxScenes: 4,
    minScenes: 2,
    maxWordsPerSecond: 2.8,
    minWordsPerSecond: 2,
    nominalWordsPerSecond: 2.4,
    onScreenText: [{ aspect: "16:9", characters: 160 }],
  },
  content: {
    title: "Hash maps",
    summary: "How hash maps store values.",
    audienceLevel: "beginner",
    language: "en",
    targetDurationMs: 12_000,
    aspects: ["16:9"],
    styleSkill: "minimal-dark",
    version: 1,
    scenes: [scene(0), scene(1), scene(2)],
  },
  ...overrides,
});
