"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approveJob,
  getStoryboard,
  regenerateStoryboard,
  updateStoryboard,
} from "@/features/generation/api/generation.api";
import { generationKeys } from "@/features/generation/query-keys";
import type { Storyboard } from "@/features/generation/types/generation.types";

export const useStoryboard = (jobId: string, enabled: boolean) =>
  useQuery({
    queryKey: generationKeys.storyboard(jobId),
    queryFn: () => getStoryboard(jobId),
    enabled,
    staleTime: 0,
  });

export const useSaveStoryboard = (jobId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { content: Storyboard; expectedVersion: number }) =>
      updateStoryboard(jobId, input),
    onSuccess: (view) => {
      client.setQueryData(generationKeys.storyboard(jobId), view);
    },
  });
};

export const useRegenerateStoryboard = (jobId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (instructions: string) => regenerateStoryboard(jobId, instructions),
    onSuccess: (job) => {
      client.setQueryData(generationKeys.job(jobId), job);
      void client.invalidateQueries({ queryKey: generationKeys.storyboard(jobId) });
    },
  });
};

export const useApproveJob = (jobId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (expectedVersion: number) => approveJob(jobId, expectedVersion),
    onSuccess: (job) => {
      client.setQueryData(generationKeys.job(jobId), job);
    },
  });
};
