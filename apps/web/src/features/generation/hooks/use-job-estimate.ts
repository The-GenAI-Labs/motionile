"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { estimateJob } from "@/features/generation/api/generation.api";
import { generationKeys } from "@/features/generation/query-keys";
import {
  decodeEstimateSignature,
  ESTIMATE_DEBOUNCE_MS,
  estimateSignature,
} from "@/features/generation/schemas/generation.schema";
import type { EstimateInput } from "@/features/generation/types/generation.types";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";

export const ESTIMATE_STALE_MS = 15_000;

export const useJobEstimate = (input: EstimateInput) => {
  const signature = estimateSignature(input);
  const settled = useDebouncedValue(signature, ESTIMATE_DEBOUNCE_MS);
  const query = useQuery({
    queryKey: generationKeys.estimate(settled),
    queryFn: () => estimateJob(decodeEstimateSignature(settled)),
    placeholderData: keepPreviousData,
    staleTime: ESTIMATE_STALE_MS,
  });
  return {
    estimate: query.data,
    isPending: query.isPending,
    isError: query.isError,
    error: query.error,
    isSettling: settled !== signature || query.isFetching,
  };
};
