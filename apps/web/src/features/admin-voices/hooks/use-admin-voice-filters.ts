"use client";

import { parseAsString, parseAsStringLiteral, useQueryStates } from "nuqs";

import type { AdminVoiceFilters } from "@/features/admin-voices/types/admin-voices.types";
import { LANGUAGE_PATTERN } from "@/features/voices/schemas/voices.schema";

export const voiceStatusValues = ["pending", "ready", "failed", "disabled"] as const;

export const adminVoiceFilterParsers = {
  status: parseAsStringLiteral(voiceStatusValues),
  language: parseAsString.withDefault(""),
};

export const useAdminVoiceFilterState = () =>
  useQueryStates(adminVoiceFilterParsers, { history: "replace" });

type AdminVoiceFilterState = ReturnType<typeof useAdminVoiceFilterState>[0];

export const toAdminVoiceFilters = (state: AdminVoiceFilterState): AdminVoiceFilters => ({
  ...(state.status === null ? {} : { status: state.status }),
  ...(LANGUAGE_PATTERN.test(state.language) ? { language: state.language } : {}),
});
