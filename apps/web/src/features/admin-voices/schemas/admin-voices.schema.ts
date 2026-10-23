import { z } from "zod";

import type {
  AdminVoice,
  AdminVoiceUpdateInput,
} from "@/features/admin-voices/types/admin-voices.types";
import {
  LANGUAGE_PATTERN,
  MAX_LANGUAGE_LENGTH,
  MAX_VOICE_NAME_LENGTH,
} from "@/features/voices/schemas/voices.schema";

export const MAX_TAGS = 10;
export const MAX_TAG_LENGTH = 30;
export const TAG_PATTERN = /^[a-z0-9][a-z0-9 -]{0,29}$/;
export const TAG_MESSAGE =
  "Use up to 30 lowercase letters, digits, spaces or hyphens, starting with a letter or digit.";

export const normalizeTag = (value: string): string => value.trim().toLowerCase();

export const voiceEditSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Enter a name.")
    .max(MAX_VOICE_NAME_LENGTH, `Use at most ${String(MAX_VOICE_NAME_LENGTH)} characters.`),
  language: z
    .string()
    .trim()
    .max(MAX_LANGUAGE_LENGTH, "The language code is too long.")
    .regex(LANGUAGE_PATTERN, "Use a language code such as en or hi."),
  tags: z
    .array(z.string().regex(TAG_PATTERN, TAG_MESSAGE))
    .max(MAX_TAGS, `Use at most ${String(MAX_TAGS)} tags.`),
  exposed: z.boolean(),
});

export type VoiceEditValues = z.infer<typeof voiceEditSchema>;

export const editValuesFor = (voice: AdminVoice): VoiceEditValues => ({
  name: voice.name,
  language: voice.language,
  tags: voice.tags,
  exposed: voice.status === "ready",
});

const sameTags = (a: readonly string[], b: readonly string[]): boolean =>
  a.length === b.length && a.every((tag, index) => tag === b[index]);

export const toVoiceUpdate = (
  values: VoiceEditValues,
  voice: AdminVoice,
): AdminVoiceUpdateInput => ({
  ...(values.name === voice.name ? {} : { name: values.name }),
  ...(values.language === voice.language ? {} : { language: values.language }),
  ...(sameTags(values.tags, voice.tags) ? {} : { tags: values.tags }),
  ...(values.exposed === (voice.status === "ready")
    ? {}
    : { status: values.exposed ? ("ready" as const) : ("disabled" as const) }),
});

export const hasVoiceChanges = (input: AdminVoiceUpdateInput): boolean =>
  Object.keys(input).length > 0;

export const isExposed = (voice: AdminVoice): boolean => voice.status === "ready";

export const addTag = (
  tags: readonly string[],
  raw: string,
): { tags: string[]; error: string | null } => {
  const tag = normalizeTag(raw);
  if (tag === "") {
    return { tags: [...tags], error: null };
  }
  if (!TAG_PATTERN.test(tag)) {
    return { tags: [...tags], error: TAG_MESSAGE };
  }
  if (tags.includes(tag)) {
    return { tags: [...tags], error: `The tag ${tag} is already added.` };
  }
  if (tags.length >= MAX_TAGS) {
    return { tags: [...tags], error: `Use at most ${String(MAX_TAGS)} tags.` };
  }
  return { tags: [...tags, tag], error: null };
};
