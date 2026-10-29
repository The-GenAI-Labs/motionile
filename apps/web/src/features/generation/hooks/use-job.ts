"use client";

import { skipToken, useQuery } from "@tanstack/react-query";

import { getJob } from "@/features/generation/api/generation.api";
import { generationKeys } from "@/features/generation/query-keys";
import { isTerminalStatus, type JobEvent } from "@/features/generation/schemas/generation.schema";

export const JOB_STALE_MS = 5_000;

const NO_EVENTS: readonly JobEvent[] = [];

interface UseJobOptions {
  pollMs?: number | false;
}

export const useJob = (jobId: string, { pollMs = false }: UseJobOptions = {}) =>
  useQuery({
    queryKey: generationKeys.job(jobId),
    queryFn: () => getJob(jobId),
    staleTime: JOB_STALE_MS,
    refetchInterval: (query) => (isTerminalStatus(query.state.data?.status) ? false : pollMs),
  });

export const useJobEventList = (jobId: string): readonly JobEvent[] => {
  const query = useQuery<readonly JobEvent[]>({
    queryKey: generationKeys.events(jobId),
    queryFn: skipToken,
    staleTime: Infinity,
  });
  return query.data ?? NO_EVENTS;
};
