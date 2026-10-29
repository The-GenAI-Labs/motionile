import * as contract from "@motionile/api-contract";
import { z } from "zod";

import { ADMIN_JOBS_PAGE_SIZE } from "@/features/admin-jobs/schemas/admin-jobs.schema";
import type { AdminJobFilters, AnalyticsRange } from "@/features/admin-jobs/types/admin-jobs.types";
import { apiClient } from "@/lib/api/client";

const JOBS_PATH = "/v1/admin/jobs";
const ANALYTICS_PATH = "/v1/admin/analytics/jobs";

export const listAdminJobs = async (filters: AdminJobFilters, cursor?: string) =>
  contract.zAdminJobsListAdminJobsResponse.parse(
    (
      await apiClient.get<unknown>(JOBS_PATH, {
        authenticated: true,
        params: contract.zAdminJobsListAdminJobsQuery.parse({
          ...filters,
          cursor,
          limit: ADMIN_JOBS_PAGE_SIZE,
        }),
      })
    ).data,
  );

export const getAdminJob = async (jobId: string) =>
  contract.zAdminJobsGetAdminJobResponse.parse(
    (
      await apiClient.get<unknown>(`${JOBS_PATH}/${z.uuid().parse(jobId)}`, {
        authenticated: true,
      })
    ).data,
  );

export const getJobAnalytics = async (range: AnalyticsRange) =>
  contract.zAdminJobsGetJobAnalyticsResponse.parse(
    (
      await apiClient.get<unknown>(ANALYTICS_PATH, {
        authenticated: true,
        params: contract.zAdminJobsGetJobAnalyticsQuery.parse({
          dateFrom: range.from,
          dateTo: range.to,
        }),
      })
    ).data,
  );
