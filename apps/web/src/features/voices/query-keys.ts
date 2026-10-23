import type { VoiceFilters } from "@/features/voices/types/voices.types";

export const voiceKeys = {
  all: ["voices"] as const,
  lists: () => [...voiceKeys.all, "list"] as const,
  list: (filters: VoiceFilters) => [...voiceKeys.lists(), filters] as const,
  details: () => [...voiceKeys.all, "detail"] as const,
  detail: (voiceId: string) => [...voiceKeys.details(), voiceId] as const,
  previews: () => [...voiceKeys.all, "preview"] as const,
  preview: (voiceId: string) => [...voiceKeys.previews(), voiceId] as const,
  attempt: (attemptId: string) => [...voiceKeys.all, "attempt", attemptId] as const,
};
