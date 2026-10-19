"use client";

import { zSubscriptionStatusName } from "@motionile/api-contract";
import Link from "next/link";

import { createDataTableColumnHelper } from "@/components/shared/data-table";
import { PagedTable } from "@/components/shared/paged-table";
import { Badge } from "@/components/ui/badge";
import {
  FilterPanel,
  optionsFromValues,
  SelectFilter,
  TextFilter,
} from "@/features/admin-billing/components/filter-fields";
import { StatusBadge } from "@/features/admin-billing/components/status-badge";
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import {
  toSubscriptionFilters,
  useSubscriptionFilterState,
} from "@/features/admin-billing/hooks/use-admin-billing-filters";
import { useAdminSubscriptions } from "@/features/admin-billing/hooks/use-admin-subscriptions";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import { intervalLabels } from "@/features/admin-billing/schemas/admin-billing.schema";
import type { AdminSubscription } from "@/features/admin-billing/types/admin-billing.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { formatDate, formatDateTime, formatPaise } from "@/lib/utils/format";

const column = createDataTableColumnHelper<AdminSubscription>();

const columns = [
  column.display({
    id: "created",
    header: "Created",
    cell: ({ row }) => formatDateTime(row.original.createdAt),
  }),
  column.display({
    id: "plan",
    header: "Plan",
    cell: ({ row }) => (
      <div className="flex flex-col">
        <Link
          href={adminBillingPaths.subscription(row.original.id)}
          className="font-medium hover:underline"
        >
          {row.original.product.name}
        </Link>
        <span className="text-xs text-muted-foreground">
          {formatPaise(row.original.product.pricePaise)} incl. GST
          {row.original.product.interval
            ? `, ${intervalLabels[row.original.product.interval].toLowerCase()}`
            : ""}
        </span>
      </div>
    ),
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => (
      <div className="flex flex-wrap gap-1">
        <StatusBadge status={row.original.status} />
        {row.original.cancelAtPeriodEnd ? (
          <Badge variant="outline">Ends at period end</Badge>
        ) : null}
      </div>
    ),
  }),
  column.display({
    id: "period",
    header: "Current period ends",
    cell: ({ row }) =>
      row.original.currentPeriodEnd ? formatDate(row.original.currentPeriodEnd) : "-",
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

export function SubscriptionsTable() {
  const [state, setState] = useSubscriptionFilterState();
  const subscriptions = useAdminSubscriptions(toSubscriptionFilters(state));
  return (
    <div className="space-y-5">
      <FilterPanel
        label="Subscription filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <SelectFilter
          id="subscription-status"
          label="Status"
          value={state.status ?? ""}
          options={optionsFromValues(zSubscriptionStatusName.options)}
          onChange={(value) => {
            const status = zSubscriptionStatusName.safeParse(value);
            void setState({ status: status.success ? status.data : null });
          }}
        />
        <TextFilter
          id="subscription-plan"
          label="Plan key"
          value={state.plan}
          onChange={(value) => void setState({ plan: value.trim() || null })}
        />
        <TextFilter
          id="subscription-user"
          label="User ID"
          value={state.user}
          onChange={(value) => void setState({ user: value.trim() || null })}
        />
      </FilterPanel>
      <PagedTable
        caption="Subscriptions"
        columns={columns}
        rows={flattenCursorPages(subscriptions.data?.pages)}
        getRowId={(subscription) => subscription.id}
        isPending={subscriptions.isPending}
        errorMessage={subscriptions.isError ? adminBillingErrorMessage(subscriptions.error) : null}
        onRetry={() => {
          void subscriptions.refetch();
        }}
        emptyState="No subscriptions match these filters."
        hasNextPage={subscriptions.hasNextPage}
        isFetchingNextPage={subscriptions.isFetchingNextPage}
        fetchNextPage={subscriptions.fetchNextPage}
      />
    </div>
  );
}
