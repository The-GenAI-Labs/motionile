"use client";

import { useQuery } from "@tanstack/react-query";

import { resolveTopicReference } from "@/features/generation/api/topic-reference.api";
import { generationKeys } from "@/features/generation/query-keys";

export const TOPIC_REFERENCE_STALE_MS = 300_000;

export const useTopicReference = (reference: string | null) =>
  useQuery({
    queryKey: generationKeys.topicRef(reference ?? ""),
    queryFn: () => resolveTopicReference(reference ?? ""),
    enabled: reference !== null && reference !== "",
    staleTime: TOPIC_REFERENCE_STALE_MS,
  });
