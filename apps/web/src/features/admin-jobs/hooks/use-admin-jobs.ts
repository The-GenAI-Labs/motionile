"use client";

import { useQuery } from "@tanstack/react-query";

import {
  getAdminJob,
  getJobAnalytics,
  listAdminJobs,
} from "@/features/admin-jobs/api/admin-jobs.api";
import { adminJobsKeys } from "@/features/admin-jobs/query-keys";
import type { AdminJobFilters, AnalyticsRange } from "@/features/admin-jobs/types/admin-jobs.types";
import { useCursorList } from "@/lib/query/use-cursor-list";

export const useAdminJobs = (filters: AdminJobFilters) =>
  useCursorList(adminJobsKeys.list(filters), (cursor) => listAdminJobs(filters, cursor));

export const useAdminJob = (jobId: string) =>
  useQuery({ queryKey: adminJobsKeys.detail(jobId), queryFn: () => getAdminJob(jobId) });

export const useJobAnalytics = (range: AnalyticsRange) =>
  useQuery({ queryKey: adminJobsKeys.analytics(range), queryFn: () => getJobAnalytics(range) });
