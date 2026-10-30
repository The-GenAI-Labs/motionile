import { zStoryboard } from "@motionile/api-contract";
import { z } from "zod";

import type {
  Aspect,
  Storyboard,
  StoryboardLimits,
  StoryboardScene,
} from "@/features/generation/types/generation.types";

export const MAX_ON_SCREEN_LINES = 6;
export const MAX_ON_SCREEN_LINE_CHARS = 120;
export const NEW_SCENE_SECONDS = 5;
export const DEFAULT_LAYOUT_NOTE = "Follow the visual brief for this aspect ratio.";
export const SCENE_ID_PATTERN = /^s(\d+)$/;

export const parseLines = (text: string): string[] =>
  text
    .split(/\r\n|\n|\r/)
    .map((line) => line.trim())
    .filter((line) => line !== "");

export const sceneDraftSchema = z.object({
  sceneId: z.string(),
  goal: z
    .string()
    .trim()
    .min(1, "Describe the goal of this scene.")
    .max(300, "Keep the goal under 300 characters."),
  narration: z
    .string()
    .trim()
    .min(1, "Write the narration for this scene.")
    .max(2000, "Keep the narration under 2,000 characters."),
  visualBrief: z
    .string()
    .trim()
    .min(1, "Describe what the scene should show.")
    .max(4000, "Keep the visual brief under 4,000 characters."),
  onScreenText: z.string().superRefine((text, context) => {
    const lines = parseLines(text);
    if (lines.length > MAX_ON_SCREEN_LINES) {
      context.addIssue({ code: "custom", message: "Use at most 6 lines of on-screen text." });
    }
    if (lines.some((line) => line.length > MAX_ON_SCREEN_LINE_CHARS)) {
      context.addIssue({
        code: "custom",
        message: "Keep each line of on-screen text under 120 characters.",
      });
    }
  }),
  durationSeconds: z
    .number({ error: "Enter a duration in seconds." })
    .min(1, "Use at least 1 second.")
    .max(120, "Use at most 120 seconds."),
});

export const storyboardDraftSchema = z.object({
  title: z
    .string()
    .trim()
    .min(1, "Give the video a title.")
    .max(120, "Keep the title under 120 characters."),
  summary: z
    .string()
    .trim()
    .min(1, "Summarise the video.")
    .max(600, "Keep the summary under 600 characters."),
  scenes: z
    .array(sceneDraftSchema)
    .min(2, "A storyboard needs at least 2 scenes.")
    .max(12, "A storyboard can have at most 12 scenes."),
});

export type SceneDraft = z.output<typeof sceneDraftSchema>;
export type StoryboardDraft = z.output<typeof storyboardDraftSchema>;

export const toDraft = (storyboard: Storyboard): StoryboardDraft => ({
  title: storyboard.title,
  summary: storyboard.summary,
  scenes: storyboard.scenes.map((scene) => ({
    sceneId: scene.id,
    goal: scene.goal,
    narration: scene.narration,
    visualBrief: scene.visualBrief,
    onScreenText: (scene.onScreenText ?? []).join("\n"),
    durationSeconds: scene.targetDurationMs / 1000,
  })),
});

const defaultLayoutNotes = (aspects: readonly Aspect[]): Record<string, string> =>
  Object.fromEntries(aspects.map((aspect) => [aspect, DEFAULT_LAYOUT_NOTE]));

export const toStoryboard = (base: Storyboard, draft: StoryboardDraft): Storyboard =>
  zStoryboard.parse({
    ...base,
    title: draft.title,
    summary: draft.summary,
    scenes: draft.scenes.map((scene, position): StoryboardScene => {
      const original = base.scenes.find((candidate) => candidate.id === scene.sceneId);
      return {
        id: scene.sceneId,
        position,
        goal: scene.goal,
        narration: scene.narration,
        visualBrief: scene.visualBrief,
        onScreenText: parseLines(scene.onScreenText),
        targetDurationMs: Math.round(scene.durationSeconds * 1000),
        layoutNotes: original?.layoutNotes ?? defaultLayoutNotes(base.aspects),
        keyTerms: original?.keyTerms ?? [],
        visualSkills: original?.visualSkills ?? [],
      };
    }),
  });

export const nextSceneId = (existing: readonly string[]): string => {
  const highest = existing.reduce((max, id) => {
    const match = SCENE_ID_PATTERN.exec(id);
    return match?.[1] === undefined ? max : Math.max(max, Number(match[1]));
  }, 0);
  return `s${String(highest + 1)}`;
};

export const newSceneDraft = (existing: readonly string[]): SceneDraft => ({
  sceneId: nextSceneId(existing),
  goal: "",
  narration: "",
  visualBrief: "",
  onScreenText: "",
  durationSeconds: NEW_SCENE_SECONDS,
});

export const wordCount = (text: string): number => {
  const trimmed = text.trim();
  return trimmed === "" ? 0 : trimmed.split(/\s+/).length;
};

export const spokenSeconds = (narration: string, limits: StoryboardLimits): number =>
  wordCount(narration) / limits.nominalWordsPerSecond;

export type RateVerdict = "ok" | "too_fast" | "too_slow";

export const rateVerdict = (
  narration: string,
  durationSeconds: number,
  limits: StoryboardLimits,
): RateVerdict => {
  const words = wordCount(narration);
  if (words === 0 || durationSeconds <= 0) {
    return "ok";
  }
  const rate = words / durationSeconds;
  if (rate > limits.maxWordsPerSecond) {
    return "too_fast";
  }
  return rate < limits.minWordsPerSecond ? "too_slow" : "ok";
};

export type TotalVerdict = "ok" | "too_long" | "too_short";

export const totalVerdict = (
  totalSeconds: number,
  requestedSeconds: number,
  tolerancePercent: number,
): TotalVerdict => {
  const tolerance = (requestedSeconds * tolerancePercent) / 100;
  if (totalSeconds > requestedSeconds + tolerance) {
    return "too_long";
  }
  return totalSeconds < requestedSeconds - tolerance ? "too_short" : "ok";
};

export const onScreenCharacterLimit = (
  limits: StoryboardLimits,
  aspects: readonly Aspect[],
): number | null => {
  const applicable = limits.onScreenText
    .filter((entry) => aspects.includes(entry.aspect))
    .map((entry) => entry.characters);
  return applicable.length === 0 ? null : Math.min(...applicable);
};

export const onScreenCharacters = (text: string): number =>
  parseLines(text).reduce((sum, line) => sum + line.length, 0);

export const totalSeconds = (scenes: readonly Pick<SceneDraft, "durationSeconds">[]): number =>
  scenes.reduce(
    (sum, scene) => sum + (Number.isFinite(scene.durationSeconds) ? scene.durationSeconds : 0),
    0,
  );

export const sceneIndexFromField = (field: string): number | null => {
  const match = /(?:^|\.)scenes\.(\d+)(?:\.|$)/.exec(field);
  return match?.[1] === undefined ? null : Number(match[1]);
};
