"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addCloneSample,
  getCloneAttempt,
  removeCloneSample,
  startClone,
  submitClone,
  uploadConsentRecording,
} from "@/features/voices/api/voices.api";
import { voiceKeys } from "@/features/voices/query-keys";
import type {
  AudioUploadInput,
  CloneAttempt,
  CloneSubmitInput,
} from "@/features/voices/types/voices.types";

export const useStartClone = () =>
  useMutation({ mutationFn: (statementVersion: string) => startClone(statementVersion) });

export const useCloneAttempt = (attemptId: string | null) =>
  useQuery({
    queryKey: voiceKeys.attempt(attemptId ?? "none"),
    queryFn: () => getCloneAttempt(attemptId ?? ""),
    enabled: attemptId !== null,
  });

const useStoreAttempt = (attemptId: string | null) => {
  const client = useQueryClient();
  return (attempt: CloneAttempt) => {
    if (attemptId !== null) {
      client.setQueryData(voiceKeys.attempt(attemptId), attempt);
    }
  };
};

export const useUploadConsentRecording = (attemptId: string | null) => {
  const store = useStoreAttempt(attemptId);
  return useMutation({
    mutationFn: (input: Omit<AudioUploadInput, "attemptId">) =>
      uploadConsentRecording({ ...input, attemptId: attemptId ?? "" }),
    onSuccess: store,
  });
};

export const useAddCloneSample = (attemptId: string | null) => {
  const store = useStoreAttempt(attemptId);
  return useMutation({
    mutationFn: (input: Omit<AudioUploadInput, "attemptId">) =>
      addCloneSample({ ...input, attemptId: attemptId ?? "" }),
    onSuccess: store,
  });
};

export const useRemoveCloneSample = (attemptId: string | null) => {
  const store = useStoreAttempt(attemptId);
  return useMutation({
    mutationFn: (sampleId: string) => removeCloneSample(attemptId ?? "", sampleId),
    onSuccess: store,
  });
};

export const useSubmitClone = (attemptId: string | null) => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: CloneSubmitInput) => submitClone(attemptId ?? "", input),
    onSuccess: () => client.invalidateQueries({ queryKey: voiceKeys.lists() }),
  });
};
