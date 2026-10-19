"use client";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import { PagedTable } from "@/components/shared/paged-table";
import { Skeleton } from "@/components/ui/skeleton";
import { AdjustCreditsDialog } from "@/features/admin-billing/components/adjust-credits-dialog";
import { AdminBillingError } from "@/features/admin-billing/components/admin-billing-error";
import { DetailSection } from "@/features/admin-billing/components/detail-section";
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import {
  useAdminUserCredits,
  useAdminUserLedger,
} from "@/features/admin-billing/hooks/use-admin-user-credits";
import type {
  AdminLedgerEntry,
  AdminLot,
} from "@/features/admin-billing/types/admin-billing.types";
import { usePermissions } from "@/features/auth/hooks/use-permissions";
import { lotSourceLabels } from "@/features/credits/schemas/credits.schema";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatCredits, formatDateTime, formatSignedCredits, titleCase } from "@/lib/utils/format";

const lotColumn = createDataTableColumnHelper<AdminLot>();

const lotColumns = [
  lotColumn.display({
    id: "source",
    header: "Source",
    cell: ({ row }) => lotSourceLabels[row.original.source],
  }),
  lotColumn.display({
    id: "amount",
    header: "Amount",
    cell: ({ row }) => <span className="font-mono">{formatCredits(row.original.amount)}</span>,
  }),
  lotColumn.display({
    id: "remaining",
    header: "Remaining",
    cell: ({ row }) => <span className="font-mono">{formatCredits(row.original.remaining)}</span>,
  }),
  lotColumn.display({
    id: "expiry",
    header: "Expiry",
    cell: ({ row }) => {
      if (row.original.expiredAt !== null) {
        return `Expired ${formatDateTime(row.original.expiredAt)}`;
      }
      return row.original.expiresAt === null
        ? "Never expires"
        : formatDateTime(row.original.expiresAt);
    },
  }),
  lotColumn.display({
    id: "created",
    header: "Created",
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  }),
];

const ledgerColumn = createDataTableColumnHelper<AdminLedgerEntry>();

const ledgerColumns = [
  ledgerColumn.display({
    id: "date",
    header: "Date",
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  }),
  ledgerColumn.display({
    id: "reason",
    header: "Reason",
    cell: ({ row }) => titleCase(row.original.reason),
  }),
  ledgerColumn.display({
    id: "delta",
    header: "Credits",
    cell: ({ row }) => <span className="font-mono">{formatSignedCredits(row.original.delta)}</span>,
  }),
  ledgerColumn.display({
    id: "reserved",
    header: "Reserved",
    cell: ({ row }) => (
      <span className="font-mono">{formatSignedCredits(row.original.reservedDelta)}</span>
    ),
  }),
  ledgerColumn.display({
    id: "balance",
    header: "Balance after",
    cell: ({ row }) => (
      <span className="font-mono">{formatCredits(row.original.balanceAfter)}</span>
    ),
  }),
  ledgerColumn.display({
    id: "reference",
    header: "Reference",
    cell: ({ row }) =>
      row.original.refType ? (
        <span className="font-mono text-xs">
          {row.original.refType} {row.original.refId?.slice(0, 8) ?? ""}
        </span>
      ) : (
        "-"
      ),
  }),
];

function WalletSection({ userId }: { userId: string }) {
  const credits = useAdminUserCredits(userId);
  const { can } = usePermissions();
  if (credits.isPending) {
    return <Skeleton role="status" aria-label="Loading wallet" className="h-40" />;
  }
  if (credits.isLoadingError) {
    return (
      <AdminBillingError
        error={credits.error}
        onRetry={() => {
          void credits.refetch();
        }}
      />
    );
  }
  const wallet = credits.data.pages[0];
  if (wallet === undefined) {
    return null;
  }
  const lots = credits.data.pages.flatMap((page) => page.lots);
  return (
    <div className="space-y-6">
      <DetailSection
        title="Wallet"
        actions={
          can("billing.credits.adjust") ? (
            <AdjustCreditsDialog userId={userId} availableCredits={wallet.available} />
          ) : null
        }
      >
        <dl className="grid gap-4 sm:grid-cols-3">
          <div>
            <dt className="text-sm text-muted-foreground">Available</dt>
            <dd className="font-mono text-3xl font-semibold">{formatCredits(wallet.available)}</dd>
          </div>
          <div>
            <dt className="text-sm text-muted-foreground">Reserved</dt>
            <dd className="font-mono text-3xl font-semibold">{formatCredits(wallet.reserved)}</dd>
          </div>
          <div>
            <dt className="text-sm text-muted-foreground">Balance</dt>
            <dd className="font-mono text-3xl font-semibold">{formatCredits(wallet.balance)}</dd>
          </div>
        </dl>
        {can("billing.credits.adjust") ? null : (
          <p className="text-sm text-muted-foreground">
            Adjusting credits needs the billing.credits.adjust permission, which your account does
            not have.
          </p>
        )}
      </DetailSection>
      <DetailSection title="Credit lots">
        <PagedTable
          caption="Credit lots"
          columns={lotColumns}
          rows={lots}
          getRowId={(lot) => lot.id}
          isPending={false}
          errorMessage={credits.isError ? adminBillingErrorMessage(credits.error) : null}
          onRetry={() => {
            void credits.fetchNextPage();
          }}
          emptyState="This user has no credit lots."
          hasNextPage={credits.hasNextPage}
          isFetchingNextPage={credits.isFetchingNextPage}
          fetchNextPage={credits.fetchNextPage}
        />
      </DetailSection>
    </div>
  );
}

function LedgerSection({ userId }: { userId: string }) {
  const ledger = useAdminUserLedger(userId);
  return (
    <DetailSection title="Ledger">
      <PagedTable
        caption="Credit ledger"
        columns={ledgerColumns}
        rows={flattenCursorPages(ledger.data?.pages)}
        getRowId={(entry) => entry.id}
        isPending={ledger.isPending}
        errorMessage={ledger.isError ? adminBillingErrorMessage(ledger.error) : null}
        onRetry={() => {
          void ledger.refetch();
        }}
        emptyState="No credit activity yet."
        hasNextPage={ledger.hasNextPage}
        isFetchingNextPage={ledger.isFetchingNextPage}
        fetchNextPage={ledger.fetchNextPage}
      />
    </DetailSection>
  );
}

export function UserCredits({ userId }: { userId: string }) {
  return (
    <div className="space-y-6">
      <WalletSection userId={userId} />
      <LedgerSection userId={userId} />
    </div>
  );
}
