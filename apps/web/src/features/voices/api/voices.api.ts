import * as contract from "@motionile/api-contract";

import {
  attemptIdSchema,
  IDEMPOTENCY_HEADER,
  sampleIdSchema,
  voiceIdSchema,
} from "@/features/voices/schemas/voices.schema";
import type {
  AudioUploadInput,
  CloneSubmitInput,
  VoiceFilters,
} from "@/features/voices/types/voices.types";
import { apiClient } from "@/lib/api/client";

export const VOICES_PAGE_SIZE = 100;
export const VOICE_UPLOAD_TIMEOUT_MS = 120_000;

const BASE = "/v1/voices";

const uploadConfig = {
  authenticated: true,
  timeout: VOICE_UPLOAD_TIMEOUT_MS,
  headers: { "Content-Type": "multipart/form-data" },
} as const;

const audioForm = (file: Blob, filename: string): FormData => {
  const body = new FormData();
  body.set("file", file, filename);
  return body;
};

export const listVoices = async (filters: VoiceFilters, cursor?: string) =>
  contract.zVoicesListVoicesResponse.parse(
    (
      await apiClient.get<unknown>(BASE, {
        authenticated: true,
        params: contract.zVoicesListVoicesQuery.parse({
          ...filters,
          cursor,
          limit: VOICES_PAGE_SIZE,
        }),
      })
    ).data,
  );

export const getVoice = async (voiceId: string) =>
  contract.zVoicesGetVoiceResponse.parse(
    (
      await apiClient.get<unknown>(`${BASE}/${voiceIdSchema.parse(voiceId)}`, {
        authenticated: true,
      })
    ).data,
  );

export const getVoicePreview = async (voiceId: string) =>
  contract.zVoicesGetVoicePreviewResponse.parse(
    (
      await apiClient.get<unknown>(`${BASE}/${voiceIdSchema.parse(voiceId)}/preview`, {
        authenticated: true,
      })
    ).data,
  );

export const deleteVoice = async (voiceId: string): Promise<void> => {
  await apiClient.delete(`${BASE}/${voiceIdSchema.parse(voiceId)}`, { authenticated: true });
};

export const startClone = async (statementVersion: string) =>
  contract.zVoicesStartVoiceCloneResponse.parse(
    (
      await apiClient.post<unknown>(
        `${BASE}/clones`,
        contract.zVoicesStartVoiceCloneBody.parse({ statementVersion, accepted: true }),
        { authenticated: true },
      )
    ).data,
  );

export const getCloneAttempt = async (attemptId: string) =>
  contract.zVoicesGetVoiceCloneAttemptResponse.parse(
    (
      await apiClient.get<unknown>(`${BASE}/clones/${attemptIdSchema.parse(attemptId)}`, {
        authenticated: true,
      })
    ).data,
  );

export const uploadConsentRecording = async ({ attemptId, file, filename }: AudioUploadInput) =>
  contract.zVoicesReplaceConsentRecordingResponse.parse(
    (
      await apiClient.put<unknown>(
        `${BASE}/clones/${attemptIdSchema.parse(attemptId)}/consent-recording`,
        audioForm(file, filename),
        uploadConfig,
      )
    ).data,
  );

export const addCloneSample = async ({ attemptId, file, filename }: AudioUploadInput) =>
  contract.zVoicesAddCloneSampleResponse.parse(
    (
      await apiClient.post<unknown>(
        `${BASE}/clones/${attemptIdSchema.parse(attemptId)}/samples`,
        audioForm(file, filename),
        uploadConfig,
      )
    ).data,
  );

export const removeCloneSample = async (attemptId: string, sampleId: string) =>
  contract.zVoicesRemoveCloneSampleResponse.parse(
    (
      await apiClient.delete<unknown>(
        `${BASE}/clones/${attemptIdSchema.parse(attemptId)}/samples/${sampleIdSchema.parse(sampleId)}`,
        { authenticated: true },
      )
    ).data,
  );

export const submitClone = async (attemptId: string, input: CloneSubmitInput) =>
  contract.zVoicesSubmitVoiceCloneResponse.parse(
    (
      await apiClient.post<unknown>(
        `${BASE}/clones/${attemptIdSchema.parse(attemptId)}/submit`,
        contract.zVoicesSubmitVoiceCloneBody.parse({ name: input.name, language: input.language }),
        { authenticated: true, headers: { [IDEMPOTENCY_HEADER]: input.idempotencyKey } },
      )
    ).data,
  );
