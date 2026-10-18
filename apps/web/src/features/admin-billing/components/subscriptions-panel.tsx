"use client";

import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AdminBillingError } from "@/features/admin-billing/components/admin-billing-error";
import { DetailSection } from "@/features/admin-billing/components/detail-section";
import { useSubscriptionAnalytics } from "@/features/admin-billing/hooks/use-admin-analytics";
import { intervalLabels } from "@/features/admin-billing/schemas/admin-billing.schema";
import type { SubscriptionAnalytics } from "@/features/admin-billing/types/admin-billing.types";
import { formatCredits, titleCase } from "@/lib/utils/format";

export function SubscriptionsView({ data }: { data: SubscriptionAnalytics }) {
  const statuses = Object.entries(data.byStatus);
  return (
    <div className="space-y-5">
      <dl className="grid gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-sm text-muted-foreground">Active subscriptions</dt>
          <dd className="font-mono text-2xl font-semibold">{formatCredits(data.totalActive)}</dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Live subscriptions</dt>
          <dd className="font-mono text-2xl font-semibold">{formatCredits(data.totalLive)}</dd>
        </div>
      </dl>
      {data.byPlan.length === 0 ? (
        <p className="text-sm text-muted-foreground">There are no subscription plans yet.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Plan</TableHead>
              <TableHead scope="col">Interval</TableHead>
              <TableHead scope="col">Active</TableHead>
              <TableHead scope="col">Live</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.byPlan.map((plan) => (
              <TableRow key={plan.productCode}>
                <TableCell>
                  <span className="font-medium">{plan.productName}</span>{" "}
                  <span className="font-mono text-xs text-muted-foreground">
                    {plan.productCode}
                  </span>
                </TableCell>
                <TableCell>
                  {plan.interval === "month" || plan.interval === "year"
                    ? intervalLabels[plan.interval]
                    : "-"}
                </TableCell>
                <TableCell className="font-mono">{formatCredits(plan.activeCount)}</TableCell>
                <TableCell className="font-mono">{formatCredits(plan.liveCount)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {statuses.length === 0 ? null : (
        <div>
          <h3 className="mb-2 text-sm font-medium">By status</h3>
          <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
            {statuses.map(([status, count]) => (
              <div key={status}>
                <dt className="text-muted-foreground">{titleCase(status)}</dt>
                <dd className="font-mono">{formatCredits(count)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

export function SubscriptionsPanel() {
  const subscriptions = useSubscriptionAnalytics();
  return (
    <DetailSection title="Subscriptions by plan">
      {subscriptions.isPending ? (
        <Skeleton role="status" aria-label="Loading subscriptions" className="h-48" />
      ) : subscriptions.isError ? (
        <AdminBillingError
          error={subscriptions.error}
          onRetry={() => {
            void subscriptions.refetch();
          }}
        />
      ) : (
        <SubscriptionsView data={subscriptions.data} />
      )}
    </DetailSection>
  );
}
