"use client";

import { zJobSource, zJobStatus } from "@motionile/api-contract";
import Link from "next/link";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import {
  FilterPanel,
  optionsFromValues,
  SelectFilter,
  TextFilter,
} from "@/components/shared/filter-fields";
import { PagedTable } from "@/components/shared/paged-table";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import { adminJobsErrorMessage } from "@/features/admin-jobs/errors";
import { useAdminJobs } from "@/features/admin-jobs/hooks/use-admin-jobs";
import { toJobFilters, useJobFilterState } from "@/features/admin-jobs/hooks/use-job-filters";
import { adminJobsPaths } from "@/features/admin-jobs/paths";
import type { AdminJobSummary } from "@/features/admin-jobs/types/admin-jobs.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatCredits, formatDateTime } from "@/lib/utils/format";

const column = createDataTableColumnHelper<AdminJobSummary>();

const columns = [
  column.display({
    id: "created",
    header: "Created",
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  }),
  column.display({
    id: "job",
    header: "Job",
    cell: ({ row }) => (
      <div className="flex max-w-72 flex-col">
        <Link
          href={adminJobsPaths.job(row.original.id)}
          className="truncate rounded-sm font-medium hover:underline focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
        >
          {row.original.query}
        </Link>
        <span className="font-mono text-xs text-muted-foreground">
          {row.original.id.slice(0, 8)}
          {row.original.parentJobId ? " (revision)" : ""}
        </span>
      </div>
    ),
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <div className="flex flex-col gap-1">
        <StatusBadge status={row.original.status} />
        {row.original.currentStage ? (
          <span className="font-mono text-xs text-muted-foreground">
            {row.original.currentStage}
          </span>
        ) : null}
        {row.original.errorCode ? (
          <span className="font-mono text-xs text-destructive">{row.original.errorCode}</span>
        ) : null}
      </div>
    ),
  }),
  column.display({
    id: "source",
    header: "Source",
    cell: ({ row }) => <span className="font-mono">{row.original.source}</span>,
  }),
  column.display({
    id: "credits",
    header: "Credits (estimated / charged)",
    cell: ({ row }) => (
      <span className="font-mono">
        {formatCredits(row.original.creditsEstimated)} /{" "}
        {row.original.creditsCharged === null ? "-" : formatCredits(row.original.creditsCharged)}
      </span>
    ),
  }),
  column.display({
    id: "user",
    header: "User",
    cell: ({ row }) => (
      <Link
        href={adminJobsPaths.user(row.original.userId)}
        className="rounded-sm font-mono text-xs hover:underline focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
      >
        {row.original.userId.slice(0, 8)}
      </Link>
    ),
  }),
];

export function JobsTable() {
  const [state, setState] = useJobFilterState();
  const jobs = useAdminJobs(toJobFilters(state));
  return (
    <div className="space-y-5">
      <FilterPanel
        label="Job filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <SelectFilter
          id="job-status"
          label="Status"
          value={state.status ?? ""}
          options={optionsFromValues(zJobStatus.options)}
          onChange={(value) => {
            const status = zJobStatus.safeParse(value);
            void setState({ status: status.success ? status.data : null });
          }}
        />
        <SelectFilter
          id="job-source"
          label="Source"
          value={state.source ?? ""}
          options={optionsFromValues(zJobSource.options)}
          onChange={(value) => {
            const source = zJobSource.safeParse(value);
            void setState({ source: source.success ? source.data : null });
          }}
        />
        <TextFilter
          id="job-user"
          label="User ID"
          value={state.user}
          onChange={(value) => void setState({ user: value.trim() || null })}
        />
        <TextFilter
          id="job-from"
          label="Created from"
          type="date"
          value={state.from}
          onChange={(value) => void setState({ from: value || null })}
        />
        <TextFilter
          id="job-to"
          label="Created to"
          type="date"
          value={state.to}
          onChange={(value) => void setState({ to: value || null })}
        />
      </FilterPanel>
      <PagedTable
        caption="Jobs"
        columns={columns}
        rows={flattenCursorPages(jobs.data?.pages)}
        getRowId={(job) => job.id}
        isPending={jobs.isPending}
        errorMessage={jobs.isError ? adminJobsErrorMessage(jobs.error) : null}
        onRetry={() => {
          void jobs.refetch();
        }}
        emptyState="No jobs match these filters."
        hasNextPage={jobs.hasNextPage}
        isFetchingNextPage={jobs.isFetchingNextPage}
        fetchNextPage={jobs.fetchNextPage}
      />
    </div>
  );
}
