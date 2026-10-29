"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getSystemSkill,
  listSystemSkills,
  reseedSystemSkills,
} from "@/features/admin-skills/api/admin-skills.api";
import { adminSkillsKeys } from "@/features/admin-skills/query-keys";
import type { SkillFilters } from "@/features/admin-skills/types/admin-skills.types";
import { useCursorList } from "@/lib/query/use-cursor-list";

export const useSystemSkills = (filters: SkillFilters) =>
  useCursorList(adminSkillsKeys.list(filters), (cursor) => listSystemSkills(filters, cursor));

export const useSystemSkill = (slug: string) =>
  useQuery({ queryKey: adminSkillsKeys.detail(slug), queryFn: () => getSystemSkill(slug) });

export const useReseedSkills = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: reseedSystemSkills,
    onSuccess: () => client.invalidateQueries({ queryKey: adminSkillsKeys.all }),
  });
};
