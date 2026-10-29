import type { SkillFilters } from "@/features/admin-skills/types/admin-skills.types";

export const adminSkillsKeys = {
  all: ["admin-skills"] as const,
  lists: () => [...adminSkillsKeys.all, "list"] as const,
  list: (filters: SkillFilters) => [...adminSkillsKeys.lists(), filters] as const,
  details: () => [...adminSkillsKeys.all, "detail"] as const,
  detail: (slug: string) => [...adminSkillsKeys.details(), slug] as const,
};
