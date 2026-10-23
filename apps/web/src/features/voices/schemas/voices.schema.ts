import { z } from "zod";

export const voiceIdSchema = z.uuid();
export const attemptIdSchema = z.uuid();
export const sampleIdSchema = z.uuid();

export const MAX_VOICE_NAME_LENGTH = 80;
export const MAX_LANGUAGE_LENGTH = 35;
export const LANGUAGE_PATTERN = /^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$/;
export const AUDIO_ACCEPT = "audio/*";
export const IDEMPOTENCY_HEADER = "Idempotency-Key";

export const voiceLanguageOptions = [
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi" },
] as const;

export const cloneSubmitFormSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Enter a name for the voice.")
    .max(MAX_VOICE_NAME_LENGTH, `Use at most ${String(MAX_VOICE_NAME_LENGTH)} characters.`),
  language: z
    .string()
    .trim()
    .max(MAX_LANGUAGE_LENGTH, "The language code is too long.")
    .regex(LANGUAGE_PATTERN, "Choose the language you speak in the samples."),
});

export type CloneSubmitFormValues = z.infer<typeof cloneSubmitFormSchema>;

export const isAudioBlob = (blob: Blob): boolean =>
  blob.type === "" || blob.type.startsWith("audio/") || blob.type === "video/webm";

export const voiceTagsText = (tags: readonly string[]): string => tags.join(", ");

export const languageLabel = (language: string): string =>
  voiceLanguageOptions.find((option) => option.value === language)?.label ?? language;
