"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import {
  downloadReconciliationReport,
  getReconciliationRun,
  listReconciliationRuns,
} from "@/features/admin-billing/api/admin-billing.api";
import { adminBillingKeys } from "@/features/admin-billing/query-keys";
import type { RunFilters } from "@/features/admin-billing/types/admin-billing.types";
import { useCursorList } from "@/lib/query/use-cursor-list";
import { downloadTextFile } from "@/lib/utils/download";

export const reportFilename = (runId: string): string => `reconciliation-${runId}.json`;

export const useAdminRuns = (filters: RunFilters) =>
  useCursorList(adminBillingKeys.runList(filters), (cursor) =>
    listReconciliationRuns(filters, cursor),
  );

export const useAdminRun = (runId: string) =>
  useQuery({
    queryKey: adminBillingKeys.run(runId),
    queryFn: () => getReconciliationRun(runId),
  });

export const useDownloadReport = (runId: string) =>
  useMutation({
    mutationFn: async () => {
      const report = await downloadReconciliationReport(runId);
      downloadTextFile(reportFilename(runId), report, "application/json");
    },
  });
