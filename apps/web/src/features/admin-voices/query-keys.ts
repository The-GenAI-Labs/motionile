import type { AdminVoiceFilters } from "@/features/admin-voices/types/admin-voices.types";

export const adminVoiceKeys = {
  all: ["admin-voices"] as const,
  lists: () => [...adminVoiceKeys.all, "list"] as const,
  list: (filters: AdminVoiceFilters) => [...adminVoiceKeys.lists(), filters] as const,
};
