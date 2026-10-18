"use client";

import { zRefundStatusName } from "@motionile/api-contract";
import Link from "next/link";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import { PagedTable } from "@/components/shared/paged-table";
import {
  FilterPanel,
  optionsFromValues,
  SelectFilter,
  TextFilter,
} from "@/features/admin-billing/components/filter-fields";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import {
  toRefundFilters,
  useRefundFilterState,
} from "@/features/admin-billing/hooks/use-admin-billing-filters";
import { useAdminRefunds } from "@/features/admin-billing/hooks/use-admin-payments";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import type { AdminRefund } from "@/features/admin-billing/types/admin-billing.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatCredits, formatDateTime, formatPaise } from "@/lib/utils/format";

const column = createDataTableColumnHelper<AdminRefund>();

const columns = [
  column.display({
    id: "date",
    header: "Created",
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  }),
  column.display({
    id: "refund",
    header: "Refund",
    cell: ({ row }) => (
      <Link
        href={adminBillingPaths.refund(row.original.id)}
        className="font-mono text-xs hover:underline"
      >
        {row.original.razorpayRefundId ?? row.original.id.slice(0, 8)}
      </Link>
    ),
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => <StatusBadge status={row.original.status} />,
  }),
  column.display({
    id: "amount",
    header: "Amount",
    cell: ({ row }) => <span className="font-mono">{formatPaise(row.original.amountPaise)}</span>,
  }),
  column.display({
    id: "clawback",
    header: "Credits clawed back",
    cell: ({ row }) => (
      <span className="font-mono">{formatCredits(row.original.creditsClawedBack)}</span>
    ),
  }),
  column.display({
    id: "reason",
    header: "Reason",
    cell: ({ row }) => <span className="block max-w-64 truncate">{row.original.reason}</span>,
  }),
];

export function RefundsTable() {
  const [state, setState] = useRefundFilterState();
  const refunds = useAdminRefunds(toRefundFilters(state));
  return (
    <div className="space-y-5">
      <FilterPanel
        label="Refund filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <SelectFilter
          id="refund-status"
          label="Status"
          value={state.status ?? ""}
          options={optionsFromValues(zRefundStatusName.options)}
          onChange={(value) => {
            const status = zRefundStatusName.safeParse(value);
            void setState({ status: status.success ? status.data : null });
          }}
        />
        <TextFilter
          id="refund-payment"
          label="Payment ID"
          value={state.payment}
          onChange={(value) => void setState({ payment: value.trim() || null })}
        />
      </FilterPanel>
      <PagedTable
        caption="Refunds"
        columns={columns}
        rows={flattenCursorPages(refunds.data?.pages)}
        getRowId={(refund) => refund.id}
        isPending={refunds.isPending}
        errorMessage={refunds.isError ? adminBillingErrorMessage(refunds.error) : null}
        onRetry={() => {
          void refunds.refetch();
        }}
        emptyState="No refunds match these filters."
        hasNextPage={refunds.hasNextPage}
        isFetchingNextPage={refunds.isFetchingNextPage}
        fetchNextPage={refunds.fetchNextPage}
      />
    </div>
  );
}
