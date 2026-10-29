"use client";

import type { zJobsReviseJobBody } from "@motionile/api-contract";
import { type QueryClient, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import type { z } from "zod";

import { creditsKeys } from "@/features/credits/query-keys";
import {
  cancelJob,
  createShareLink,
  deleteJob,
  reviseJob,
  revokeShareLinks,
} from "@/features/generation/api/generation.api";
import { isRetryableSubmitError } from "@/features/generation/errors";
import { generationKeys } from "@/features/generation/query-keys";
import type { Aspect, Job } from "@/features/generation/types/generation.types";
import { libraryKeys } from "@/features/library/query-keys";

const invalidateLibrary = (client: QueryClient) =>
  Promise.all([
    client.invalidateQueries({ queryKey: libraryKeys.lists() }),
    client.invalidateQueries({ queryKey: libraryKeys.recent() }),
    client.invalidateQueries({ queryKey: libraryKeys.activeJobs() }),
  ]);

export const useCancelJob = (jobId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => cancelJob(jobId),
    onSuccess: (job) => {
      client.setQueryData(generationKeys.job(jobId), job);
      void client.invalidateQueries({ queryKey: generationKeys.jobs() });
      void client.invalidateQueries({ queryKey: creditsKeys.wallet() });
      void invalidateLibrary(client);
    },
  });
};

export const useDeleteJob = (jobId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => deleteJob(jobId),
    onSuccess: () => {
      client.removeQueries({ queryKey: generationKeys.job(jobId) });
      client.removeQueries({ queryKey: generationKeys.events(jobId) });
      void client.invalidateQueries({ queryKey: generationKeys.jobs() });
      void invalidateLibrary(client);
    },
  });
};

type ReviseBody = z.input<typeof zJobsReviseJobBody>;

interface PendingRevision {
  fingerprint: string;
  idempotencyKey: string;
}

export const useReviseJob = (jobId: string) => {
  const client = useQueryClient();
  const pendingAttempt = useRef<PendingRevision | null>(null);
  const mutation = useMutation({
    mutationFn: (input: { body: ReviseBody; idempotencyKey: string }) => reviseJob(jobId, input),
  });

  const submit = async (body: ReviseBody): Promise<Job | null> => {
    const fingerprint = JSON.stringify(body);
    const previous = pendingAttempt.current;
    const idempotencyKey =
      previous?.fingerprint === fingerprint ? previous.idempotencyKey : crypto.randomUUID();
    pendingAttempt.current = { fingerprint, idempotencyKey };
    try {
      const job = await mutation.mutateAsync({ body, idempotencyKey });
      pendingAttempt.current = null;
      client.setQueryData(generationKeys.job(job.id), job);
      void client.invalidateQueries({ queryKey: generationKeys.jobs() });
      void client.invalidateQueries({ queryKey: creditsKeys.wallet() });
      void invalidateLibrary(client);
      return job;
    } catch (failure) {
      if (!isRetryableSubmitError(failure)) {
        pendingAttempt.current = null;
      }
      return null;
    }
  };

  return { submit, error: mutation.error, isSubmitting: mutation.isPending, reset: mutation.reset };
};

export const useCreateShare = (jobId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { aspect: Aspect; allowIndexing: boolean }) =>
      createShareLink(jobId, input),
    onSuccess: () => invalidateLibrary(client),
  });
};

export const useRevokeShare = (jobId: string) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => revokeShareLinks(jobId),
    onSuccess: () => invalidateLibrary(client),
  });
};
