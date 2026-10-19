"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminBillingError } from "@/features/admin-billing/components/admin-billing-error";
import { DetailSection } from "@/features/admin-billing/components/detail-section";
import { useAdminOrders } from "@/features/admin-billing/hooks/use-admin-payments";
import { useAdminRuns } from "@/features/admin-billing/hooks/use-admin-reconciliation";
import { useAdminWebhooks } from "@/features/admin-billing/hooks/use-admin-webhooks";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import {
  flagReasonLabels,
  runTypeLabels,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import { usePermissions } from "@/features/auth/hooks/use-permissions";
import { formatDateTime } from "@/lib/utils/format";

const PREVIEW_LIMIT = 5;

const FLAGGED_ORDERS = { flagged: true } as const;
const MISMATCH_RUNS = { hasMismatches: true } as const;
const FAILED_EVENTS = { status: "failed" } as const;

interface AttentionRowProps {
  label: string;
  count: string;
  action: ReactNode;
  children?: ReactNode;
}

function AttentionRow({ label, count, action, children }: AttentionRowProps) {
  return (
    <li className="space-y-2 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium">
          {label}: <span className="font-mono">{count}</span>
        </p>
        {action}
      </div>
      {children}
    </li>
  );
}

const countLabel = (loaded: number, hasMore: boolean): string =>
  `${String(loaded)}${hasMore ? "+" : ""}`;

function FlaggedOrdersRow() {
  const orders = useAdminOrders(FLAGGED_ORDERS);
  const items = orders.data?.pages.flatMap((page) => page.items) ?? [];
  if (orders.isPending) {
    return (
      <li>
        <Skeleton role="status" aria-label="Loading flagged orders" className="h-16" />
      </li>
    );
  }
  if (orders.isError) {
    return (
      <li>
        <AdminBillingError error={orders.error} />
      </li>
    );
  }
  return (
    <AttentionRow
      label="Orders flagged for review"
      count={countLabel(items.length, orders.hasNextPage)}
      action={
        <Link
          href={{ pathname: adminBillingPaths.orders, query: { flagged: "true" } }}
          className="text-sm underline"
        >
          Review flagged orders
        </Link>
      }
    >
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No orders need review.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {items.slice(0, PREVIEW_LIMIT).map((order) => (
            <li key={order.id} className="flex flex-wrap items-center gap-2">
              <Link href={adminBillingPaths.order(order.id)} className="hover:underline">
                {order.productName}
              </Link>
              {order.flagReason ? (
                <Badge variant="destructive">{flagReasonLabels[order.flagReason]}</Badge>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </AttentionRow>
  );
}

function MismatchRunsRow() {
  const runs = useAdminRuns(MISMATCH_RUNS);
  const items = runs.data?.pages.flatMap((page) => page.items) ?? [];
  if (runs.isPending) {
    return (
      <li>
        <Skeleton role="status" aria-label="Loading reconciliation runs" className="h-16" />
      </li>
    );
  }
  if (runs.isError) {
    return (
      <li>
        <AdminBillingError error={runs.error} />
      </li>
    );
  }
  return (
    <AttentionRow
      label="Reconciliation runs with mismatches"
      count={countLabel(items.length, runs.hasNextPage)}
      action={
        <Link
          href={{ pathname: adminBillingPaths.reconciliation, query: { mismatches: "true" } }}
          className="text-sm underline"
        >
          Review reconciliation runs
        </Link>
      }
    >
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No run found a mismatch.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {items.slice(0, PREVIEW_LIMIT).map((run) => (
            <li key={run.id}>
              <Link href={adminBillingPaths.run(run.id)} className="hover:underline">
                {runTypeLabels[run.type]} on {formatDateTime(run.startedAt)}
              </Link>{" "}
              <span className="font-mono">({run.mismatchCount})</span>
            </li>
          ))}
        </ul>
      )}
    </AttentionRow>
  );
}

function FailedWebhooksRow() {
  const events = useAdminWebhooks(FAILED_EVENTS);
  const items = events.data?.pages.flatMap((page) => page.items) ?? [];
  if (events.isPending) {
    return (
      <li>
        <Skeleton role="status" aria-label="Loading webhook events" className="h-16" />
      </li>
    );
  }
  if (events.isError) {
    return (
      <li>
        <AdminBillingError error={events.error} />
      </li>
    );
  }
  return (
    <AttentionRow
      label="Failed webhook events"
      count={countLabel(items.length, events.hasNextPage)}
      action={
        <Link
          href={{ pathname: adminBillingPaths.webhooks, query: { status: "failed" } }}
          className="text-sm underline"
        >
          Review failed events
        </Link>
      }
    />
  );
}

export function AttentionPanel() {
  const { can } = usePermissions();
  return (
    <DetailSection title="Needs attention">
      <ul className="grid gap-3 lg:grid-cols-2">
        <FlaggedOrdersRow />
        <MismatchRunsRow />
        {can("billing.webhooks.manage") ? <FailedWebhooksRow /> : null}
      </ul>
    </DetailSection>
  );
}
