import { z } from "zod";

import {
  aspectValues,
  type GoldenFormValues,
  type RenderFormValues,
} from "@/features/admin-render/schemas/admin-render.schema";

export const COMPOSITION_FIELD = "composition";
export const OPTIONS_FIELD = "options";

const choicesSchema = z.object({
  aspects: z.array(z.enum(aspectValues)).min(1).max(3),
  fps: z.number().int().min(24).max(60),
  musicTrackId: z.uuid().nullable(),
  subtitles: z.boolean(),
  burnInSubtitles: z.boolean(),
});

const synthesizeNarrationSchema = z.object({
  mode: z.literal("synthesize"),
  voiceId: z.uuid(),
  scenes: z
    .array(z.object({ sceneId: z.string().min(1), text: z.string().min(1).max(2000) }))
    .min(1)
    .max(60),
});

const uploadNarrationSchema = z.object({
  mode: z.literal("upload"),
  scenes: z
    .array(
      z.object({
        sceneId: z.string().min(1),
        audioPart: z.string().min(1).max(64),
        text: z.string().min(1).max(2000).optional(),
      }),
    )
    .min(1)
    .max(60),
});

export const renderOptionsRequestSchema = choicesSchema.extend({
  narration: z.discriminatedUnion("mode", [synthesizeNarrationSchema, uploadNarrationSchema]),
});

export const goldenRequestSchema = choicesSchema.extend({ voiceId: z.uuid() });

export type RenderOptionsRequest = z.output<typeof renderOptionsRequestSchema>;
export type GoldenRequest = z.output<typeof goldenRequestSchema>;

export const audioPartName = (index: number): string => `audio-${String(index)}`;

const choicesFrom = (values: GoldenFormValues | RenderFormValues) => ({
  aspects: values.aspects,
  fps: Number(values.fps),
  musicTrackId: values.musicTrackId === "" ? null : values.musicTrackId,
  subtitles: values.subtitles,
  burnInSubtitles: values.subtitles && values.burnInSubtitles,
});

export const buildRenderOptions = (values: RenderFormValues): RenderOptionsRequest =>
  renderOptionsRequestSchema.parse({
    ...choicesFrom(values),
    narration:
      values.mode === "synthesize"
        ? {
            mode: "synthesize",
            voiceId: values.voiceId,
            scenes: values.scenes.map((scene) => ({
              sceneId: scene.sceneId,
              text: scene.text.trim(),
            })),
          }
        : {
            mode: "upload",
            scenes: values.scenes.map((scene, index) => ({
              sceneId: scene.sceneId,
              audioPart: audioPartName(index),
              ...(scene.text.trim() === "" ? {} : { text: scene.text.trim() }),
            })),
          },
  });

export const buildTestbedForm = (values: RenderFormValues): FormData => {
  const composition = values.composition;
  if (composition === undefined) {
    throw new Error("A composition file is required.");
  }
  const body = new FormData();
  body.set(COMPOSITION_FIELD, composition, composition.name);
  body.set(OPTIONS_FIELD, JSON.stringify(buildRenderOptions(values)));
  if (values.mode === "upload") {
    values.scenes.forEach((scene, index) => {
      if (scene.audio === undefined) {
        throw new Error(`Audio is required for scene ${scene.sceneId}.`);
      }
      body.set(audioPartName(index), scene.audio, scene.audio.name);
    });
  }
  return body;
};

export const buildGoldenRequest = (values: GoldenFormValues): GoldenRequest =>
  goldenRequestSchema.parse({ ...choicesFrom(values), voiceId: values.voiceId });
