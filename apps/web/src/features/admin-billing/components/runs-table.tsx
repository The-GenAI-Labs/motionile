"use client";

import { zRunStatusName, zRunTypeName } from "@motionile/api-contract";
import Link from "next/link";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import { PagedTable } from "@/components/shared/paged-table";
import { Badge } from "@/components/ui/badge";
import {
  BOOLEAN_OPTIONS,
  booleanFromValue,
  FilterPanel,
  optionsFromValues,
  SelectFilter,
  valueFromBoolean,
} from "@/features/admin-billing/components/filter-fields";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import {
  toRunFilters,
  useRunFilterState,
} from "@/features/admin-billing/hooks/use-admin-billing-filters";
import { useAdminRuns } from "@/features/admin-billing/hooks/use-admin-reconciliation";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import { runTypeLabels } from "@/features/admin-billing/schemas/admin-billing.schema";
import type { AdminRun } from "@/features/admin-billing/types/admin-billing.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatCredits, formatDateTime } from "@/lib/utils/format";

const column = createDataTableColumnHelper<AdminRun>();

const columns = [
  column.display({
    id: "started",
    header: "Started",
    cell: ({ row }) => (
      <Link href={adminBillingPaths.run(row.original.id)} className="font-medium hover:underline">
        {formatDateTime(row.original.startedAt)}
      </Link>
    ),
  }),
  column.display({
    id: "type",
    header: "Run",
    cell: ({ row }) => runTypeLabels[row.original.type],
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => <StatusBadge status={row.original.status} />,
  }),
  column.display({
    id: "checked",
    header: "Checked",
    cell: ({ row }) => (
      <span className="font-mono">{formatCredits(row.original.checkedCount)}</span>
    ),
  }),
  column.display({
    id: "mismatches",
    header: "Mismatches",
    cell: ({ row }) =>
      row.original.mismatchCount > 0 ? (
        <Badge variant="destructive">{formatCredits(row.original.mismatchCount)}</Badge>
      ) : (
        <span className="font-mono">0</span>
      ),
  }),
  column.display({
    id: "repaired",
    header: "Repaired",
    cell: ({ row }) => (
      <span className="font-mono">{formatCredits(row.original.repairedCount)}</span>
    ),
  }),
  column.display({
    id: "report",
    header: "Report",
    cell: ({ row }) => (row.original.hasReport ? "Available" : "None"),
  }),
];

export function RunsTable() {
  const [state, setState] = useRunFilterState();
  const runs = useAdminRuns(toRunFilters(state));
  return (
    <div className="space-y-5">
      <FilterPanel
        label="Reconciliation filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <SelectFilter
          id="run-type"
          label="Run type"
          value={state.type ?? ""}
          options={optionsFromValues(zRunTypeName.options, runTypeLabels)}
          onChange={(value) => {
            const type = zRunTypeName.safeParse(value);
            void setState({ type: type.success ? type.data : null });
          }}
        />
        <SelectFilter
          id="run-status"
          label="Status"
          value={state.status ?? ""}
          options={optionsFromValues(zRunStatusName.options)}
          onChange={(value) => {
            const status = zRunStatusName.safeParse(value);
            void setState({ status: status.success ? status.data : null });
          }}
        />
        <SelectFilter
          id="run-mismatches"
          label="Has mismatches"
          value={valueFromBoolean(state.mismatches)}
          options={BOOLEAN_OPTIONS}
          onChange={(value) => void setState({ mismatches: booleanFromValue(value) })}
        />
      </FilterPanel>
      <PagedTable
        caption="Reconciliation runs"
        columns={columns}
        rows={flattenCursorPages(runs.data?.pages)}
        getRowId={(run) => run.id}
        isPending={runs.isPending}
        errorMessage={runs.isError ? adminBillingErrorMessage(runs.error) : null}
        onRetry={() => {
          void runs.refetch();
        }}
        emptyState="No reconciliation runs match these filters."
        hasNextPage={runs.hasNextPage}
        isFetchingNextPage={runs.isFetchingNextPage}
        fetchNextPage={runs.fetchNextPage}
      />
    </div>
  );
}
