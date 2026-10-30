import type { AdminJobFilters, AnalyticsRange } from "@/features/admin-jobs/types/admin-jobs.types";

export const adminJobsKeys = {
  all: ["admin-jobs"] as const,
  lists: () => [...adminJobsKeys.all, "list"] as const,
  list: (filters: AdminJobFilters) => [...adminJobsKeys.lists(), filters] as const,
  details: () => [...adminJobsKeys.all, "detail"] as const,
  detail: (jobId: string) => [...adminJobsKeys.details(), jobId] as const,
  analytics: (range: AnalyticsRange) => [...adminJobsKeys.all, "analytics", range] as const,
};
