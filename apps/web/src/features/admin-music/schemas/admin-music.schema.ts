import { z } from "zod";

import type {
  MusicTrack,
  MusicUpdateInput,
  MusicUploadInput,
} from "@/features/admin-music/types/admin-music.types";

export const MUSIC_MAX_BYTES = 50 * 1024 * 1024;
export const MIN_BPM = 30;
export const MAX_BPM = 300;
export const MAX_TITLE_LENGTH = 120;
export const MAX_LICENSE_NAME_LENGTH = 120;
export const MAX_LICENSE_URL_LENGTH = 2000;
export const MAX_ATTRIBUTION_LENGTH = 500;
export const MOOD_PATTERN = /^[a-z][a-z0-9-]{1,39}$/;
export const HTTPS_URL_PATTERN = /^https:\/\/\S+$/;
const BPM_PATTERN = /^\d{1,3}$/;

export const MOOD_MESSAGE =
  "Use 2 to 40 lowercase letters, digits or hyphens, starting with a letter.";

const requiredText = (label: string, max: number) =>
  z
    .string()
    .trim()
    .min(1, `${label} is required.`)
    .max(max, `${label} must be at most ${String(max)} characters.`);

const bpmField = z
  .string()
  .trim()
  .superRefine((value, ctx) => {
    if (value === "") {
      return;
    }
    const bpm = Number(value);
    if (!BPM_PATTERN.test(value) || bpm < MIN_BPM || bpm > MAX_BPM) {
      ctx.addIssue({
        code: "custom",
        message: `Enter a whole number from ${String(MIN_BPM)} to ${String(MAX_BPM)}, or leave it empty.`,
      });
    }
  });

const fileField = z
  .custom<File>((value) => value instanceof File)
  .optional()
  .superRefine((file, ctx) => {
    if (file === undefined) {
      return;
    }
    if (file.size === 0) {
      ctx.addIssue({ code: "custom", message: "The file is empty." });
    } else if (file.size > MUSIC_MAX_BYTES) {
      ctx.addIssue({ code: "custom", message: "The file is larger than 50 MB." });
    }
  });

export const trackFormSchema = z.object({
  file: fileField,
  title: requiredText("Title", MAX_TITLE_LENGTH),
  mood: z.string().trim().regex(MOOD_PATTERN, MOOD_MESSAGE),
  bpm: bpmField,
  licenseName: requiredText("License name", MAX_LICENSE_NAME_LENGTH),
  licenseUrl: z
    .string()
    .trim()
    .max(MAX_LICENSE_URL_LENGTH, "The URL is too long.")
    .regex(HTTPS_URL_PATTERN, "Enter an https URL without spaces."),
  attributionText: z
    .string()
    .trim()
    .max(
      MAX_ATTRIBUTION_LENGTH,
      `Attribution must be at most ${String(MAX_ATTRIBUTION_LENGTH)} characters.`,
    ),
  activate: z.boolean(),
});

export type TrackFormValues = z.infer<typeof trackFormSchema>;

export const uploadFormSchema = trackFormSchema.superRefine((values, ctx) => {
  if (values.file === undefined) {
    ctx.addIssue({ code: "custom", path: ["file"], message: "Choose an audio file." });
  }
});

export const emptyTrackFormValues: TrackFormValues = {
  title: "",
  mood: "",
  bpm: "",
  licenseName: "",
  licenseUrl: "",
  attributionText: "",
  activate: false,
};

export const trackFormValues = (track: MusicTrack): TrackFormValues => ({
  title: track.title,
  mood: track.mood,
  bpm: String(track.bpm ?? ""),
  licenseName: track.licenseName,
  licenseUrl: track.licenseUrl,
  attributionText: track.attributionText ?? "",
  activate: track.isActive,
});

export const toUploadInput = (values: TrackFormValues): MusicUploadInput => {
  if (values.file === undefined) {
    throw new Error("An audio file is required.");
  }
  return {
    file: values.file,
    metadata: {
      title: values.title,
      mood: values.mood,
      ...(values.bpm === "" ? {} : { bpm: Number(values.bpm) }),
      licenseName: values.licenseName,
      licenseUrl: values.licenseUrl,
      ...(values.attributionText === "" ? {} : { attributionText: values.attributionText }),
      activate: values.activate,
    },
  };
};

export const toUpdateInput = (values: TrackFormValues, track: MusicTrack): MusicUpdateInput => {
  const bpm = values.bpm === "" ? null : Number(values.bpm);
  const attributionText = values.attributionText === "" ? null : values.attributionText;
  return {
    ...(values.title === track.title ? {} : { title: values.title }),
    ...(values.mood === track.mood ? {} : { mood: values.mood }),
    ...(bpm === (track.bpm ?? null) ? {} : { bpm }),
    ...(values.licenseName === track.licenseName ? {} : { licenseName: values.licenseName }),
    ...(values.licenseUrl === track.licenseUrl ? {} : { licenseUrl: values.licenseUrl }),
    ...(attributionText === (track.attributionText ?? null) ? {} : { attributionText }),
  };
};

export const hasUpdateChanges = (input: MusicUpdateInput): boolean => Object.keys(input).length > 0;

export const moodFilterSchema = z.string().trim().regex(MOOD_PATTERN);

export const isSecureLicenseUrl = (value: string): boolean => HTTPS_URL_PATTERN.test(value);
