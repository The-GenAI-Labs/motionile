"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";

import { creditsKeys } from "@/features/credits/query-keys";
import { createJob } from "@/features/generation/api/generation.api";
import { isRetryableSubmitError } from "@/features/generation/errors";
import { generationKeys } from "@/features/generation/query-keys";
import {
  buildCreateRequest,
  type CreateJobFormValues,
} from "@/features/generation/schemas/generation.schema";
import type { Job } from "@/features/generation/types/generation.types";

interface PendingAttempt {
  fingerprint: string;
  idempotencyKey: string;
}

export const useCreateJob = () => {
  const client = useQueryClient();
  const pendingAttempt = useRef<PendingAttempt | null>(null);
  const mutation = useMutation({ mutationFn: createJob });

  const submit = async (values: CreateJobFormValues): Promise<Job | null> => {
    const request = buildCreateRequest(values);
    const fingerprint = JSON.stringify(request);
    const previous = pendingAttempt.current;
    const idempotencyKey =
      previous?.fingerprint === fingerprint ? previous.idempotencyKey : crypto.randomUUID();
    pendingAttempt.current = { fingerprint, idempotencyKey };
    try {
      const job = await mutation.mutateAsync({ request, idempotencyKey });
      pendingAttempt.current = null;
      client.setQueryData(generationKeys.job(job.id), job);
      void client.invalidateQueries({ queryKey: generationKeys.jobs() });
      void client.invalidateQueries({ queryKey: creditsKeys.wallet() });
      return job;
    } catch (failure) {
      if (!isRetryableSubmitError(failure)) {
        pendingAttempt.current = null;
      }
      return null;
    }
  };

  return { submit, error: mutation.error, isSubmitting: mutation.isPending };
};
