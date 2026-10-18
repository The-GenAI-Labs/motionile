"use client";

import { useState } from "react";

import { createDataTableColumnHelper, DataTable } from "@/components/shared/data-table";
import { PagedTable } from "@/components/shared/paged-table";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { billingErrorMessage } from "@/features/billing/errors";
import { useDailyUsage, useUsageEntries } from "@/features/credits/hooks/use-credit-history";
import type { DailyUsage, UsageEntry } from "@/features/credits/types/credits.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatCredits, formatDate, formatDateTime, titleCase } from "@/lib/utils/format";

const entryColumn = createDataTableColumnHelper<UsageEntry>();

const entryColumns = [
  entryColumn.display({
    id: "date",
    header: "Date",
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  }),
  entryColumn.display({
    id: "stage",
    header: "Activity",
    cell: ({ row }) => titleCase(row.original.stage),
  }),
  entryColumn.display({
    id: "reference",
    header: "Used for",
    cell: ({ row }) => {
      if (row.original.jobId) {
        return "Video generation";
      }
      return row.original.publicationId ? "Publishing" : "-";
    },
  }),
  entryColumn.display({
    id: "credits",
    header: "Credits",
    cell: ({ row }) => <span className="font-mono">{formatCredits(row.original.credits)}</span>,
  }),
];

const dailyColumn = createDataTableColumnHelper<DailyUsage>();

const dailyColumns = [
  dailyColumn.display({
    id: "date",
    header: "Day",
    cell: ({ row }) => formatDate(row.original.date),
  }),
  dailyColumn.display({
    id: "credits",
    header: "Credits used",
    cell: ({ row }) => <span className="font-mono">{formatCredits(row.original.credits)}</span>,
  }),
  dailyColumn.display({
    id: "records",
    header: "Records",
    cell: ({ row }) => <span className="font-mono">{formatCredits(row.original.records)}</span>,
  }),
];

function UsageEntries() {
  const usage = useUsageEntries();
  return (
    <PagedTable
      caption="Credit usage"
      columns={entryColumns}
      rows={flattenCursorPages(usage.data?.pages)}
      getRowId={(entry) => entry.id}
      isPending={usage.isPending}
      errorMessage={usage.isError ? billingErrorMessage(usage.error) : null}
      onRetry={() => {
        void usage.refetch();
      }}
      emptyState="No credits have been used yet."
      hasNextPage={usage.hasNextPage}
      isFetchingNextPage={usage.isFetchingNextPage}
      fetchNextPage={usage.fetchNextPage}
    />
  );
}

function DailyTotals() {
  const daily = useDailyUsage();
  if (daily.isPending) {
    return <Skeleton role="status" aria-label="Loading daily usage" className="h-64" />;
  }
  if (daily.isError) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
        <p>{billingErrorMessage(daily.error)}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void daily.refetch();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }
  return (
    <DataTable
      caption="Daily credit usage for the last 30 days"
      columns={dailyColumns}
      data={daily.data.items}
      getRowId={(day) => day.date}
      emptyState="No credits were used in the last 30 days."
    />
  );
}

export function UsageView() {
  const [daily, setDaily] = useState(false);
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Switch id="usage-daily-totals" checked={daily} onCheckedChange={setDaily} />
        <Label htmlFor="usage-daily-totals">Daily totals</Label>
      </div>
      {daily ? <DailyTotals /> : <UsageEntries />}
    </div>
  );
}
