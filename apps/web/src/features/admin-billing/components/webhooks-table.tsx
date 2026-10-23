"use client";

import { zWebhookStatusName } from "@motionile/api-contract";
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
import { adminBillingErrorMessage } from "@/features/admin-billing/errors";
import {
  toWebhookFilters,
  useWebhookFilterState,
} from "@/features/admin-billing/hooks/use-admin-billing-filters";
import { useAdminWebhooks } from "@/features/admin-billing/hooks/use-admin-webhooks";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import type { AdminWebhookEvent } from "@/features/admin-billing/types/admin-billing.types";
import { flattenCursorPages } from "@/lib/api/pagination";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { formatDateTime } from "@/lib/utils/format";

const SEARCH_DEBOUNCE_MS = 300;

const column = createDataTableColumnHelper<AdminWebhookEvent>();

const columns = [
  column.display({
    id: "received",
    header: "Received",
    cell: ({ row }) => formatDateTime(row.original.receivedAt),
  }),
  column.display({
    id: "event",
    header: "Event",
    cell: ({ row }) => (
      <div className="flex flex-col">
        <Link
          href={adminBillingPaths.webhook(row.original.id)}
          className="font-mono text-sm hover:underline"
        >
          {row.original.eventType}
        </Link>
        <span className="font-mono text-xs text-muted-foreground">{row.original.eventId}</span>
      </div>
    ),
  }),
  column.display({
    id: "status",
    header: "Status",
    cell: ({ row }) => <StatusBadge status={row.original.status} />,
  }),
  column.display({
    id: "attempts",
    header: "Attempts",
    cell: ({ row }) => <span className="font-mono">{row.original.attempts}</span>,
  }),
  column.display({
    id: "note",
    header: "Last error or reason",
    cell: ({ row }) => (
      <span className="block max-w-64 truncate">
        {row.original.lastError ?? row.original.ignoredReason ?? "-"}
      </span>
    ),
  }),
];

export function WebhooksTable() {
  const [state, setState] = useWebhookFilterState();
  const eventType = useDebouncedValue(state.type, SEARCH_DEBOUNCE_MS);
  const webhooks = useAdminWebhooks(toWebhookFilters({ ...state, type: eventType }));
  return (
    <div className="space-y-5">
      <FilterPanel
        label="Webhook filters"
        onClear={() => {
          void setState(null);
        }}
      >
        <SelectFilter
          id="webhook-status"
          label="Status"
          value={state.status ?? ""}
          options={optionsFromValues(zWebhookStatusName.options)}
          onChange={(value) => {
            const status = zWebhookStatusName.safeParse(value);
            void setState({ status: status.success ? status.data : null });
          }}
        />
        <TextFilter
          id="webhook-type"
          label="Event type"
          placeholder="payment.captured"
          value={state.type}
          onChange={(value) => void setState({ type: value.trim() || null })}
        />
        <TextFilter
          id="webhook-from"
          label="Received from"
          type="date"
          value={state.from}
          onChange={(value) => void setState({ from: value || null })}
        />
        <TextFilter
          id="webhook-to"
          label="Received to"
          type="date"
          value={state.to}
          onChange={(value) => void setState({ to: value || null })}
        />
      </FilterPanel>
      <PagedTable
        caption="Webhook events"
        columns={columns}
        rows={flattenCursorPages(webhooks.data?.pages)}
        getRowId={(event) => event.id}
        isPending={webhooks.isPending}
        errorMessage={webhooks.isError ? adminBillingErrorMessage(webhooks.error) : null}
        onRetry={() => {
          void webhooks.refetch();
        }}
        emptyState="No webhook events match these filters."
        hasNextPage={webhooks.hasNextPage}
        isFetchingNextPage={webhooks.isFetchingNextPage}
        fetchNextPage={webhooks.fetchNextPage}
      />
    </div>
  );
}
