"use client";

import { zPaymentStatusName } from "@motionile/api-contract";
import Link from "next/link";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import {
  BOOLEAN_OPTIONS,
  booleanFromValue,
  FilterPanel,
  optionsFromValues,
  SelectFilter,
  TextFilter,
  valueFromBoolean,
} from "@/components/shared/filter-fields";
import { PagedTable } from "@/components/shared/paged-table";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import {
  toPaymentFilters,
  usePaymentFilterState,
} from "@/features/admin-billing/hooks/use-admin-billing-filters";
import { useAdminPayments } from "@/features/admin-billing/hooks/use-admin-payments";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import type { AdminPayment } from "@/features/admin-billing/types/admin-billing.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatCredits, formatDateTime, formatPaise } from "@/lib/utils/format";

const column = createDataTableColumnHelper<AdminPayment>();

const columns = [
  column.display({
    id: "date",
    header: "Date",
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  }),
  column.display({
    id: "payment",
    header: "Payment",
    cell: ({ row }) => (
      <Link
        href={adminBillingPaths.payment(row.original.id)}
        className="font-mono text-xs hover:underline"
      >
        {row.original.razorpayPaymentId}
      </Link>
    ),
  }),
  column.display({
    id: "product",
    header: "Product",
    cell: ({ row }) => row.original.productName ?? "-",
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <div className="flex flex-wrap gap-1">
        <StatusBadge status={row.original.status} />
        {row.original.flagged ? <Badge variant="destructive">Flagged</Badge> : null}
      </div>
    ),
  }),
  column.display({
    id: "amount",
    header: "Amount (incl. GST)",
    cell: ({ row }) => <span className="font-mono">{formatPaise(row.original.amountPaise)}</span>,
  }),
  column.display({
    id: "refunded",
    header: "Refunded",
    cell: ({ row }) => <span className="font-mono">{formatPaise(row.original.refundedPaise)}</span>,
  }),
  column.display({
    id: "credits",
    header: "Credits",
    cell: ({ row }) => (
      <span className="font-mono">{formatCredits(row.original.creditsGranted)}</span>
    ),
  }),
];

export function PaymentsTable() {
  const [state, setState] = usePaymentFilterState();
  const payments = useAdminPayments(toPaymentFilters(state));
  return (
    <div className="space-y-5">
      <FilterPanel
        label="Payment filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <SelectFilter
          id="payment-status"
          label="Status"
          value={state.status ?? ""}
          options={optionsFromValues(zPaymentStatusName.options)}
          onChange={(value) => {
            const status = zPaymentStatusName.safeParse(value);
            void setState({ status: status.success ? status.data : null });
          }}
        />
        <SelectFilter
          id="payment-flagged"
          label="Flagged"
          value={valueFromBoolean(state.flagged)}
          options={BOOLEAN_OPTIONS}
          onChange={(value) => void setState({ flagged: booleanFromValue(value) })}
        />
        <TextFilter
          id="payment-user"
          label="User ID"
          value={state.user}
          onChange={(value) => void setState({ user: value.trim() || null })}
        />
        <TextFilter
          id="payment-order"
          label="Order ID"
          value={state.order}
          onChange={(value) => void setState({ order: value.trim() || null })}
        />
        <TextFilter
          id="payment-from"
          label="From"
          type="date"
          value={state.from}
          onChange={(value) => void setState({ from: value || null })}
        />
        <TextFilter
          id="payment-to"
          label="To"
          type="date"
          value={state.to}
          onChange={(value) => void setState({ to: value || null })}
        />
      </FilterPanel>
      <PagedTable
        caption="Payments"
        columns={columns}
        rows={flattenCursorPages(payments.data?.pages)}
        getRowId={(payment) => payment.id}
        isPending={payments.isPending}
        errorMessage={payments.isError ? adminBillingErrorMessage(payments.error) : null}
        onRetry={() => {
          void payments.refetch();
        }}
        emptyState="No payments match these filters."
        hasNextPage={payments.hasNextPage}
        isFetchingNextPage={payments.isFetchingNextPage}
        fetchNextPage={payments.fetchNextPage}
      />
    </div>
  );
}
