import * as contract from "@motionile/api-contract";
import { z } from "zod";

import { buildEstimateRequest } from "@/features/generation/schemas/generation.schema";
import type {
  EstimateInput,
  JobFilters,
  Storyboard,
} from "@/features/generation/types/generation.types";
import { apiClient } from "@/lib/api/client";

export const IDEMPOTENCY_HEADER = "Idempotency-Key";
export const JOBS_PAGE_SIZE = 20;

const idempotencyKeySchema = z.string().regex(/^[\x21-\x7E]{1,255}$/);

const idempotencyHeaders = (key: string) => ({
  [IDEMPOTENCY_HEADER]: idempotencyKeySchema.parse(key),
});

const jobPath = (jobId: string): string => `/v1/jobs/${z.uuid().parse(jobId)}`;

export const listStyles = async () =>
  contract.zStylesListStylesResponse.parse(
    (await apiClient.get<unknown>("/v1/styles", { authenticated: true })).data,
  );

export const estimateJob = async (input: EstimateInput) =>
  contract.zJobsEstimateJobResponse.parse(
    (
      await apiClient.post<unknown>("/v1/jobs/estimate", buildEstimateRequest(input), {
        authenticated: true,
      })
    ).data,
  );

export const createJob = async (input: {
  request: z.output<typeof contract.zJobsCreateJobBody>;
  idempotencyKey: string;
}) =>
  contract.zJobsCreateJobResponse.parse(
    (
      await apiClient.post<unknown>("/v1/jobs", input.request, {
        authenticated: true,
        headers: idempotencyHeaders(input.idempotencyKey),
      })
    ).data,
  );

export const listJobs = async (filters: JobFilters, cursor?: string) =>
  contract.zJobsListJobsResponse.parse(
    (
      await apiClient.get<unknown>("/v1/jobs", {
        authenticated: true,
        params: contract.zJobsListJobsQuery.parse({
          ...filters,
          cursor,
          limit: JOBS_PAGE_SIZE,
        }),
      })
    ).data,
  );

export const getJob = async (jobId: string) =>
  contract.zJobsGetJobResponse.parse(
    (await apiClient.get<unknown>(jobPath(jobId), { authenticated: true })).data,
  );

export const getStoryboard = async (jobId: string) =>
  contract.zJobsGetStoryboardResponse.parse(
    (await apiClient.get<unknown>(`${jobPath(jobId)}/storyboard`, { authenticated: true })).data,
  );

export const updateStoryboard = async (
  jobId: string,
  input: { content: Storyboard; expectedVersion: number },
) =>
  contract.zJobsUpdateStoryboardResponse.parse(
    (
      await apiClient.put<unknown>(
        `${jobPath(jobId)}/storyboard`,
        contract.zJobsUpdateStoryboardBody.parse(input),
        { authenticated: true },
      )
    ).data,
  );

export const regenerateStoryboard = async (jobId: string, instructions: string) =>
  contract.zJobsRegenerateStoryboardResponse.parse(
    (
      await apiClient.post<unknown>(
        `${jobPath(jobId)}/storyboard/regenerate`,
        contract.zJobsRegenerateStoryboardBody.parse({ instructions }),
        { authenticated: true },
      )
    ).data,
  );

export const approveJob = async (jobId: string, expectedVersion: number) =>
  contract.zJobsApproveJobResponse.parse(
    (
      await apiClient.post<unknown>(
        `${jobPath(jobId)}/approve`,
        contract.zJobsApproveJobBody.parse({ expectedVersion }),
        { authenticated: true },
      )
    ).data,
  );

export const cancelJob = async (jobId: string) =>
  contract.zJobsCancelJobResponse.parse(
    (
      await apiClient.post<unknown>(`${jobPath(jobId)}/cancel`, undefined, {
        authenticated: true,
      })
    ).data,
  );

export const reviseJob = async (
  jobId: string,
  input: {
    body: z.input<typeof contract.zJobsReviseJobBody>;
    idempotencyKey: string;
  },
) =>
  contract.zJobsReviseJobResponse.parse(
    (
      await apiClient.post<unknown>(
        `${jobPath(jobId)}/revise`,
        contract.zJobsReviseJobBody.parse(input.body),
        { authenticated: true, headers: idempotencyHeaders(input.idempotencyKey) },
      )
    ).data,
  );

export const deleteJob = async (jobId: string): Promise<void> => {
  await apiClient.delete(jobPath(jobId), { authenticated: true });
};

export const createShareLink = async (
  jobId: string,
  body: z.input<typeof contract.zShareCreateShareLinkBody>,
) =>
  contract.zShareCreateShareLinkResponse.parse(
    (
      await apiClient.post<unknown>(
        `${jobPath(jobId)}/share`,
        contract.zShareCreateShareLinkBody.parse(body),
        { authenticated: true },
      )
    ).data,
  );

export const revokeShareLinks = async (jobId: string): Promise<void> => {
  await apiClient.delete(`${jobPath(jobId)}/share`, { authenticated: true });
};
