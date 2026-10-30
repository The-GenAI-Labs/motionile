"use client";

import { parseAsString, useQueryStates } from "nuqs";

import { createDataTableColumnHelper, DataTable } from "@/components/shared/data-table";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { DailyBarChart } from "@/features/admin-billing/components/daily-bar-chart";
import { DateRangeControl } from "@/features/admin-billing/components/date-range-control";
import { DetailSection } from "@/features/admin-billing/components/detail-section";
import {
  defaultDateRange,
  isValidDateRange,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import { adminJobsErrorMessage } from "@/features/admin-jobs/errors";
import { useJobAnalytics } from "@/features/admin-jobs/hooks/use-admin-jobs";
import { formatMicrosUsd, formatRate } from "@/features/admin-jobs/schemas/admin-jobs.schema";
import type { JobAnalytics } from "@/features/admin-jobs/types/admin-jobs.types";
import { formatCredits } from "@/lib/utils/format";

type DayOutcome = JobAnalytics["days"][number];
type StageDuration = JobAnalytics["stages"][number];

const dayColumn = createDataTableColumnHelper<DayOutcome>();

const dayColumns = [
  dayColumn.display({ id: "day", header: "Day", cell: ({ row }) => row.original.day }),
  dayColumn.display({
    id: "completed",
    header: "Completed",
    cell: ({ row }) => <span className="font-mono">{row.original.completed}</span>,
  }),
  dayColumn.display({
    id: "failed",
    header: "Failed",
    cell: ({ row }) => <span className="font-mono">{row.original.failed}</span>,
  }),
  dayColumn.display({
    id: "cancelled",
    header: "Cancelled",
    cell: ({ row }) => <span className="font-mono">{row.original.cancelled}</span>,
  }),
  dayColumn.display({
    id: "success",
    header: "Success rate",
    cell: ({ row }) => <span className="font-mono">{formatRate(row.original.successRate)}</span>,
  }),
];

const stageColumn = createDataTableColumnHelper<StageDuration>();

const stageColumns = [
  stageColumn.display({
    id: "stage",
    header: "Stage",
    cell: ({ row }) => <span className="font-mono">{row.original.stage}</span>,
  }),
  stageColumn.display({
    id: "average",
    header: "Average time",
    cell: ({ row }) => (
      <span className="font-mono">{row.original.averageSeconds.toFixed(1)} s</span>
    ),
  }),
  stageColumn.display({
    id: "samples",
    header: "Samples",
    cell: ({ row }) => <span className="font-mono">{formatCredits(row.original.samples)}</span>,
  }),
];

const costOverCharge = (analytics: JobAnalytics): string => {
  const cost = analytics.averageCostMicrosUsd;
  const charged = analytics.averageCreditsCharged;
  if (cost === null || charged === null) {
    return "No data";
  }
  return `${formatMicrosUsd(cost)} cost, ${charged.toFixed(1)} credits charged`;
};

export function JobsAnalyticsView({ data }: { data: JobAnalytics }) {
  const summary = [
    { label: "Success rate", value: formatRate(data.successRate) },
    { label: "Scenes repaired", value: formatRate(data.repairRate) },
    { label: "Scenes on fallback", value: formatRate(data.fallbackRate) },
    { label: "Scenes generated", value: formatCredits(data.scenes) },
    { label: "Average cost versus charged", value: costOverCharge(data) },
  ];
  return (
    <div className="space-y-5">
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {summary.map((item) => (
          <div key={item.label}>
            <dt className="text-sm text-muted-foreground">{item.label}</dt>
            <dd className="font-mono text-lg font-semibold">{item.value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-sm text-muted-foreground">
        {data.dateFrom} to {data.dateTo}.
      </p>
      <DailyBarChart
        title="Jobs per day"
        days={data.days.map((day) => day.day)}
        formatValue={formatCredits}
        series={[
          {
            key: "completed",
            label: "Completed",
            swatchClassName: "bg-success",
            barClassName: "fill-success",
            values: data.days.map((day) => day.completed),
          },
          {
            key: "failed",
            label: "Failed",
            swatchClassName: "bg-destructive",
            barClassName: "fill-destructive",
            values: data.days.map((day) => day.failed),
          },
          {
            key: "cancelled",
            label: "Cancelled",
            swatchClassName: "bg-muted-foreground",
            barClassName: "fill-muted-foreground",
            values: data.days.map((day) => day.cancelled),
          },
        ]}
      />
      <div className="grid gap-5 lg:grid-cols-2">
        <DataTable
          caption="Outcomes per day"
          columns={dayColumns}
          data={[...data.days].reverse()}
          getRowId={(day) => day.day}
          maxHeight={320}
        />
        <DataTable
          caption="Average time per stage"
          columns={stageColumns}
          data={data.stages}
          getRowId={(stage) => stage.stage}
          emptyState="No stage timings in this range."
          maxHeight={320}
        />
      </div>
    </div>
  );
}

const rangeParsers = {
  statsFrom: parseAsString.withDefault(""),
  statsTo: parseAsString.withDefault(""),
};

export function JobsAnalyticsPanel() {
  const [params, setParams] = useQueryStates(rangeParsers, { history: "replace" });
  const fallback = defaultDateRange();
  const from = params.statsFrom === "" ? fallback.from : params.statsFrom;
  const to = params.statsTo === "" ? fallback.to : params.statsTo;
  const range = isValidDateRange(from, to) ? { from, to } : fallback;
  const analytics = useJobAnalytics(range);
  return (
    <div className="space-y-4">
      <DateRangeControl
        from={from}
        to={to}
        onChange={(next) => {
          void setParams({ statsFrom: next.from, statsTo: next.to });
        }}
      />
      <DetailSection title="Generation analytics">
        {analytics.isPending ? (
          <Skeleton
            role="status"
            aria-hidden={false}
            aria-label="Loading job analytics"
            className="h-64"
          />
        ) : analytics.isError ? (
          <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-destructive">
            <p>{adminJobsErrorMessage(analytics.error)}</p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void analytics.refetch();
              }}
            >
              Try again
            </Button>
          </div>
        ) : (
          <JobsAnalyticsView data={analytics.data} />
        )}
      </DetailSection>
    </div>
  );
}
