"use client";

import Link from "next/link";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import { PagedTable } from "@/components/shared/paged-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { billingErrorMessage } from "@/features/billing/errors";
import { useBillingHistory } from "@/features/billing/hooks/use-billing-history";
import type { HistoryItem } from "@/features/billing/types/billing.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatCredits, formatDateTime, formatPaise, titleCase } from "@/lib/utils/format";

const column = createDataTableColumnHelper<HistoryItem>();

const columns = [
  column.display({
    id: "date",
    header: "Date",
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  }),
  column.display({
    id: "title",
    header: "Description",
    cell: ({ row }) => (
      <div className="flex flex-col gap-1">
        <span className="font-medium">{row.original.title}</span>
        <Badge variant="outline" className="w-fit capitalize">
          {row.original.type}
        </Badge>
      </div>
    ),
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <Badge variant={row.original.status === "paid" ? "success" : "outline"}>
        {titleCase(row.original.status)}
      </Badge>
    ),
  }),
  column.display({
    id: "amount",
    header: "Amount (incl. GST)",
    cell: ({ row }) => (
      <span className="font-mono">
        {row.original.type === "refund" ? "-" : ""}
        {formatPaise(row.original.amountPaise)}
      </span>
    ),
  }),
  column.display({
    id: "credits",
    header: "Credits",
    cell: ({ row }) => (
      <span className="font-mono">
        {row.original.creditsGranted ? formatCredits(row.original.creditsGranted) : "-"}
      </span>
    ),
  }),
  column.display({
    id: "details",
    header: () => <span className="sr-only">Details</span>,
    cell: ({ row }) =>
      row.original.orderId ? (
        <Button asChild variant="ghost" size="sm">
          <Link
            href={`/billing/status/${row.original.orderId}`}
            aria-label={`View ${row.original.title}`}
          >
            View
          </Link>
        </Button>
      ) : null,
  }),
];

export function OrdersTable() {
  const history = useBillingHistory();
  return (
    <PagedTable
      caption="Payments and orders"
      columns={columns}
      rows={flattenCursorPages(history.data?.pages)}
      getRowId={(item) => `${item.type}-${item.id}`}
      isPending={history.isPending}
      errorMessage={history.isError ? billingErrorMessage(history.error) : null}
      onRetry={() => {
        void history.refetch();
      }}
      emptyState="No payments or orders yet."
      hasNextPage={history.hasNextPage}
      isFetchingNextPage={history.isFetchingNextPage}
      fetchNextPage={history.fetchNextPage}
    />
  );
}
