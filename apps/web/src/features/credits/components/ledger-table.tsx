"use client";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import { PagedTable } from "@/components/shared/paged-table";
import { billingErrorMessage } from "@/features/billing/errors";
import { useLedger } from "@/features/credits/hooks/use-credit-history";
import { ledgerReasonLabels } from "@/features/credits/schemas/credits.schema";
import type { LedgerEntry } from "@/features/credits/types/credits.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatCredits, formatDateTime, formatSignedCredits } from "@/lib/utils/format";

const column = createDataTableColumnHelper<LedgerEntry>();

const columns = [
  column.display({
    id: "date",
    header: "Date",
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  }),
  column.display({
    id: "activity",
    header: "Activity",
    cell: ({ row }) => ledgerReasonLabels[row.original.reason],
  }),
  column.display({
    id: "change",
    header: "Credits",
    cell: ({ row }) => <span className="font-mono">{formatSignedCredits(row.original.delta)}</span>,
  }),
  column.display({
    id: "reserved",
    header: "Reserved",
    cell: ({ row }) => (
      <span className="font-mono">{formatSignedCredits(row.original.reservedDelta)}</span>
    ),
  }),
  column.display({
    id: "balance",
    header: "Balance after",
    cell: ({ row }) => (
      <span className="font-mono">{formatCredits(row.original.balanceAfter)}</span>
    ),
  }),
];

export function LedgerTable() {
  const ledger = useLedger();
  return (
    <PagedTable
      caption="Credit ledger"
      columns={columns}
      rows={flattenCursorPages(ledger.data?.pages)}
      getRowId={(entry) => entry.id}
      isPending={ledger.isPending}
      errorMessage={ledger.isError ? billingErrorMessage(ledger.error) : null}
      onRetry={() => {
        void ledger.refetch();
      }}
      emptyState="No credit activity yet."
      hasNextPage={ledger.hasNextPage}
      isFetchingNextPage={ledger.isFetchingNextPage}
      fetchNextPage={ledger.fetchNextPage}
    />
  );
}
