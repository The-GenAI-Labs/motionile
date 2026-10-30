import * as contract from "@motionile/api-contract";

import {
  SKILLS_PAGE_SIZE,
  skillSlugSchema,
} from "@/features/admin-skills/schemas/admin-skills.schema";
import type { SkillFilters } from "@/features/admin-skills/types/admin-skills.types";
import { apiClient } from "@/lib/api/client";

const BASE = "/v1/admin/skills";

export const listSystemSkills = async (filters: SkillFilters, cursor?: string) =>
  contract.zAdminSkillsListSystemSkillsResponse.parse(
    (
      await apiClient.get<unknown>(BASE, {
        authenticated: true,
        params: contract.zAdminSkillsListSystemSkillsQuery.parse({
          ...filters,
          cursor,
          limit: SKILLS_PAGE_SIZE,
        }),
      })
    ).data,
  );

export const getSystemSkill = async (slug: string) =>
  contract.zAdminSkillsGetSystemSkillResponse.parse(
    (
      await apiClient.get<unknown>(`${BASE}/${skillSlugSchema.parse(slug)}`, {
        authenticated: true,
      })
    ).data,
  );

export const reseedSystemSkills = async () =>
  contract.zAdminSkillsReseedSystemSkillsResponse.parse(
    (await apiClient.post<unknown>(`${BASE}/reseed`, undefined, { authenticated: true })).data,
  );
