"use client";

import { zSkillLayer } from "@motionile/api-contract";
import { parseAsStringLiteral, useQueryStates } from "nuqs";

import type { SkillFilters } from "@/features/admin-skills/types/admin-skills.types";

export const skillFilterParsers = {
  layer: parseAsStringLiteral(zSkillLayer.options),
};

export const useSkillFilterState = () => useQueryStates(skillFilterParsers, { history: "replace" });

type SkillFilterState = ReturnType<typeof useSkillFilterState>[0];

export const toSkillFilters = (state: SkillFilterState): SkillFilters =>
  state.layer === null ? {} : { layer: state.layer };
