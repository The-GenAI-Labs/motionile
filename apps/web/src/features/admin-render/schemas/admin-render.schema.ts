import { zAspect, zRenderStage, zRenderStatus } from "@motionile/api-contract";
import { z } from "zod";

import type {
  Aspect,
  RenderStage,
  RenderStatus,
} from "@/features/admin-render/types/admin-render.types";

export const COMPOSITION_MAX_BYTES = 4 * 1024 * 1024;
export const AUDIO_MAX_BYTES = 25 * 1024 * 1024;
export const MAX_SCENES = 60;
export const MAX_SCENE_TEXT_CHARS = 2_000;
export const MAX_TOTAL_TEXT_CHARS = 20_000;
export const MIN_FPS = 24;
export const MAX_FPS = 60;
export const DEFAULT_FPS = 30;
export const MAX_ASPECTS = 3;
export const SCENE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
export const FPS_PATTERN = /^\d{1,2}$/;

export const aspectValues = ["16:9", "9:16", "1:1"] as const satisfies readonly Aspect[];

export const aspectOptions = [
  { value: "16:9", label: "16:9 landscape" },
  { value: "9:16", label: "9:16 portrait" },
  { value: "1:1", label: "1:1 square" },
] as const satisfies readonly { value: Aspect; label: string }[];

export const renderStages = [
  "preparing",
  "voicing",
  "mixing",
  "capturing",
  "encoding",
  "finalizing",
] as const satisfies readonly RenderStage[];

export const stageLabels = {
  preparing: "Preparing",
  voicing: "Voicing",
  mixing: "Mixing audio",
  capturing: "Capturing frames",
  encoding: "Encoding",
  finalizing: "Finalizing",
} as const satisfies Record<RenderStage, string>;

export const terminalStatuses = [
  "completed",
  "failed",
  "cancelled",
] as const satisfies readonly RenderStatus[];

export const isTerminalStatus = (status: RenderStatus | null | undefined): boolean =>
  status !== null &&
  status !== undefined &&
  (terminalStatuses as readonly string[]).includes(status);

export const isActiveStatus = (status: RenderStatus | null | undefined): boolean =>
  status !== null && status !== undefined && !isTerminalStatus(status);

export const renderProgressEventSchema = z.object({
  renderId: z.uuid(),
  status: zRenderStatus,
  stage: zRenderStage.nullish(),
  progress: z.number().min(0).max(100),
  at: z.string(),
  errorCode: z.string().nullish(),
  errorMessage: z.string().nullish(),
});

export type RenderProgressEvent = z.output<typeof renderProgressEventSchema>;

export const validationIssueSchema = z.looseObject({
  code: z.string(),
  severity: z.enum(["error", "warning"]),
  kind: z.string().optional(),
  message: z.string(),
  scene: z.string().nullish(),
  timeMs: z.number().nullish(),
  aspect: z.string().nullish(),
  selector: z.string().nullish(),
});

export const validationReportSchema = z.looseObject({
  version: z.number().optional(),
  valid: z.boolean(),
  issues: z.array(validationIssueSchema),
  stats: z
    .looseObject({
      scenes: z.number().optional(),
      aspects: z.number().optional(),
      samples: z.number().optional(),
      durationMs: z.number().optional(),
    })
    .optional(),
});

export type ValidationIssue = z.output<typeof validationIssueSchema>;
export type ValidationReport = z.output<typeof validationReportSchema>;

export const parseValidationReport = (raw: unknown): ValidationReport | null => {
  const parsed = validationReportSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
};

export const sortIssues = (issues: readonly ValidationIssue[]): ValidationIssue[] =>
  issues.toSorted(
    (a, b) =>
      Number(a.severity === "warning") - Number(b.severity === "warning") ||
      (a.timeMs ?? 0) - (b.timeMs ?? 0),
  );

export interface StageTiming {
  stage: string;
  milliseconds: number;
}

export const parseStageTimings = (raw: unknown): StageTiming[] => {
  const parsed = z.record(z.string(), z.unknown()).safeParse(raw);
  if (!parsed.success) {
    return [];
  }
  const order = (stage: string): number => {
    const index = (renderStages as readonly string[]).indexOf(stage);
    return index === -1 ? renderStages.length : index;
  };
  return Object.entries(parsed.data)
    .flatMap(([stage, value]) =>
      typeof value === "number" && Number.isFinite(value) ? [{ stage, milliseconds: value }] : [],
    )
    .toSorted((a, b) => order(a.stage) - order(b.stage));
};

const fileSchema = z.custom<File>((value) => value instanceof File);

export const renderSceneSchema = z.object({
  sceneId: z.string(),
  text: z.string(),
  audio: fileSchema.optional(),
});

const choicesShape = {
  aspects: z
    .array(zAspect)
    .min(1, "Choose at least one aspect ratio.")
    .max(MAX_ASPECTS, "Choose at most three aspect ratios."),
  fps: z.string().trim(),
  musicTrackId: z.string(),
  subtitles: z.boolean(),
  burnInSubtitles: z.boolean(),
};

const refineChoices = (
  values: { fps: string; subtitles: boolean; burnInSubtitles: boolean },
  ctx: z.RefinementCtx,
): void => {
  const fps = Number(values.fps);
  if (!FPS_PATTERN.test(values.fps) || fps < MIN_FPS || fps > MAX_FPS) {
    ctx.addIssue({
      code: "custom",
      path: ["fps"],
      message: `Enter a whole number from ${String(MIN_FPS)} to ${String(MAX_FPS)}.`,
    });
  }
  if (values.burnInSubtitles && !values.subtitles) {
    ctx.addIssue({
      code: "custom",
      path: ["burnInSubtitles"],
      message: "Turn subtitles on to burn them in.",
    });
  }
};

export const compositionFileError = (file: File | undefined): string | null => {
  if (file === undefined) {
    return "Choose a composition HTML file.";
  }
  if (!file.name.toLowerCase().endsWith(".html")) {
    return "The composition must be an .html file.";
  }
  if (file.size === 0) {
    return "The file is empty.";
  }
  return file.size > COMPOSITION_MAX_BYTES ? "The file is larger than 4 MB." : null;
};

export const audioFileError = (file: File | undefined): string | null => {
  if (file === undefined) {
    return "Choose an audio file for this scene.";
  }
  if (file.type !== "" && !file.type.startsWith("audio/")) {
    return "The file is not audio.";
  }
  if (file.size === 0) {
    return "The file is empty.";
  }
  return file.size > AUDIO_MAX_BYTES ? "The file is larger than 25 MB." : null;
};

export const renderFormSchema = z
  .object({
    composition: fileSchema.optional(),
    mode: z.enum(["synthesize", "upload"]),
    voiceId: z.string(),
    scenes: z.array(renderSceneSchema),
    ...choicesShape,
  })
  .superRefine((values, ctx) => {
    const compositionError = compositionFileError(values.composition);
    if (compositionError !== null) {
      ctx.addIssue({ code: "custom", path: ["composition"], message: compositionError });
    } else if (values.scenes.length === 0) {
      ctx.addIssue({
        code: "custom",
        path: ["composition"],
        message: "The composition has no scenes. Mark each scene with a data-scene attribute.",
      });
    }
    refineChoices(values, ctx);
    if (values.scenes.length > MAX_SCENES) {
      ctx.addIssue({
        code: "custom",
        path: ["composition"],
        message: `A render has at most ${String(MAX_SCENES)} scenes.`,
      });
    }
    if (values.mode === "synthesize" && values.voiceId === "") {
      ctx.addIssue({ code: "custom", path: ["voiceId"], message: "Choose a voice." });
    }
    let total = 0;
    values.scenes.forEach((scene, index) => {
      const text = scene.text.trim();
      total += text.length;
      if (text.length > MAX_SCENE_TEXT_CHARS) {
        ctx.addIssue({
          code: "custom",
          path: ["scenes", index, "text"],
          message: `Use at most ${String(MAX_SCENE_TEXT_CHARS)} characters.`,
        });
      }
      if (values.mode === "synthesize" && text.length === 0) {
        ctx.addIssue({
          code: "custom",
          path: ["scenes", index, "text"],
          message: "Enter the narration for this scene.",
        });
      }
      if (values.mode === "upload") {
        const audioError = audioFileError(scene.audio);
        if (audioError !== null) {
          ctx.addIssue({ code: "custom", path: ["scenes", index, "audio"], message: audioError });
        }
      }
    });
    if (total > MAX_TOTAL_TEXT_CHARS) {
      ctx.addIssue({
        code: "custom",
        path: ["scenes"],
        message: `The narration may hold at most ${String(MAX_TOTAL_TEXT_CHARS)} characters in total.`,
      });
    }
  });

export type RenderFormValues = z.infer<typeof renderFormSchema>;

export const goldenFormSchema = z
  .object({ voiceId: z.string().min(1, "Choose a voice."), ...choicesShape })
  .superRefine(refineChoices);

export type GoldenFormValues = z.infer<typeof goldenFormSchema>;

export type ChoicesFormValues = Pick<
  RenderFormValues,
  "aspects" | "fps" | "musicTrackId" | "subtitles" | "burnInSubtitles" | "voiceId"
>;

export const emptyRenderFormValues = (): RenderFormValues => ({
  mode: "synthesize",
  scenes: [],
  voiceId: "",
  aspects: [...aspectValues],
  fps: String(DEFAULT_FPS),
  musicTrackId: "",
  subtitles: true,
  burnInSubtitles: false,
});

export const emptyGoldenFormValues = (): GoldenFormValues => ({
  voiceId: "",
  aspects: [...aspectValues],
  fps: String(DEFAULT_FPS),
  musicTrackId: "",
  subtitles: true,
  burnInSubtitles: false,
});
