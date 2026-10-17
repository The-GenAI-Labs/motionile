"use client";

import { useQuery } from "@tanstack/react-query";

import { analytics } from "@/features/admin/api/admin.api";
import { AnalyticsOverview } from "@/features/admin/components/analytics-overview";
import { adminKeys } from "@/features/admin/query-keys";

export function AnalyticsDashboard() {
  const query = useQuery({ queryKey: [...adminKeys.all, "analytics"], queryFn: analytics });
  if (query.isPending) return <p role="status">Loading analytics…</p>;
  if (query.isError)
    return (
      <p role="alert" className="text-destructive">
        Analytics could not be loaded.
      </p>
    );
  return <AnalyticsOverview data={query.data} />;
}
