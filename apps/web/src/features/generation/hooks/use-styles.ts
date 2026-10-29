"use client";

import { useQuery } from "@tanstack/react-query";

import { listStyles } from "@/features/generation/api/generation.api";
import { generationKeys } from "@/features/generation/query-keys";

export const STYLES_STALE_MS = 300_000;

export const useStyles = () =>
  useQuery({
    queryKey: generationKeys.styles(),
    queryFn: listStyles,
    select: (list) => list.items,
    staleTime: STYLES_STALE_MS,
  });
