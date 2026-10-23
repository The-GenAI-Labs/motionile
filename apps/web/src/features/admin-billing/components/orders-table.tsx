"use client";

import { zOrderStatusName } from "@motionile/api-contract";
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
  toOrderFilters,
  useOrderFilterState,
} from "@/features/admin-billing/hooks/use-admin-billing-filters";
import { useAdminOrders } from "@/features/admin-billing/hooks/use-admin-payments";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import { flagReasonLabels } from "@/features/admin-billing/schemas/admin-billing.schema";
import type { AdminOrder } from "@/features/admin-billing/types/admin-billing.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatDateTime, formatPaise } from "@/lib/utils/format";

const column = createDataTableColumnHelper<AdminOrder>();

const columns = [
  column.display({
    id: "date",
    header: "Created",
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  }),
  column.display({
    id: "order",
    header: "Order",
    cell: ({ row }) => (
      <div className="flex flex-col">
        <Link
          href={adminBillingPaths.order(row.original.id)}
          className="font-medium hover:underline"
        >
          {row.original.productName}
        </Link>
        <span className="font-mono text-xs text-muted-foreground">{row.original.receipt}</span>
      </div>
    ),
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <div className="flex flex-wrap gap-1">
        <StatusBadge status={row.original.status} />
        {row.original.flagReason ? (
          <Badge variant="destructive">{flagReasonLabels[row.original.flagReason]}</Badge>
        ) : null}
      </div>
    ),
  }),
  column.display({
    id: "amount",
    header: "Amount (incl. GST)",
    cell: ({ row }) => <span className="font-mono">{formatPaise(row.original.amountPaise)}</span>,
  }),
  column.display({
    id: "user",
    header: "User",
    cell: ({ row }) => (
      <Link
        href={adminBillingPaths.user(row.original.userId)}
        className="font-mono text-xs hover:underline"
      >
        {row.original.userId.slice(0, 8)}
      </Link>
    ),
  }),
];

export function OrdersTable() {
  const [state, setState] = useOrderFilterState();
  const orders = useAdminOrders(toOrderFilters(state));
  return (
    <div className="space-y-5">
      <FilterPanel
        label="Order filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <SelectFilter
          id="order-status"
          label="Status"
          value={state.status ?? ""}
          options={optionsFromValues(zOrderStatusName.options)}
          onChange={(value) => {
            const status = zOrderStatusName.safeParse(value);
            void setState({ status: status.success ? status.data : null });
          }}
        />
        <SelectFilter
          id="order-flagged"
          label="Flagged for review"
          value={valueFromBoolean(state.flagged)}
          options={BOOLEAN_OPTIONS}
          onChange={(value) => void setState({ flagged: booleanFromValue(value) })}
        />
        <TextFilter
          id="order-user"
          label="User ID"
          value={state.user}
          onChange={(value) => void setState({ user: value.trim() || null })}
        />
      </FilterPanel>
      <PagedTable
        caption="Orders"
        columns={columns}
        rows={flattenCursorPages(orders.data?.pages)}
        getRowId={(order) => order.id}
        isPending={orders.isPending}
        errorMessage={orders.isError ? adminBillingErrorMessage(orders.error) : null}
        onRetry={() => {
          void orders.refetch();
        }}
        emptyState="No orders match these filters."
        hasNextPage={orders.hasNextPage}
        isFetchingNextPage={orders.isFetchingNextPage}
        fetchNextPage={orders.fetchNextPage}
      />
    </div>
  );
}
