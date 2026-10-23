"use client";

import { parseAsBoolean, parseAsString, useQueryStates } from "nuqs";

import { moodFilterSchema } from "@/features/admin-music/schemas/admin-music.schema";
import type { MusicFilters } from "@/features/admin-music/types/admin-music.types";

export const musicFilterParsers = {
  mood: parseAsString.withDefault(""),
  active: parseAsBoolean,
};

export const useMusicFilterState = () => useQueryStates(musicFilterParsers, { history: "replace" });

type MusicFilterState = ReturnType<typeof useMusicFilterState>[0];

export const toMusicFilters = (state: MusicFilterState, mood: string): MusicFilters => {
  const parsedMood = moodFilterSchema.safeParse(mood.toLowerCase());
  return {
    ...(parsedMood.success ? { mood: parsedMood.data } : {}),
    ...(state.active === null ? {} : { active: state.active }),
  };
};
