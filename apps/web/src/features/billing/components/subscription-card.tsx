import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import type { Subscription, SubscriptionStatus } from "@/features/billing/types/billing.types";
import { formatCredits, formatDate, formatPaise } from "@/lib/utils/format";

export const subscriptionStatusLabels: Readonly<Record<SubscriptionStatus, string>> = {
  created: "Awaiting payment",
  authenticated: "Authorised",
  active: "Active",
  pending: "Payment pending",
  halted: "Payment failed",
  paused: "Paused",
  cancelled: "Cancelled",
  completed: "Completed",
  expired: "Expired",
};

const badgeVariant = (status: SubscriptionStatus) => {
  if (status === "active") {
    return "success";
  }
  if (status === "halted") {
    return "destructive";
  }
  return "outline";
};

export const subscriptionEndDate = (subscription: Subscription): string | null =>
  subscription.endsAt ?? subscription.currentPeriodEnd;

const intervalNoun = (subscription: Subscription): string =>
  subscription.product.interval === "year" ? "year" : "month";

interface SubscriptionCardProps {
  subscription: Subscription;
  actions?: ReactNode;
}

export function SubscriptionCard({ subscription, actions }: SubscriptionCardProps) {
  const { product, pendingProduct } = subscription;
  const endDate = subscriptionEndDate(subscription);
  return (
    <section
      aria-labelledby="current-plan-title"
      className="space-y-4 rounded-xl border bg-surface p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="current-plan-title" className="font-semibold">
          Current plan
        </h2>
        <Badge variant={badgeVariant(subscription.status)}>
          {subscriptionStatusLabels[subscription.status]}
        </Badge>
      </div>
      <div>
        <p className="text-xl font-semibold">{product.name}</p>
        <p className="mt-1 text-sm text-subtle-foreground">
          {formatPaise(product.pricePaise)} per {intervalNoun(subscription)} incl. GST,{" "}
          {formatCredits(product.creditsGranted)} credits each {intervalNoun(subscription)}
        </p>
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        {subscription.currentPeriodStart && subscription.currentPeriodEnd ? (
          <div>
            <dt className="text-muted-foreground">Current period</dt>
            <dd>
              {formatDate(subscription.currentPeriodStart)} to{" "}
              {formatDate(subscription.currentPeriodEnd)}
            </dd>
          </div>
        ) : null}
        {!subscription.cancelAtPeriodEnd && subscription.nextChargeAt ? (
          <div>
            <dt className="text-muted-foreground">Next charge</dt>
            <dd>
              {formatPaise((pendingProduct ?? product).pricePaise)} incl. GST on{" "}
              {formatDate(subscription.nextChargeAt)}
            </dd>
          </div>
        ) : null}
      </dl>
      {subscription.cancelAtPeriodEnd && endDate ? (
        <p role="note" className="rounded-md border bg-elevated p-3 text-sm">
          Your subscription ends on {formatDate(endDate)}. You will not be charged again, and your
          subscription credits stay available until then.
        </p>
      ) : null}
      {pendingProduct && subscription.currentPeriodEnd ? (
        <p role="note" className="rounded-md border bg-elevated p-3 text-sm">
          Your plan changes to {pendingProduct.name} on {formatDate(subscription.currentPeriodEnd)}.
        </p>
      ) : null}
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </section>
  );
}
