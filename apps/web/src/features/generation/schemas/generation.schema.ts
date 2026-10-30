import { zAspectName, zJobsCreateJobBody, zJobsEstimateJobBody } from "@motionile/api-contract";
import { z } from "zod";

import type {
  Aspect,
  EstimateInput,
  JobStatus,
} from "@/features/generation/types/generation.types";

export const DURATION_MIN_SECONDS = 10;
export const DURATION_MAX_SECONDS = 120;
export const DURATION_STEP_SECONDS = 5;
export const DEFAULT_DURATION_SECONDS = 60;
export const QUERY_MIN_CHARS = 3;
export const QUERY_MAX_CHARS = 2000;
export const INSTRUCTIONS_MAX_CHARS = 2000;
export const ESTIMATE_DEBOUNCE_MS = 400;
export const TOPIC_SEARCH_DEBOUNCE_MS = 300;
export const DEFAULT_STYLE_SLUG = "minimal-dark";
export const ALL_ASPECTS = ["16:9", "9:16", "1:1"] as const satisfies readonly Aspect[];

export const aspectChoices = [
  { value: "16:9", label: "16:9", description: "Landscape" },
  { value: "9:16", label: "9:16", description: "Portrait" },
  { value: "1:1", label: "1:1", description: "Square" },
] as const satisfies readonly { value: Aspect; label: string; description: string }[];

export const terminalStatuses = [
  "completed",
  "failed",
  "cancelled",
] as const satisfies readonly JobStatus[];

export const isTerminalStatus = (status: JobStatus | null | undefined): boolean =>
  status !== null &&
  status !== undefined &&
  (terminalStatuses as readonly string[]).includes(status);

export const createJobFormSchema = z
  .object({
    topicId: z.uuid().nullable(),
    topicTitle: z.string().nullable(),
    query: z.string().trim().max(QUERY_MAX_CHARS, "Keep the question under 2,000 characters."),
    durationSeconds: z
      .number()
      .int()
      .min(DURATION_MIN_SECONDS, "Choose at least 10 seconds.")
      .max(DURATION_MAX_SECONDS, "Choose at most 120 seconds."),
    aspects: z.array(zAspectName).min(1, "Choose at least one aspect ratio.").max(3),
    style: z.string().min(1, "Choose a style."),
    voiceId: z.uuid().nullable(),
    language: z.string().min(2, "Choose a language."),
    reviewStoryboard: z.boolean(),
    subtitles: z.boolean(),
    burnInSubtitles: z.boolean(),
  })
  .superRefine((values, context) => {
    if (values.topicId === null && values.query.length < QUERY_MIN_CHARS) {
      context.addIssue({
        code: "custom",
        path: ["query"],
        message: "Describe what the video should explain, or pick a topic.",
      });
    }
    if (values.burnInSubtitles && !values.subtitles) {
      context.addIssue({
        code: "custom",
        path: ["burnInSubtitles"],
        message: "Turn on subtitles to burn them into the video.",
      });
    }
  });

export type CreateJobFormValues = z.output<typeof createJobFormSchema>;

export const buildCreateRequest = (values: CreateJobFormValues) =>
  zJobsCreateJobBody.parse({
    topicId: values.topicId,
    query: values.topicId === null ? values.query : null,
    options: {
      durationSeconds: values.durationSeconds,
      aspects: values.aspects,
      style: values.style,
      voiceId: values.voiceId,
      language: values.language,
      reviewStoryboard: values.reviewStoryboard,
      subtitles: values.subtitles,
      burnInSubtitles: values.subtitles && values.burnInSubtitles,
    },
  });

export const estimateSignature = (input: EstimateInput): string =>
  `${String(input.durationSeconds)}|${input.aspects.toSorted().join(",")}|${input.voiceId ?? ""}`;

export const decodeEstimateSignature = (signature: string): EstimateInput => {
  const [seconds = "", aspects = "", voice = ""] = signature.split("|");
  return {
    durationSeconds: Number(seconds),
    aspects: z.array(zAspectName).parse(aspects.split(",")),
    voiceId: voice === "" ? null : voice,
  };
};

export const buildEstimateRequest = (input: EstimateInput) =>
  zJobsEstimateJobBody.parse({
    options: {
      durationSeconds: input.durationSeconds,
      aspects: input.aspects,
      voiceId: input.voiceId,
    },
  });

export const reviseFormSchema = z.object({
  instructions: z
    .string()
    .trim()
    .min(1, "Tell Motionile what to change.")
    .max(INSTRUCTIONS_MAX_CHARS, "Keep the instructions under 2,000 characters."),
  sceneIds: z.array(z.string()),
  overrideDuration: z.boolean(),
  durationSeconds: z.number().int().min(DURATION_MIN_SECONDS).max(DURATION_MAX_SECONDS),
  overrideStyle: z.boolean(),
  style: z.string(),
});

export type ReviseFormValues = z.output<typeof reviseFormSchema>;

export const regenerateFormSchema = z.object({
  instructions: z
    .string()
    .trim()
    .min(1, "Tell Motionile what to change.")
    .max(INSTRUCTIONS_MAX_CHARS, "Keep the instructions under 2,000 characters."),
});

export type RegenerateFormValues = z.output<typeof regenerateFormSchema>;

export const jobEventSchema = z.object({
  id: z.uuid().nullable(),
  type: z.string(),
  stage: z.string().nullable(),
  payload: z.record(z.string(), z.unknown()),
  at: z.iso.datetime({ offset: true }),
});

export type JobEvent = z.output<typeof jobEventSchema>;

export const TERMINAL_EVENT_TYPES = ["job.completed", "job.failed", "job.cancelled"] as const;

export const isTerminalEvent = (event: JobEvent): boolean =>
  (TERMINAL_EVENT_TYPES as readonly string[]).includes(event.type);

export const parseJobEvent = (raw: string): JobEvent | null => {
  try {
    const parsed = jobEventSchema.safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
};
